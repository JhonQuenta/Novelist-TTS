import base64,io,tempfile,time,unittest,wave,zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.flac import Picture
from novelavoz import books,exporter as e
from test_core import sample_epub

class AudioOptionsTests(unittest.TestCase):
    def test_uploaded_audio_cover_preserves_book_cover_and_video_background(self):
        from novelavoz.server import Handler
        from email.message import Message
        with tempfile.TemporaryDirectory() as directory,patch.object(books,'BOOKS',Path(directory)):
            book=books.import_epub(sample_epub(),'prueba.epub')
            cover,background=book['cover'],book.get('background')
            payload=io.BytesIO();Image.new('RGB',(60,80),'red').save(payload,'PNG');raw=payload.getvalue()
            handler=object.__new__(Handler);handler.path='/api/upload-image?book='+book['id']+'&target=audio-cover'
            handler.headers=Message();handler.headers['Content-Length']=str(len(raw));handler.rfile=io.BytesIO(raw)
            handler.guard=lambda *args:None;responses=[];handler.json=lambda data,status=200:responses.append((data,status))
            handler.do_POST()
            result,status=responses[0];self.assertEqual(status,200,result)
            self.assertEqual(result['cover'],cover);self.assertEqual(result.get('background'),background)
            self.assertTrue(result['images'][-1]['id'].startswith('custom-'))
            self.assertTrue(books.image_file(result,result['images'][-1]['id']).is_file())

    def test_validation_and_legacy_defaults(self):
        options=e.audio_options({},['mp3'])
        self.assertTrue(options['embed_cover']);self.assertTrue(options['embed_lyrics'])
        self.assertIsNone(options['bitrate'])
        for raw in ({'bitrate':12},{'bitrate':True},{'embed_cover':'false'},{'embed_lyrics':0},{'sidecar_lyrics':None}):
            with self.assertRaises(ValueError):e.audio_options({'audio':raw},['mp3'])
        for fmt,rates in e.AUDIO_BITRATES.items():
            for rate in rates:self.assertEqual(e.audio_options({'audio':{'bitrate':rate}},[fmt])['bitrate'],rate)

    def test_real_exports_selected_quality_custom_cover_and_optional_lyrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(books,'BOOKS',root/'books'),patch.object(e,'JOBS',root/'jobs'),patch.object(e,'EXPORTS',root/'exports'),patch.object(e,'STATES',{}),patch.object(e,'CANCEL',set()),patch.object(e,'DELETE_REQUESTED',set()):
                book=books.import_epub(sample_epub(),'prueba.epub');e.JOBS.mkdir()
                custom=books.book_path(book['id'])/'book'/'custom.png';Image.new('RGB',(70,110),'#ee1111').save(custom)
                book['images'].append({'id':'custom','path':'custom.png','rotation':0,'excluded':False})
                original_cover=book['cover'];original_background=book.get('background')
                def fake(text,settings,output,cancel=None,**kwargs):
                    with wave.open(str(output),'wb') as w:
                        w.setparams((1,2,24000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*24000)
                cases=[('mp3',192,True,False,'custom',False),('m4a',128,False,True,None,True),('opus',64,True,True,'custom',True)]
                with patch.object(e,'synthesize',side_effect=fake):
                    for index,(fmt,bitrate,cover_on,lyrics_on,image,lrc_on) in enumerate(cases,1):
                        job=f'{index:016x}';e.STATES[job]={'id':job,'status':'queued','created':time.time(),'files':[]}
                        options={'chapters':[1,2],'batch_size':2,'formats':[fmt],'voice':{'engine':'edge','voice':'es-MX-JorgeNeural'},'audio':{'bitrate':bitrate,'embed_cover':cover_on,'embed_lyrics':lyrics_on,'cover_image':image,'sidecar_lyrics':lrc_on}}
                        e.execute(job,book,options,False)
                        self.assertEqual(e.STATES[job]['status'],'done',e.STATES[job])
                        folder=e.EXPORTS/job;path=next(folder.glob('*.'+fmt));self.assertEqual(len(list(folder.glob('*.'+fmt))),1)
                        if fmt=='mp3':
                            from mutagen.mp3 import MP3
                            self.assertAlmostEqual(MP3(path).info.bitrate,192000,delta=100)
                            tags=ID3(path);pictures=[x.data for x in tags.getall('APIC')];lyrics=bool(tags.getall('USLT') or tags.getall('SYLT'))
                        elif fmt=='m4a':
                            tags=MP4(path);pictures=tags.get('covr',[]);lyrics=bool(tags.get('\xa9lyr'))
                        else:
                            tags=OggOpus(path);pictures=[Picture(base64.b64decode(x)).data for x in tags.get('metadata_block_picture',[])];lyrics=bool(tags.get('lyrics'))
                        self.assertEqual(bool(pictures),cover_on);self.assertEqual(lyrics,lyrics_on)
                        if pictures:
                            rgb=Image.open(io.BytesIO(bytes(pictures[0]))).getpixel((20,20));self.assertGreater(rgb[0],200);self.assertLess(rgb[1],40)
                        with zipfile.ZipFile(folder/'NovelistTTS.zip') as z:
                            self.assertIsNone(z.testzip());self.assertEqual(any(n.endswith('.lrc') for n in z.namelist()),lrc_on)
                            self.assertFalse(any(n.endswith('.srt') for n in z.namelist()))
                        self.assertEqual(book['cover'],original_cover);self.assertEqual(book.get('background'),original_background)
                        # Re-tagging with both options disabled must remove existing frames.
                        e.tag_audio(path,book,'Prueba',1,'texto',[],None,False)
                        if fmt=='mp3':self.assertFalse(ID3(path).getall('APIC') or ID3(path).getall('USLT') or ID3(path).getall('SYLT'))
                        elif fmt=='m4a':self.assertFalse(MP4(path).get('covr') or MP4(path).get('\xa9lyr'))
                        else:self.assertFalse(OggOpus(path).get('metadata_block_picture') or OggOpus(path).get('lyrics'))
