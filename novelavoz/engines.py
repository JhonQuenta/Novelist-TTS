from __future__ import annotations
import asyncio, hashlib, json, os, re, subprocess, sys, time, wave
from pathlib import Path
from .books import ROOT, DATA, atomic_json

MODELS = DATA / 'voices'
PIPER_VOICES = ['es_ES-sharvard-medium','es_ES-davefx-medium','es_MX-ald-medium','es_AR-daniela-high']
GOOGLE_VOICES = {'google-es-MX':('es-MX','México','com.mx'),'google-es-ES':('es-ES','España','es'),'google-es-US':('es-US','Estados Unidos','us')}
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
MICROSOFT_ENGINES = ('edge','narrator','sapi','onecore')
SUPERTONIC_BASE_SPEED = 1.20
GOOGLE_BASE_SPEED = 1.20
# FFmpeg's m parameter is inverse: .875 limits attenuation to 6 dB.
DEESS_FILTERS = {
    'off': '',
    'soft': 'deesser=i=0.30:m=0.9375:f=0.55',
    'medium': 'deesser=i=0.40:m=0.875:f=0.55',
    'strong': 'deesser=i=0.50:m=0.8125:f=0.55',
}

def sibilance_filter(settings):
    return DEESS_FILTERS[settings['deess']] if settings['engine'] in MICROSOFT_ENGINES else ''

def narration_text(text, settings):
    # Change synthesis input only: EPUB text, captions and offsets remain original.
    if settings['engine'] in MICROSOFT_ENGINES and settings.get('neutral_questions',False):
        return re.sub(r'[!?]+','.',re.sub(r'[¿¡]','',text))
    return text

class Cancelled(Exception): pass

def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def run(args, cancel=None, timeout=600, cwd=None):
    with subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW, cwd=cwd) as process:
        deadline = time.monotonic()+timeout
        while True:
            try:
                stdout, stderr = process.communicate(timeout=.25)
                break
            except subprocess.TimeoutExpired:
                if (cancel and cancel()) or time.monotonic()>deadline:
                    process.kill()
                    process.communicate()
                    if cancel and cancel(): raise Cancelled('Cancelado. Los fragmentos terminados se conservan.')
                    raise RuntimeError('La operación excedió el tiempo permitido.')
        if process.returncode:
            detail=stderr.decode('utf-8','replace').strip()[-2000:] or stdout.decode('utf-8','replace').strip()[-1000:]
            if not detail:
                name=Path(str(args[1] if len(args)>1 and str(args[1]).endswith('.py') else args[0])).name
                detail=f'El proceso {name} terminó con código {process.returncode} sin un mensaje de error.'
            raise RuntimeError(detail)
        return stdout.decode('utf-8-sig','replace').strip()

def voices(refresh=False):
    result, warnings = [], []
    async def online():
        import edge_tts
        return await asyncio.wait_for(edge_tts.list_voices(), timeout=25)
    try:
        if refresh:
            catalog = asyncio.run(online())
            items = [{'id':v['ShortName'],'name':v['FriendlyName'],'lang':v['Locale'],'engine':'edge','installed':True} for v in catalog if v['Locale'].startswith('es-')]
            atomic_json(DATA/'edge-voices.json', items)
        else:
            cached = DATA/'edge-voices.json'
            items = json.loads(cached.read_text(encoding='utf-8')) if cached.exists() else [{'id':v,'name':v,'lang':v[:5],'engine':'edge','installed':True} for v in ['es-MX-DaliaNeural','es-MX-JorgeNeural','es-ES-ElviraNeural','es-ES-AlvaroNeural','es-PE-CamilaNeural','es-PE-AlexNeural']]
        result.extend(items)
    except Exception:
        warnings.append('Edge no pudo consultar su catálogo. Requiere internet; su integración es no oficial.')
        cached = DATA/'edge-voices.json'
        if cached.exists(): result.extend(json.loads(cached.read_text(encoding='utf-8')))
        else:
            result.extend({'id':v,'name':v,'lang':v[:5],'engine':'edge','installed':True} for v in ['es-MX-DaliaNeural','es-MX-JorgeNeural','es-ES-ElviraNeural','es-ES-AlvaroNeural','es-PE-CamilaNeural','es-PE-AlexNeural'])
    for voice_id,(locale,name,domain) in GOOGLE_VOICES.items():
        result.append({'id':voice_id,'name':'Google Traductor · Español ('+name+')','lang':locale,'engine':'gtts','installed':True})
    from .narrator import catalog
    result.extend(catalog())
    from .supertonic_engine import catalog as supertonic_catalog
    local_supertonic=supertonic_catalog()
    result.extend(local_supertonic)
    if local_supertonic and local_supertonic[0].get('compute_warning'):warnings.append(local_supertonic[0]['compute_warning'])
    return {'voices':result,'warnings':warnings,'natural_windows':'Las voces naturales locales usan paquetes compatibles guardados en la aplicación; no reemplazan las voces de Narrador instaladas.'}

def download_voice(voice_id, cancel=None):
    if voice_id not in PIPER_VOICES: raise ValueError('Modelo no permitido.')
    MODELS.mkdir(parents=True, exist_ok=True)
    run([sys.executable,'-m','piper.download_voices','--download-dir',MODELS,voice_id],cancel,1200)
    try:
        from urllib.request import urlopen
        locale, name, quality = voice_id.split('-')
        url=f'https://huggingface.co/rhasspy/piper-voices/resolve/main/{locale[:2]}/{locale}/{name}/{quality}/MODEL_CARD'
        with urlopen(url,timeout=20) as response:
            (MODELS/(voice_id+'.MODEL_CARD')).write_bytes(response.read())
    except Exception:
        pass  # A missing optional card does not invalidate the downloaded audio model.

def validate_settings(settings):
    s = dict(settings)
    if s.get('engine') not in ('edge','sapi','onecore','piper','gtts','narrator','supertonic'): raise ValueError('Selecciona un motor de voz que permita exportar archivos de audio.')
    if s.get('engine')=='supertonic':
        from .supertonic_engine import VOICES
        if s.get('voice') not in VOICES:raise ValueError('Selecciona una voz válida de Supertonic 3.')
    if not isinstance(s.get('voice'),str) or not s['voice']: raise ValueError('Selecciona una voz.')
    if s['engine']=='gtts' and s['voice'] not in GOOGLE_VOICES: raise ValueError('Selecciona una voz válida de Google Traductor.')
    for name, default, minimum, maximum in [('rate',0,-50,100),('pitch',0,-10,10),('volume',100,0,100),('pause',.15,0,5)]:
        s[name] = float(s.get(name,default))
        if not minimum <= s[name] <= maximum: raise ValueError(f'Ajuste fuera de rango: {name}')
    s.setdefault('deess','medium' if s['engine'] in MICROSOFT_ENGINES else 'off')
    if not isinstance(s['deess'],str) or s['deess'] not in DEESS_FILTERS:
        raise ValueError('Selecciona un nivel válido para suavizar las eses.')
    if s['engine'] not in MICROSOFT_ENGINES:s['deess']='off'
    s.setdefault('neutral_questions',False)
    if not isinstance(s['neutral_questions'],bool):
        raise ValueError('El ajuste de preguntas debe estar activado o desactivado.')
    if s['engine'] not in MICROSOFT_ENGINES:s['neutral_questions']=False
    s.setdefault('natural_pauses',True)
    if not isinstance(s['natural_pauses'],bool):raise ValueError('El ajuste de pausas naturales debe estar activado o desactivado.')
    s.setdefault('supertonic_steps',10)
    if type(s['supertonic_steps']) is not int or s['supertonic_steps'] not in (5,10,16):
        raise ValueError('Selecciona una calidad válida de Supertonic.')
    # Ignore the retired comma-splitting option, including saved jobs.
    s.pop('supertonic_commas',None)
    s.setdefault('supertonic_variation',0)
    if type(s['supertonic_variation']) is not int or not 0<=s['supertonic_variation']<=999999:
        raise ValueError('La variación de Supertonic debe ser un entero entre 0 y 999999.')
    # The base is fixed; ignore the retired adjustable setting in saved projects/jobs.
    s.pop('supertonic_base_rate',None)
    if s['engine']=='supertonic':s['supertonic_revision']=5
    return s

def synthesize(text, settings, output, cancel=None, source_cache=None):
    settings = validate_settings(settings)
    text = narration_text(text, settings)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # A silent reply such as “…” has no speech to synthesize. Some native
    # Microsoft packages abort on this input. Keep its cue as a short pause.
    if text.strip() and not any(char.isalnum() for char in text):
        frames=round(24000*(.35+settings['pause']))
        with wave.open(str(output),'wb') as audio:
            audio.setparams((1,2,24000,0,'NONE','not compressed'))
            audio.writeframes(b'\0\0'*frames)
        return frames/24000
    temporary = output.with_suffix('.source.wav')
    keep_source = False
    engine, voice = settings['engine'], settings['voice']
    if cancel and cancel(): raise Cancelled()
    if engine == 'edge':
        temporary = output.with_suffix('.source.mp3')
        # Pitch is applied below in semitones, consistently across engines.
        async def speak():
            import edge_tts
            tts = edge_tts.Communicate(text,voice,rate=f"{int(settings['rate']):+d}%",volume=f"{int(settings['volume'])-100:+d}%")
            task = asyncio.create_task(tts.save(str(temporary)))
            deadline = time.monotonic()+120
            try:
                while not task.done():
                    if cancel and cancel(): raise Cancelled()
                    if time.monotonic()>deadline: raise RuntimeError('Edge no respondió en 120 segundos.')
                    await asyncio.sleep(.2)
                await task
            finally:
                if not task.done():
                    task.cancel()
                    try: await task
                    except asyncio.CancelledError: pass
        asyncio.run(speak())
    elif engine == 'gtts':
        temporary=output.with_suffix('.source.mp3')
        request=output.with_suffix('.request.json')
        atomic_json(request,{'text':text,'tld':GOOGLE_VOICES[voice][2],'output':str(temporary.resolve())})
        try: run([sys.executable,ROOT/'novelavoz/google_worker.py',request],cancel,150)
        finally: request.unlink(missing_ok=True)
    elif engine == 'narrator':
        from .narrator import request as narrator_request
        from .narrator_session import SESSION
        SESSION.synthesize(narrator_request(voice,text,temporary),cancel,120)
    elif engine == 'supertonic':
        from .supertonic_engine import synthesize as supertonic_synthesize, REVISION
        # Generate at normal pace: high native speed can weaken articulation.
        if source_cache is not None:
            source_cache=Path(source_cache);source_cache.mkdir(parents=True,exist_ok=True)
            key=hashlib.sha256(json.dumps({'text':text,'voice':voice,'steps':settings['supertonic_steps'],'variation':settings['supertonic_variation'],'model':REVISION,'version':1},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            temporary=source_cache/(key+'.wav')
            keep_source=True
        valid=False
        if keep_source and temporary.exists():
            try:
                with wave.open(str(temporary),'rb') as cached:
                    valid=cached.getnframes()>0 and cached.getsampwidth()==2 and cached.getnchannels()==1 and temporary.stat().st_size>=44+cached.getnframes()*2
            except (OSError,EOFError,wave.Error):pass
        if not valid:
            staged=temporary.with_suffix('.partial.wav') if keep_source else temporary
            try:
                supertonic_synthesize(text,voice,1.0,staged,cancel,steps=settings['supertonic_steps'],variation=settings['supertonic_variation'])
                if keep_source:staged.replace(temporary)
            finally:
                if keep_source:staged.unlink(missing_ok=True)
    elif engine == 'sapi':
        request = output.with_suffix('.request.json')
        atomic_json(request,{'text':text,'voice':voice,'rate':round(settings['rate']/10),'volume':settings['volume'],'output':str(temporary.resolve())})
        try:
            run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',ROOT/'novelavoz/sapi.ps1','-InputFile',request],cancel,120)
        finally: request.unlink(missing_ok=True)
    elif engine == 'onecore':
        request=output.with_suffix('.request.json')
        atomic_json(request,{'text':text,'voice':voice,'speed':1+settings['rate']/100,'volume':settings['volume']/100,'output':str(temporary.resolve())})
        try: run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',ROOT/'novelavoz/onecore.ps1','-InputFile',request],cancel,120)
        finally: request.unlink(missing_ok=True)
    else:
        if voice not in PIPER_VOICES: raise ValueError('Voz Piper no válida.')
        model = MODELS/(voice+'.onnx')
        if not model.exists(): raise ValueError('Primero descarga la voz de Piper desde Voces y pruebas.')
        from piper import PiperVoice, SynthesisConfig
        global _piper_voice, _piper_model
        if _piper_model != str(model):
            _piper_voice = PiperVoice.load(str(model))
            _piper_model = str(model)
        config = SynthesisConfig(length_scale=1/(1+settings['rate']/100),volume=settings['volume']/100)
        with wave.open(str(temporary),'wb') as wav:
            _piper_voice.synthesize_wav(text,wav,config)
        if cancel and cancel():
            temporary.unlink(missing_ok=True)
            raise Cancelled()
    filters = []
    if engine == 'narrator':
        if settings['rate']: filters.append(f"atempo={1+settings['rate']/100:.8f}")
        if settings['volume']!=100: filters.append(f"volume={settings['volume']/100:.8f}")
    if engine in ('supertonic','gtts'):
        base_speed=SUPERTONIC_BASE_SPEED if engine=='supertonic' else GOOGLE_BASE_SPEED
        tempo=base_speed*(1+settings['rate']/100)
        # Chained factors <=2 avoid FFmpeg's sample-skipping fast tempo mode.
        while tempo>2:
            filters.append('atempo=2');tempo/=2
        if tempo!=1:filters.append(f"atempo={tempo:.8f}")
        if settings['volume']!=100:filters.append(f"volume={settings['volume']/100:.8f}")
    if settings['pitch']:
        filters.append(f"rubberband=pitch={2**(settings['pitch']/12):.8f}")
    if sibilance_filter(settings):
        filters.append(sibilance_filter(settings))
    filters.append(f"apad=pad_dur={settings['pause']}")
    try:
        run([ffmpeg(),'-hide_banner','-loglevel','error','-y','-i',temporary,'-af',','.join(filters),'-ar','24000','-ac','1','-c:a','pcm_s16le',output],cancel,120)
    finally:
        if not keep_source:temporary.unlink(missing_ok=True)
    return duration(output)

def duration(path):
    with wave.open(str(path),'rb') as wav:
        return wav.getnframes()/wav.getframerate()

_piper_voice = None
_piper_model = None
