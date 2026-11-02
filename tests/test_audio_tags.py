import base64,io,tempfile,unittest,wave
from pathlib import Path
from PIL import Image
from novelavoz.exporter import tag_audio
from novelavoz.engines import run,ffmpeg

class AudioTagsTests(unittest.TestCase):
    def test_real_encoded_files_retain_embedded_cover_and_lyrics(self):
        from mutagen.id3 import ID3
        from mutagen.mp4 import MP4
        from mutagen.oggopus import OggOpus
        from mutagen.flac import Picture
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);wav=folder/'test.wav'
            with wave.open(str(wav),'wb') as audio:
                audio.setparams((1,2,24000,0,'NONE','not compressed'));audio.writeframes(b'\0\0'*12000)
            image=io.BytesIO();Image.new('RGB',(120,180),'#bb4422').save(image,'JPEG');cover=image.getvalue()
            cues=[{'text':'¿Qué ocurrió? ¡Sonrió! Ñandú, niña, canción, pingüino: áéíóú ÁÉÍÓÚ Ññ.','start':0,'end':.5}]
            book={'title':'Novela de prueba','author':'Autora'};lrc='[00:00.00]¿Qué ocurrió? ¡Sonrió! Ñandú, niña, canción, pingüino: áéíóú ÁÉÍÓÚ Ññ.\n'
            for ext,codec in [('mp3','libmp3lame'),('m4a','aac'),('opus','libopus')]:
                path=folder/('test.'+ext)
                run([ffmpeg(),'-v','error','-y','-i',wav,'-c:a',codec,path])
                for _ in range(2):tag_audio(path,book,'Prólogo',1,lrc,cues,cover)
                if ext=='mp3':
                    tags=ID3(path);self.assertEqual(tags.version,(2,3,0))
                    self.assertEqual(len(tags.getall('APIC')),1);picture=tags.getall('APIC')[0].data
                    self.assertEqual(tags.getall('USLT')[0].text,cues[0]['text'])
                    self.assertEqual(tags.getall('SYLT')[0].text,[(cues[0]['text'],0)])
                    self.assertEqual(str(tags['TIT2']),'Prólogo')
                elif ext=='m4a':
                    tags=MP4(path);picture=bytes(tags['covr'][0]);self.assertEqual(tags['\xa9lyr'],[lrc])
                else:
                    tags=OggOpus(path);picture=Picture(base64.b64decode(tags['metadata_block_picture'][0])).data
                    self.assertEqual(tags['lyrics'],[lrc])
                self.assertEqual(picture,cover)
                Image.open(io.BytesIO(picture)).verify()
