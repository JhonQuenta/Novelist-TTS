from __future__ import annotations
import base64, hashlib, json, shutil, textwrap, threading, time, uuid, wave, zipfile
import re
from array import array
from PIL import Image, ImageFilter, ImageOps, ImageDraw
from .books import DATA, book_path, image_file, atomic_json, safe_filename, make_batches, split_text, effective_background
from .engines import synthesize, run, ffmpeg, Cancelled, validate_settings, GOOGLE_BASE_SPEED

JOBS = DATA/'jobs'
EXPORTS = DATA/'exports'
QUEUE_LOCK = threading.Lock()
CACHE_LOCK = threading.Lock()
STATE_LOCK = threading.RLock()
STATES = {}
CANCEL = set()
DELETE_REQUESTED = set()
AUDIO_BITRATES={'mp3':(64,96,128,192,256,320),'m4a':(48,64,96,128,192,256),'opus':(24,32,48,64,96,128)}

def cache_operation(clear=False):
    from . import audio_cache
    status_list()
    # Registration of new jobs shares this lock. Existing jobs keep running;
    # all cache belonging to their books is protected, including queued jobs.
    with CACHE_LOCK:
        with STATE_LOCK:
            protected={s['book_id'] for s in STATES.values() if s.get('book_id') and s['status'] in ('running','queued')}
        result=audio_cache.clear(protected) if clear else audio_cache.summary(audio_cache.inventory(protected))
        result['protected_books']=len(protected)
        return result

def audio_options(options,formats,book=None):
    raw=options.get('audio',{})
    if not isinstance(raw,dict):raise ValueError('Ajustes de audio inválidos.')
    result={}
    for key in ('embed_lyrics','embed_cover','sidecar_lyrics'):
        value=raw.get(key,True)
        if not isinstance(value,bool):raise ValueError('Ajuste de audio inválido: '+key)
        result[key]=value
    bitrate=raw.get('bitrate')
    if bitrate is not None and (type(bitrate) is not int or any(bitrate not in AUDIO_BITRATES[f] for f in formats if f in AUDIO_BITRATES)):
        raise ValueError('Calidad de audio no válida para el formato seleccionado.')
    result['bitrate']=bitrate
    image=raw.get('cover_image') or None
    if image is not None and not isinstance(image,str):raise ValueError('Portada de audio inválida.')
    if image and result['embed_cover'] and book is not None and not any(i['id']==image for i in book['images']):raise ValueError('La imagen elegida como portada no está disponible.')
    result['cover_image']=image
    return result

def natural_audio_bounds(audio,boundary,padding):
    """Adjust only quiet edges, leaving speech and pauses inside phrases intact."""
    rate=24000;frames=audio.getnframes();guard=round(.025*rate)
    audio.setpos(0);head=array('h',audio.readframes(min(frames,rate)))
    first=next((i for i,value in enumerate(head) if abs(value)>58),None)
    start=max(0,first-guard) if first is not None else 0
    offset=max(0,frames-rate*8);audio.setpos(offset)
    tail=array('h',audio.readframes(frames-offset))
    last=next((i for i in range(len(tail)-1,-1,-1) if abs(tail[i])>58),None)
    if last is None:return 0,frames,0  # Preserve intentionally silent replies.
    end=min(frames,offset+last+1+guard)
    quiet=(frames-end)/rate
    # Model silence is retained within a useful range instead of always
    # adding another fixed pause at every split. Account for cached padding.
    minimum,maximum={'sentence':(.08,.18),'paragraph':(.18,.32),'chapter':(.45,.65),'end':(.08,.18)}[boundary]
    target=max(minimum,min(maximum,quiet-max(0,padding)))
    return start,max(0,end-start),round(target*rate)

def narration_boundary(text,parts,index,last='end'):
    if index+1==len(parts):return last
    gap=text[parts[index]['end_offset']:parts[index+1]['offset']]
    return 'paragraph' if '\n' in gap else 'sentence'

def append_audio(writer, path, cancel, boundary=None, padding=0):
    """Append bounded PCM blocks so a long chapter never fills RAM."""
    with wave.open(str(path),'rb') as audio:
        if (audio.getnchannels(),audio.getsampwidth(),audio.getframerate())!=(1,2,24000):
            raise ValueError('El fragmento no tiene el formato de audio esperado.')
        frames=audio.getnframes();start=0;silence=0
        if boundary is not None:start,frames,silence=natural_audio_bounds(audio,boundary,padding)
        audio.setpos(start);remaining=frames
        while remaining:
            if cancel():raise Cancelled()
            block=audio.readframes(min(remaining,24000*5))
            if not block:raise ValueError('El fragmento de audio está incompleto.')
            writer.writeframesraw(block);remaining-=len(block)//2
        if silence:writer.writeframesraw(b'\0\0'*silence)
        return (frames+silence)/24000

def fragment_cache_key(text, settings):
    names=['engine','voice','rate','pitch','volume','pause']
    if settings['engine'] in ('edge','narrator','sapi','onecore'):names+=['deess','neutral_questions']
    if settings['engine']=='supertonic':names+=['supertonic_steps','supertonic_variation','supertonic_revision']
    relevant={name:settings[name] for name in names}
    if settings['engine']=='gtts':relevant['base_speed']=GOOGLE_BASE_SPEED
    return hashlib.sha256(json.dumps({'text':text,'settings':relevant,'version':4},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def encode_audio_formats(source, paths, cancel, bitrate=None, progress=None):
    """Read PCM once and encode only the requested audio formats."""
    if not paths:return
    codecs={'.mp3':['libmp3lame','96k'],'.m4a':['aac','96k'],'.opus':['libopus','48k']}
    args=[ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',source]
    for path in paths:
        codec,default_bitrate=codecs[path.suffix]
        args+=['-map','0:a:0','-c:a',codec,'-b:a',f'{bitrate}k' if bitrate is not None else default_bitrate]
        # MPEG-2 MP3 at 24 kHz cannot exceed 160 kbps. Mono AAC also has
        # a per-frame limit: raise the output sample rate for high targets.
        if bitrate is not None and path.suffix=='.mp3' and bitrate>160:args+=['-ar','44100']
        if bitrate is not None and path.suffix=='.m4a' and bitrate>128:args+=['-ar','48000']
        args+=['-threads','1',path]
    if progress:
        with wave.open(str(source),'rb') as audio:seconds=audio.getnframes()/audio.getframerate()
        run_media(args,cancel,3600,source.parent/'audio-progress.txt',seconds,progress)
    else:run(args,cancel,3600)

def run_media(args,cancel,timeout,progress_file,seconds,progress,cwd=None):
    """Read FFmpeg's media clock without interrupting cancellation checks."""
    progress_file=progress_file.resolve()
    progress_file.write_text('',encoding='utf-8')
    last=0.0
    started=time.monotonic()
    def check():
        nonlocal last
        if cancel and cancel():return True
        now=time.monotonic()
        if now-last>=1:
            last=now
            try:
                with progress_file.open('rb') as stream:
                    stream.seek(max(0,progress_file.stat().st_size-8192))
                    tail=stream.read().decode('utf-8','replace')
                values=re.findall(r'^out_time_us=(\d+)\r?$',tail,re.M)
                done=min(seconds,int(values[-1])/1e6) if values else 0
                fraction=done/seconds if seconds else 0
                eta=(now-started)*(1-fraction)/fraction if .01<fraction<1 else None
                progress(fraction,eta)
            except OSError:pass
        return False
    run([args[0],'-progress',progress_file,'-nostats',*args[1:]],check,timeout,cwd=cwd)
    if cancel and cancel():raise Cancelled()
    progress(1,0)

def package_files(output, files, cancel):
    """Compressed media gains little from DEFLATE; store it without recompression."""
    with zipfile.ZipFile(output/'NovelistTTS.zip','w') as archive:
        for item in files:
            if cancel():raise Cancelled()
            path=output/item['path']
            info=zipfile.ZipInfo.from_file(path,item['name'])
            info.compress_type=zipfile.ZIP_STORED if path.suffix in ('.mp3','.m4a','.opus','.mp4') else zipfile.ZIP_DEFLATED
            with path.open('rb') as source,archive.open(info,'w') as target:
                while True:
                    if cancel():raise Cancelled()
                    block=source.read(1024*1024)
                    if not block:break
                    target.write(block)

def purge_job(job_id):
    if not re.fullmatch(r'[a-f0-9]{16}',job_id): raise ValueError('Trabajo inválido.')
    root=EXPORTS.resolve()
    target=(root/job_id).resolve()
    if target.parent!=root: raise ValueError('Ruta de trabajo insegura.')
    if target.exists(): shutil.rmtree(target)
    (JOBS/(job_id+'.json')).unlink(missing_ok=True)
    STATES.pop(job_id,None)
    CANCEL.discard(job_id); DELETE_REQUESTED.discard(job_id)

def delete_jobs(job_ids=None):
    status_list()
    with STATE_LOCK:
        ids=list(STATES) if job_ids is None else list(dict.fromkeys(job_ids))
        if any(not re.fullmatch(r'[a-f0-9]{16}',j) for j in ids): raise ValueError('Trabajo inválido.')
        for job_id in ids:
            item=STATES.get(job_id)
            if not item: continue
            if item['status'] in ('running','queued'):
                CANCEL.add(job_id); DELETE_REQUESTED.add(job_id)
                update(job_id,delete_requested=True,message='Cancelando para eliminar el trabajo y sus archivos…')
            else: purge_job(job_id)
    return {'ok':True,'count':len(ids)}

def stamp(seconds, kind='lrc'):
    ms = round(max(0,seconds)*1000)
    if kind=='lrc': return f'{ms//60000:02d}:{ms//1000%60:02d}.{ms//10%100:02d}'
    if kind=='ass': return f'{ms//3600000}:{ms//60000%60:02d}:{ms//1000%60:02d}.{ms//10%100:02d}'
    return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'

def write_subtitles(folder, cues, title):
    lrc = '[ti:'+title.replace('\n',' ')+']\n'+'\n'.join(f"[{stamp(c['start'])}]{c['text']}" for c in cues)+'\n'
    (folder/'texto.lrc').write_text(lrc,encoding='utf-8')
    srt = '\n\n'.join(f"{i}\n{stamp(c['start'],'srt')} --> {stamp(c['end'],'srt')}\n"+'\n'.join(textwrap.wrap(c['text'],width=65,break_long_words=False)) for i,c in enumerate(cues,1))+'\n'
    (folder/'subtitulos.srt').write_text(srt,encoding='utf-8')
    return lrc

def cover_jpeg(book, image_id=None):
    image_id=image_id or book.get('cover')
    if not image_id: return None
    from io import BytesIO
    with Image.open(image_file(book,image_id)) as img:
        img = ImageOps.contain(img.convert('RGB'),(1200,1200))
        stream = BytesIO(); img.save(stream,'JPEG',quality=90)
        return stream.getvalue()

def tag_audio(path, book, title, track, lrc, cues, cover, embed_lyrics=True):
    if path.suffix=='.mp3':
        from mutagen.id3 import ID3, APIC, TIT2, TALB, TPE1, TRCK, USLT, SYLT
        tags = ID3(path)
        # Explicit v2.3/UTF-16 rather than Mutagen's default v2.4/UTF-8.
        tags.add(TIT2(encoding=1,text=title)); tags.add(TALB(encoding=1,text=book['title']))
        tags.add(TPE1(encoding=1,text=book['author'] or 'Narración')); tags.add(TRCK(encoding=1,text=str(track)))
        tags.delall('USLT');tags.delall('SYLT')
        if embed_lyrics:
            tags.add(USLT(encoding=1,lang='spa',desc='',text='\n'.join(c['text'] for c in cues)))
            tags.add(SYLT(encoding=1,lang='spa',format=2,type=1,desc='',text=[(c['text'],round(c['start']*1000)) for c in cues]))
        tags.delall('APIC')
        if cover: tags.add(APIC(encoding=0,mime='image/jpeg',type=3,desc='',data=cover))
        tags.update_to_v23()
        tags.save(path,v2_version=3)
    elif path.suffix=='.m4a':
        from mutagen.mp4 import MP4, MP4Cover
        tags = MP4(path); tags['\xa9nam']=[title]; tags['\xa9alb']=[book['title']]; tags['\xa9ART']=[book['author'] or 'Narración']; tags['trkn']=[(track,0)]
        tags.pop('\xa9lyr',None);tags.pop('covr',None)
        if embed_lyrics:tags['\xa9lyr']=[lrc]
        if cover: tags['covr']=[MP4Cover(cover,imageformat=MP4Cover.FORMAT_JPEG)]
        tags.save()
    else:
        from mutagen.oggopus import OggOpus
        from mutagen.flac import Picture
        tags = OggOpus(path); tags['TITLE']=title; tags['ALBUM']=book['title']; tags['ARTIST']=book['author'] or 'Narración'; tags['TRACKNUMBER']=str(track)
        tags.pop('LYRICS',None);tags.pop('METADATA_BLOCK_PICTURE',None)
        if embed_lyrics:tags['LYRICS']=lrc
        if cover:
            pic=Picture(); pic.type=3; pic.mime='image/jpeg'; pic.desc='Portada'; pic.data=cover
            from io import BytesIO
            with Image.open(BytesIO(cover)) as image:pic.width,pic.height=image.size
            pic.depth=24
            tags['METADATA_BLOCK_PICTURE']=base64.b64encode(pic.write()).decode('ascii')
        tags.save()

def background(book, image_id, destination):
    if image_id:
        with Image.open(image_file(book,image_id)) as source:
            source=source.convert('RGB')
            canvas=ImageOps.fit(source,(1280,720)).filter(ImageFilter.GaussianBlur(30))
            dark=Image.new('RGB',canvas.size,(18,19,30)); canvas=Image.blend(canvas,dark,.55)
            foreground=ImageOps.contain(source,(1280,720))
            canvas.paste(foreground,((1280-foreground.width)//2,(720-foreground.height)//2))
    else:
        canvas=Image.new('RGB',(1280,720),(23,26,41))
        ImageDraw.Draw(canvas).text((50,60),book['title'],fill='white',font_size=32)
    canvas.save(destination)

def ass_color(hex_value):
    if not isinstance(hex_value,str) or len(hex_value)!=7 or hex_value[0]!='#': raise ValueError('Color inválido.')
    int(hex_value[1:],16)
    return '&H00'+hex_value[5:7]+hex_value[3:5]+hex_value[1:3]

def render_video(folder, book, cues, events, seconds, style, output, cancel, progress=None):
    font=style.get('font','Arial')
    if font not in ('Arial','Calibri','Verdana','Georgia'): raise ValueError('Fuente inválida.')
    size=max(18,min(72,int(style.get('size',34))))
    outline=max(0,min(6,int(style.get('outline',2))))
    color=ass_color(style.get('color','#ffffff'))
    panel=3 if style.get('panel',True) else 1
    alignment={'bottom':2,'middle':5,'top':8}.get(style.get('position','bottom'),2)
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{color},&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,{panel},{outline},0,{alignment},60,60,35,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines=[]
    width=max(25,min(90,int(style.get('width',60))))
    for c in cues:
        # Escape ASS syntax; braces from a novel must never become formatting.
        text=c['text'].replace('\\','／').replace('{','（').replace('}','）')
        text='\\N'.join(textwrap.wrap(text,width=width,break_long_words=False))
        lines.append(f"Dialogue: 0,{stamp(c['start'],'ass')},{stamp(c['end'],'ass')},Default,,0,0,0,,{text}")
    (folder/'video.ass').write_text(header+'\n'.join(lines),encoding='utf-8-sig')
    background(book,effective_background(book),folder/'fondo.png')
    ids={e['image_id'] for e in events}
    filenames={}
    for i,image_id in enumerate(sorted(ids)):
        name=f'illustration-{i}.png'; filenames[image_id]=name
        background(book,image_id,folder/name)
    points=sorted({0.0,seconds,*[max(0,min(seconds,e['start'])) for e in events],*[max(0,min(seconds,e['end'])) for e in events]})
    scenes=[]
    for a,b in zip(points,points[1:]):
        if b-a<.001: continue
        active=[e for e in events if e['start']<=a<e['end']]
        image=filenames[max(active,key=lambda e:e['start'])['image_id']] if active else 'fondo.png'
        if scenes and scenes[-1][0]==image: scenes[-1]=(image,scenes[-1][1]+b-a)
        else: scenes.append((image,b-a))
    concat='\n'.join(f"file '{name}'\nduration {length:.6f}" for name,length in scenes)
    concat+=f"\nfile '{scenes[-1][0]}'\n"
    (folder/'visuales.txt').write_text(concat,encoding='utf-8')
    # Relative filter filename avoids Windows drive-colon escaping issues.
    run_in_folder=[ffmpeg(),'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i','visuales.txt','-i','narracion.wav','-vf','subtitles=video.ass','-r','24','-t',f'{seconds:.6f}','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-b:a','96k','-movflags','+faststart',str(output.resolve())]
    if progress:run_media(run_in_folder,cancel,86400,folder/'video-progress.txt',seconds,progress,cwd=folder)
    else:run(run_in_folder,cancel,86400,cwd=folder)

def status_list():
    JOBS.mkdir(parents=True,exist_ok=True)
    with STATE_LOCK:
        for file in JOBS.glob('*.json'):
            if file.stem not in STATES:
                try:
                    item=json.loads(file.read_text(encoding='utf-8'))
                    if item['status'] in ('queued','running'): item['status']='interrupted'; item['message']='Interrumpido al cerrar la aplicación. Puedes reanudar.'
                    STATES[file.stem]=item
                    if item.get('delete_requested'): purge_job(file.stem)
                except (ValueError,OSError): pass
        return sorted([dict(s) for s in STATES.values()],key=lambda s:s['created'],reverse=True)

def update(job_id, **kwargs):
    with STATE_LOCK:
        now=time.time()
        if kwargs.get('status')=='running':kwargs.setdefault('started',now)
        if kwargs.get('status') in ('done','error','cancelled'):
            kwargs.setdefault('finished',now)
            kwargs['eta_seconds']=None
        kwargs['updated']=now
        STATES[job_id].update(kwargs)
        atomic_json(JOBS/(job_id+'.json'),STATES[job_id])

def start_job(book, options, preview=False):
    settings=validate_settings(options.get('voice',{}))
    if not preview:
        selected=set(int(i) for i in options.get('chapters',[]))
        size=int(options.get('batch_size',1))
        if not 0<=size<=1000: raise ValueError('Tamaño de lote fuera de rango.')
        make_batches(book['chapters'],selected,size)
        formats=options.get('formats',['mp3'])
        if not formats or any(f not in ('mp3','m4a','opus','mp4') for f in formats): raise ValueError('Selecciona un formato válido.')
        audio_options(options,formats,book)
    job_id=uuid.uuid4().hex[:16]
    item={'id':job_id,'book_id':book['id'] if book else None,'title':'Prueba de voz' if preview else book['title'],'status':'queued','message':'En cola','progress':0,'created':time.time(),'files':[],'options':options,'preview':preview,'started':None,'finished':None,'eta_seconds':None,'stage':'queued'}
    with CACHE_LOCK,STATE_LOCK:
        STATES[job_id]=item
        atomic_json(JOBS/(job_id+'.json'),item)
    threading.Thread(target=execute,args=(job_id,book,options,preview),daemon=True).start()
    return dict(item)

def resume_job(job_id, book):
    status_list()
    item=STATES[job_id]
    if item['status'] in ('running','queued'): raise ValueError('El trabajo ya está activo.')
    return start_job(book,item['options'],item['preview'])

def execute(job_id, book, options, preview):
    cancel=lambda: job_id in CANCEL
    with QUEUE_LOCK:
        try:
            if cancel(): raise Cancelled()
            update(job_id,status='running',message='Preparando narración',stage='prepare')
            settings=validate_settings(options['voice'])
            output=EXPORTS/job_id; output.mkdir(parents=True,exist_ok=True)
            if preview:
                text=str(options.get('text','')).strip()[:3000]
                if not text: raise ValueError('Escribe un texto de prueba.')
                parts=split_text(text)
                if not parts: raise ValueError('El texto de prueba no contiene frases narrables.')
                preview_start=time.monotonic();preview_done=0;preview_total=sum(len(p['text']) for p in parts)
                with wave.open(str(output/'prueba.wav'),'wb') as merged:
                    merged.setparams((1,2,24000,0,'NONE','not compressed'))
                    for index,part in enumerate(parts,1):
                        temp=output/'fragmento.wav'
                        synthesize(part['text'],settings,temp,cancel)
                        boundary=narration_boundary(text,parts,index-1) if settings['natural_pauses'] and any(c.isalnum() for c in part['text']) else None
                        append_audio(merged,temp,cancel,boundary,settings['pause'])
                        temp.unlink(missing_ok=True)
                        preview_done+=len(part['text'])
                        eta=(time.monotonic()-preview_start)*(preview_total-preview_done)/preview_done
                        update(job_id,progress=round(index/len(parts)*95),stage='narration',eta_seconds=eta,eta_scope='Prueba de voz',message=f'Prueba · fragmento {index}/{len(parts)}')
                update(job_id,status='done',progress=100,message='Prueba lista',files=[{'name':'prueba.wav','path':'prueba.wav'}])
                return
            batches=make_batches(book['chapters'],set(int(i) for i in options['chapters']),int(options.get('batch_size',1)))
            chapter_parts={c['id']:split_text(c['text']) for batch in batches for c in batch}
            total=sum(len(parts) for parts in chapter_parts.values())
            completed=0; files=[]; manifest=[]
            # Estimate model work separately from reusable fragments: cached audio
            # must not make the remaining synthesis appear unrealistically fast.
            pending_chars=0; generated_chars=0; generation_seconds=0.0
            cache=book_path(book['id'])/'cache';cache.mkdir(exist_ok=True)
            for parts in chapter_parts.values():
                for part in parts:
                    cached=cache/(fragment_cache_key(part['text'],settings)+'.wav')
                    legacy_key=hashlib.sha256(json.dumps({'text':part['text'],'settings':settings,'version':3},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                    legacy=cache/(legacy_key+'.wav')
                    if not cached.exists() and not (settings['engine']!='gtts' and legacy.exists()):pending_chars+=len(part['text'])
            audio_settings=audio_options(options,options['formats'],book)
            cover=cover_jpeg(book,audio_settings['cover_image']) if audio_settings['embed_cover'] else None
            for batch_number,batch in enumerate(batches,1):
                if cancel(): raise Cancelled()
                title=batch[0]['title'] if len(batch)==1 else f"Capítulos {batch[0]['id']:03d}–{batch[-1]['id']:03d}"
                name=f'{batch_number:03d} - '+safe_filename(title,limit=90)
                folder=output/f'lote-{batch_number:03d}'; folder.mkdir(exist_ok=True)
                cues=[]; events=[]; cursor=0.0
                cache=book_path(book['id'])/'cache'; cache.mkdir(exist_ok=True)
                update(job_id,stage='narration',eta_seconds=None,eta_scope='Narración pendiente; después se exporta',message=f'Lote {batch_number}/{len(batches)} · Preparando narración')
                with wave.open(str(folder/'narracion.wav'),'wb') as merged:
                    merged.setparams((1,2,24000,0,'NONE','not compressed'))
                    for chapter_index,chapter in enumerate(batch):
                        chapter_start=cursor; chapter_cues=[]
                        parts=chapter_parts[chapter['id']]
                        for part_index,part in enumerate(parts):
                            if cancel(): raise Cancelled()
                            key=fragment_cache_key(part['text'],settings)
                            audio=cache/(key+'.wav')
                            if not audio.exists() and settings['engine']!='gtts':
                                # Existing processed fragments remain reusable after upgrading.
                                legacy_key=hashlib.sha256(json.dumps({'text':part['text'],'settings':settings,'version':3},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                                legacy=cache/(legacy_key+'.wav')
                                if legacy.exists():audio=legacy
                            if not audio.exists():
                                temp=cache/(key+'.partial.wav')
                                generation_start=time.monotonic()
                                synthesize(part['text'],settings,temp,cancel,source_cache=cache/'source'); temp.replace(audio)
                                generation_seconds+=time.monotonic()-generation_start
                                generated_chars+=len(part['text']);pending_chars=max(0,pending_chars-len(part['text']))
                            boundary=narration_boundary(chapter['text'],parts,part_index,'chapter' if chapter_index+1<len(batch) else 'end') if settings['natural_pauses'] and any(c.isalnum() for c in part['text']) else None
                            length=append_audio(merged,audio,cancel,boundary,settings['pause'])
                            cue={**part,'start':cursor,'end':cursor+length,'chapter':chapter['id']}
                            cues.append(cue); chapter_cues.append(cue); cursor+=length
                            completed+=1
                            eta=generation_seconds*pending_chars/generated_chars if generated_chars and pending_chars else None
                            base=(batch_number-1)/len(batches)*98
                            fraction=len(cues)/max(1,sum(len(chapter_parts[c['id']]) for c in batch))
                            update(job_id,progress=round(base+fraction*70/len(batches)),stage='narration',eta_seconds=eta,eta_scope='Narración pendiente; después se exporta',message=f'Lote {batch_number}/{len(batches)} · {chapter["title"]} · fragmento {completed}/{total}')
                        for occurrence in book['occurrences']:
                            if occurrence['chapter_id']!=chapter['id'] or occurrence['excluded']: continue
                            image=next((i for i in book['images'] if i['id']==occurrence['image_id']),None)
                            if not image or image['excluded'] or image['id']==book.get('cover'): continue
                            manual=occurrence.get('time')
                            boundary=next((c['end'] if occurrence['offset']>=c['end_offset'] else c['start'] for c in chapter_cues if c['end_offset']>=occurrence['offset']),cursor)
                            start=chapter_start+float(manual) if manual is not None else boundary
                            end=start+float(occurrence.get('duration',20))
                            if start<end: events.append({'image_id':image['id'],'start':max(chapter_start,start),'end':end})
                events=[{**e,'end':min(cursor,e['end'])} for e in events if e['start']<cursor]
                lrc=write_subtitles(folder,cues,title)
                formats=list(dict.fromkeys(options['formats']))
                audio_paths=[output/(name+'.'+fmt) for fmt in formats if fmt!='mp4']
                def media_progress(fraction,eta):
                    stage_start=70
                    span=12 if audio_paths and 'mp4' in formats else 28
                    if STATES[job_id].get('stage')=='video' and audio_paths:stage_start=82;span=16
                    update(job_id,progress=round(((batch_number-1)*98+stage_start+span*fraction)/len(batches)),eta_seconds=eta,eta_scope=f'Exportación del lote {batch_number}/{len(batches)}')
                if audio_paths:
                    update(job_id,stage='audio',eta_seconds=None,message=f'Codificando lote {batch_number}/{len(batches)} · '+', '.join(p.suffix[1:].upper() for p in audio_paths))
                    encode_audio_formats(folder/'narracion.wav',audio_paths,cancel,audio_settings['bitrate'],progress=media_progress)
                for fmt in formats:
                    if cancel(): raise Cancelled()
                    update(job_id,message=f'Exportando lote {batch_number}/{len(batches)} · {fmt.upper()}')
                    path=output/(name+'.'+fmt)
                    if fmt=='mp4':
                        update(job_id,stage='video',eta_seconds=None,eta_scope=f'Exportación del lote {batch_number}/{len(batches)}')
                        render_video(folder,book,cues,events,cursor,options.get('subtitles',{}),path,cancel,progress=media_progress)
                    else:
                        tag_audio(path,book,title,batch_number,lrc,cues,cover,audio_settings['embed_lyrics'])
                    files.append({'name':path.name,'path':path.name})
                sidecars=[('lrc','texto.lrc')] if audio_settings['sidecar_lyrics'] else []
                if 'mp4' in options['formats']:sidecars.append(('srt','subtitulos.srt'))
                for suffix,src in sidecars:
                    path=output/(name+'.'+suffix); shutil.copyfile(folder/src,path)
                    files.append({'name':path.name,'path':path.name})
                manifest.append({'title':title,'chapter_ids':[c['id'] for c in batch],'duration':cursor,'cues':cues,'images':events})
                update(job_id,files=files,progress=round(batch_number/len(batches)*98))
            atomic_json(output/'proyecto.json',{'book':book['title'],'voice':settings,'audio':audio_settings,'batches':manifest,'subtitle_precision':'Inicio exacto de cada fragmento; sin alineación por palabra.'})
            files.append({'name':'proyecto.json','path':'proyecto.json'})
            update(job_id,stage='package',eta_seconds=None,message='Preparando ZIP de descarga…')
            package_files(output,files,cancel)
            files.insert(0,{'name':'NovelistTTS.zip','path':'NovelistTTS.zip'})
            update(job_id,status='done',progress=100,message='Exportación terminada',files=files)
        except Cancelled:
            update(job_id,status='cancelled',message='Cancelado. Puedes reanudar reutilizando los fragmentos guardados.')
        except Exception as exc:
            update(job_id,status='error',message=str(exc))
        finally:
            with STATE_LOCK:
                if job_id in DELETE_REQUESTED: purge_job(job_id)
                else: CANCEL.discard(job_id)
