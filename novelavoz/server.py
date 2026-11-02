from __future__ import annotations
import copy, json, mimetypes, re, threading, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote
from .books import ROOT, DATA, confined, import_epub, load_book, save_book, library, image_file, make_batches, book_path, effective_background
from .engines import voices, download_voice
from . import exporter

BOOK_LOCK = threading.RLock()
MODEL_STATUS = {'status':'idle','message':''}

class Handler(BaseHTTPRequestHandler):
    server_version='NovelistTTS/0.5'
    def log_message(self, *args): pass
    def json(self,value,status=200):
        payload=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(payload))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(payload)
    def guard(self, mutation=False):
        host=self.headers.get('Host','')
        if host not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
            raise ValueError('Host no permitido.')
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
            raise ValueError('Origen no permitido.')
        if mutation and self.headers.get('X-Novelist-TTS')!='1' and self.headers.get('X-NovelaVoz')!='1': raise ValueError('Petición inválida.')
    def file(self,path,attachment=False):
        if not path.is_file(): raise FileNotFoundError('Archivo no encontrado.')
        size=path.stat().st_size; start,end=0,size-1; code=200
        range_header=self.headers.get('Range','')
        if range_header:
            match=re.fullmatch(r'bytes=(\d+)-(\d*)',range_header)
            if match:
                start=int(match[1]); end=min(end,int(match[2])) if match[2] else end
                if start>=size or end<start:
                    self.send_response(416); self.send_header('Content-Range',f'bytes */{size}'); self.end_headers(); return
                code=206
        self.send_response(code)
        content_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        if path.suffix=='.opus': content_type='audio/ogg'
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(end-start+1)); self.send_header('Accept-Ranges','bytes')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-cache')
        if code==206: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        if attachment:
            from urllib.parse import quote
            self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(path.name))
        self.end_headers()
        with path.open('rb') as stream:
            stream.seek(start); remaining=end-start+1
            while remaining:
                chunk=stream.read(min(1024*1024,remaining))
                if not chunk: break
                self.wfile.write(chunk); remaining-=len(chunk)
    def do_GET(self):
        try:
            self.guard()
            parsed=urlsplit(self.path); route=parsed.path; q={k:v[0] for k,v in parse_qs(parsed.query).items()}
            if route=='/api/library': return self.json(library())
            if route=='/api/book': return self.json(load_book(q['id']))
            if route=='/api/voices': return self.json(voices(refresh=q.get('refresh')=='1'))
            if route=='/api/jobs': return self.json(exporter.status_list())
            if route=='/api/cache': return self.json(exporter.cache_operation())
            if route=='/api/model-status': return self.json(MODEL_STATUS)
            if route=='/api/image': return self.file(image_file(load_book(q['book']),q['image']))
            if route=='/api/thumbnail':
                import hashlib
                book=load_book(q['book'])
                identity=json.dumps({'background':effective_background(book),'rotation':[i.get('rotation',0) for i in book['images']]},sort_keys=True)
                folder=book_path(book['id'])/'derived'; folder.mkdir(exist_ok=True)
                path=folder/('miniatura-'+hashlib.sha256(identity.encode()).hexdigest()[:12]+'.png')
                if not path.exists(): exporter.background(book,effective_background(book),path)
                return self.file(path,True)
            if route=='/api/download':
                if not re.fullmatch(r'[a-f0-9]{16}',q['job']): raise ValueError('Trabajo inválido.')
                path=confined(exporter.EXPORTS/q['job'],q['file'])
                return self.file(path,q.get('inline')!='1')
            path=confined(ROOT/'static',unquote(route).lstrip('/') or 'index.html')
            self.file(path)
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception as exc: self.json({'error':str(exc)},400)
    def do_POST(self):
        try:
            self.guard(True)
            parsed=urlsplit(self.path); route=parsed.path; q={k:v[0] for k,v in parse_qs(parsed.query).items()}
            length=int(self.headers.get('Content-Length',0))
            if not 0<length<=200*1024*1024: raise ValueError('Archivo vacío o mayor a 200 MB.')
            raw=self.rfile.read(length)
            if route=='/api/import':
                with BOOK_LOCK: return self.json(import_epub(raw,q.get('name','libro.epub')))
            if route=='/api/upload-image':
                from PIL import Image
                from io import BytesIO
                with BOOK_LOCK:
                    book=load_book(q['book']); image_id='custom-'+uuid.uuid4().hex[:8]
                    relative='custom/'+image_id+'.png'
                    destination=book_path(book['id'])/'book'/relative; destination.parent.mkdir(exist_ok=True)
                    with Image.open(BytesIO(raw)) as image:
                        image=ImageOps_contain(image.convert('RGB'),(4000,4000)); image.save(destination)
                    book['images'].append({'id':image_id,'path':relative,'media_type':'image/png','bytes':destination.stat().st_size,'rotation':0,'excluded':False})
                    if q.get('target')!='audio-cover':
                        book['background']=image_id; book['background_user_set']=True
                    save_book(book)
                    return self.json(book)
            body=json.loads(raw)
            if route=='/api/book/update':
                with BOOK_LOCK:
                    book=load_book(body['id'])
                    for key in ('cover','background'):
                        if key in body:
                            value=body[key]
                            if value is not None and not any(i['id']==value for i in book['images']): raise ValueError('Imagen inválida.')
                            book[key]=value
                            book[key+'_user_set']=True
                    if 'settings' in body: book['settings']=body['settings']
                    if 'all_durations' in body:
                        duration=float(body['all_durations'])
                        if not 1<=duration<=3600: raise ValueError('Duración inválida (1–3600 segundos).')
                        for occurrence in book['occurrences']: occurrence['duration']=duration
                    if 'image' in body:
                        item=next(i for i in book['images'] if i['id']==body['image']['id'])
                        change=body['image']
                        if 'rotation' in change: item['rotation']=int(change['rotation'])%360
                        if 'excluded' in change: item['excluded']=bool(change['excluded'])
                    if 'occurrence' in body:
                        item=next(i for i in book['occurrences'] if i['id']==body['occurrence']['id']); change=body['occurrence']
                        if 'excluded' in change: item['excluded']=bool(change['excluded'])
                        if 'duration' in change:
                            value=float(change['duration'])
                            if not 1<=value<=3600: raise ValueError('Duración inválida (1–3600 segundos).')
                            item['duration']=value
                        if 'time' in change:
                            value=change['time']
                            if value is not None and (not 0<=float(value)<=86400): raise ValueError('Tiempo inválido.')
                            item['time']=float(value) if value is not None else None
                    save_book(book); return self.json(book)
            if route=='/api/batches':
                book=load_book(body['book_id']); batches=make_batches(book['chapters'],set(body['chapters']),int(body['batch_size']))
                return self.json([{'ids':[c['id'] for c in batch],'title':batch[0]['title'] if len(batch)==1 else f"Capítulos {batch[0]['id']}–{batch[-1]['id']}",'characters':sum(len(c['text']) for c in batch)} for batch in batches])
            if route=='/api/generate': return self.json(exporter.start_job(copy.deepcopy(load_book(body['book_id'])),body))
            if route=='/api/preview': return self.json(exporter.start_job(None,body,True))
            if route=='/api/jobs/delete':
                return self.json(exporter.delete_jobs(None if body.get('all') else body.get('jobs',[])))
            if route=='/api/cache/clear': return self.json(exporter.cache_operation(clear=True))
            if route=='/api/cancel':
                exporter.CANCEL.add(body['job']); return self.json({'ok':True})
            if route=='/api/resume':
                exporter.status_list(); item=exporter.STATES[body['job']]
                book=load_book(item['book_id']) if item['book_id'] else None
                return self.json(exporter.resume_job(body['job'],copy.deepcopy(book)))
            if route=='/api/download-voice':
                if MODEL_STATUS['status']=='running': raise ValueError('Ya hay una descarga activa.')
                voice=body['voice']
                from .engines import PIPER_VOICES
                if voice not in PIPER_VOICES: raise ValueError('Voz no válida.')
                MODEL_STATUS.update(status='running',message='Descargando '+voice)
                def download():
                    try:
                        download_voice(voice); MODEL_STATUS.update(status='done',message='Voz descargada: '+voice)
                    except Exception as exc: MODEL_STATUS.update(status='error',message=str(exc))
                threading.Thread(target=download,daemon=True).start(); return self.json(MODEL_STATUS)
            if route=='/api/install-supertonic':
                if MODEL_STATUS['status']=='running':raise ValueError('Ya hay una descarga activa.')
                MODEL_STATUS.update(status='running',message='Preparando Supertonic 3: modelos locales y diez voces…')
                def prepare_supertonic():
                    try:
                        import sys
                        from .engines import run
                        run([sys.executable,ROOT/'novelavoz/setup_supertonic.py'],timeout=1800)
                        MODEL_STATUS.update(status='done',message='Supertonic 3 preparado. Las diez voces permiten crear archivos.')
                    except Exception as exc:MODEL_STATUS.update(status='error',message=str(exc))
                threading.Thread(target=prepare_supertonic,daemon=True).start();return self.json(MODEL_STATUS)
            if route=='/api/install-narrator':
                if MODEL_STATUS['status']=='running':raise ValueError('Ya hay una descarga activa.')
                MODEL_STATUS.update(status='running',message='Descargando y preparando las cuatro voces naturales locales…')
                def prepare_narrator():
                    try:
                        import sys
                        from .engines import run
                        run([sys.executable,ROOT/'novelavoz/setup_narrator.py'],timeout=1800)
                        MODEL_STATUS.update(status='done',message='Voces naturales locales preparadas. Puedes probar Jorge, Dalia, Álvaro y Elvira.')
                    except Exception as exc:MODEL_STATUS.update(status='error',message=str(exc))
                threading.Thread(target=prepare_narrator,daemon=True).start();return self.json(MODEL_STATUS)
            raise ValueError('Ruta no encontrada.')
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception as exc: self.json({'error':str(exc)},400)

def ImageOps_contain(image,size):
    from PIL import ImageOps
    return ImageOps.contain(image,size) if image.width>size[0] or image.height>size[1] else image

def serve(port=8765):
    DATA.mkdir(exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Novelist TTS: http://127.0.0.1:{port}',flush=True)
    server.serve_forever()
