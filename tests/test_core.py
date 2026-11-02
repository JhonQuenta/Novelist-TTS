import io, json, shutil, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from novelavoz import books
from novelavoz.books import import_epub, split_text, make_batches, image_file, confined, effective_background

def sample_epub():
    photo=io.BytesIO(); Image.new('RGB',(80,120),'#b58150').save(photo,'PNG')
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        z.writestr('mimetype','application/epub+zip')
        z.writestr('META-INF/container.xml','''<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>''')
        z.writestr('OEBPS/content.opf','''<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>La biblioteca de la lluvia</dc:title><dc:creator>Novelist TTS · Prueba</dc:creator><dc:language>es</dc:language></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="text" href="text.xhtml" media-type="application/xhtml+xml"/><item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/><item id="illustration" href="illustration.png" media-type="image/png"/></manifest><spine><itemref idref="text"/></spine></package>''')
        z.writestr('OEBPS/nav.xhtml','''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="text.xhtml#one">Capítulo 1 · La lluvia</a></li><li><a href="text.xhtml#two">Capítulo 2 · El libro</a></li></ol></nav><nav epub:type="landmarks"><a href="text.xhtml">Inicio</a></nav></body></html>''')
        z.writestr('OEBPS/text.xhtml','''<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Libro</title></head><body><h1 id="one">La lluvia</h1><p>La lluvia caía sobre la ciudad. Una nueva aventura estaba por comenzar.</p><img src="illustration.png"/><p>Ella sonrió al ver la luz de la biblioteca.</p><h1 id="two">El libro</h1><p>En la última página encontró una promesa. Mañana volvería para descubrir su significado.</p><img src="illustration.png"/><p>El silencio llenó la habitación.</p></body></html>''')
        z.writestr('OEBPS/cover.png',photo.getvalue()); z.writestr('OEBPS/illustration.png',photo.getvalue())
    stable=io.BytesIO()
    with zipfile.ZipFile(stream) as source, zipfile.ZipFile(stable,'w') as target:
        for name in source.namelist():
            content=source.read(name)
            if name.endswith('content.opf'):
                content=content.replace(b'<manifest>',b'<manifest><item id="coverpage" href="cover.xhtml" media-type="application/xhtml+xml"/>').replace(b'<spine>',b'<spine><itemref idref="coverpage"/>')
            target.writestr(zipfile.ZipInfo(name,date_time=(2026,10,13,12,0,0)),content)
        target.writestr(zipfile.ZipInfo('OEBPS/cover.xhtml',date_time=(2026,10,13,12,0,0)),'''<html xmlns="http://www.w3.org/1999/xhtml"><body><img src="cover.png"/></body></html>''')
    return stable.getvalue()

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.patcher=patch.object(books,'BOOKS',self.root); self.patcher.start()
    def tearDown(self): self.patcher.stop(); self.temp.cleanup()
    def test_anchor_chapters_and_images(self):
        book=import_epub(sample_epub(),'muestra.epub')
        self.assertEqual(len(book['chapters']),2)
        self.assertIn('promesa',book['chapters'][1]['text'])
        self.assertNotIn('promesa',book['chapters'][0]['text'])
        self.assertEqual([o['chapter_id'] for o in book['occurrences']],[1,2])
        self.assertGreater(book['occurrences'][0]['offset'],0)
        self.assertEqual(book['cover'],'cover')
        self.assertEqual(import_epub(sample_epub(),'otra.epub')['id'],book['id'])
    def test_rotation_does_not_change_source(self):
        book=import_epub(sample_epub(),'muestra.epub'); image=book['images'][0]
        source=image_file(book,image['id']); before=source.read_bytes()
        image['rotation']=90
        with Image.open(image_file(book,image['id'])) as result: self.assertEqual(result.size,(120,80))
        self.assertEqual(before,source.read_bytes())
    def test_batches_keep_spine_order_and_short_final_batch(self):
        chapters=[{'id':i,'text':'contenido'} for i in range(1,24)]
        result=make_batches(chapters,set(range(1,24)),10)
        self.assertEqual([len(x) for x in result],[10,10,3])
        result=make_batches(chapters,{20,3,7},2)
        self.assertEqual([[c['id'] for c in b] for b in result],[[3,7],[20]])
        self.assertEqual(len(make_batches(chapters,{3,7},0)),1)
    def test_chunks_preserve_text(self):
        text='«Hola», dijo él. ¿Qué ocurrirá mañana?\nUna frase sin punto final y con números 3.14 y nombres del Dr. Pérez.'
        parts=split_text(text,30)
        normalized=lambda t:' '.join(t.split())
        self.assertEqual(normalized(' '.join(p['text'] for p in parts)),normalized(text))
        for p in parts: self.assertEqual(text[p['offset']:p['end_offset']],p['text'])
    def test_zip_traversal_rejected(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z: z.writestr('../escape.txt','bad')
        with self.assertRaises(ValueError): import_epub(data.getvalue(),'bad.epub')
    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError): confined(self.root,'../escape')
    def test_svg_portada_beats_first_logo_and_migrates_existing_project(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(sample_epub())) as source, zipfile.ZipFile(raw,'w') as target:
            for name in source.namelist():
                content=source.read(name)
                if name.endswith('content.opf'):
                    content=content.replace(b' properties="cover-image"',b'').replace(b'<manifest>',b'<manifest><item id="logo" href="logo.png" media-type="image/png"/>')
                if name.endswith('cover.xhtml'):
                    content=b'<html xmlns="http://www.w3.org/1999/xhtml"><body><svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><image xlink:href="cover.png"/></svg></body></html>'
                target.writestr(name,content)
            target.writestr('OEBPS/logo.png',source.read('OEBPS/cover.png'))
        book=import_epub(raw.getvalue(),'svg.epub')
        self.assertEqual(book['cover'],'cover')
        book.pop('cover_detection_version'); book['cover']='logo'; book['background']='logo'; books.save_book(book)
        migrated=books.load_book(book['id'])
        self.assertEqual(migrated['cover'],'cover'); self.assertIsNone(migrated['background'])
        self.assertEqual(effective_background(migrated),'cover')
        migrated['background']='logo'; migrated['cover']='logo'; migrated['cover_user_set']=True; migrated['background_user_set']=True; migrated['cover_detection_version']=0
        books.save_book(migrated)
        self.assertEqual(books.load_book(book['id'])['cover'],'logo')
        self.assertEqual(books.load_book(book['id'])['background'],'logo')

class JobDeletionTests(unittest.TestCase):
    def setUp(self):
        from novelavoz import exporter
        self.exporter=exporter
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.patches=[patch.object(exporter,'JOBS',self.root/'jobs'),patch.object(exporter,'EXPORTS',self.root/'exports'),patch.object(exporter,'STATES',{}),patch.object(exporter,'CANCEL',set()),patch.object(exporter,'DELETE_REQUESTED',set())]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def create(self,id,status='done'):
        e=self.exporter;e.JOBS.mkdir(exist_ok=True);directory=e.EXPORTS/id;directory.mkdir(parents=True,exist_ok=True);(directory/'audio.mp3').write_bytes(b'test')
        data={'id':id,'status':status,'created':1};e.STATES[id]=data;books.atomic_json(e.JOBS/(id+'.json'),data)
    def test_selected_and_all_delete_only_job_data(self):
        self.create('a'*16);self.create('b'*16)
        preserved=self.root/'books';preserved.mkdir();(preserved/'book.json').write_text('keep')
        self.exporter.delete_jobs(['a'*16]);self.assertNotIn('a'*16,self.exporter.STATES);self.assertIn('b'*16,self.exporter.STATES)
        self.assertFalse((self.exporter.EXPORTS/('a'*16)).exists())
        self.exporter.delete_jobs();self.assertFalse(self.exporter.STATES);self.assertTrue((preserved/'book.json').exists())
    def test_active_job_cancelled_before_deletion(self):
        self.create('c'*16,'running');e=self.exporter;e.delete_jobs(['c'*16])
        self.assertIn('c'*16,e.CANCEL);self.assertIn('c'*16,e.DELETE_REQUESTED);self.assertTrue((e.EXPORTS/('c'*16)).exists())
    def test_invalid_id_cannot_delete_outside_exports(self):
        with self.assertRaises(ValueError):self.exporter.delete_jobs(['../books'])

if __name__=='__main__': unittest.main()
