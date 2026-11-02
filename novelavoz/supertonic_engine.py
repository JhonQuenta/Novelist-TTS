"""Supertonic 3: Spanish audio from archived local ONNX models."""
import atexit, hashlib, json, os, threading, wave
from pathlib import Path
from .books import DATA, split_text

FOLDER=DATA/'supertonic-3'
REVISION='aafc6e32416a594460b32413efc49d7fe4ce6d46'
VOICES={f'supertonic-{gender}{n}':f'{"Masculina" if gender=="M" else "Femenina"} {n}' for gender in ('M','F') for n in range(1,6)}
_model=None
_styles={}
_lock=threading.Lock()
_gpu_session=None
_gpu_error=None
_gpu_infer=None

def gpu_configuration():
    if _gpu_error:return None
    path=DATA/'supertonic-compute.json'
    if not (DATA/'supertonic-gpu-runtime/onnxruntime/__init__.py').is_file():return None
    try:
        item=json.loads(path.read_text(encoding='utf-8'))
        if item.get('provider')=='directml' and item.get('verified') is True and type(item.get('device_id')) is int and 0<=item['device_id']<16:return item
    except (OSError,ValueError):pass
    return None

def ready(voice):
    return voice in VOICES and all((FOLDER/'onnx'/name).is_file() for name in ('duration_predictor.onnx','text_encoder.onnx','vector_estimator.onnx','vocoder.onnx','tts.json','unicode_indexer.json')) and (FOLDER/'voice_styles'/(voice.split('-')[-1]+'.json')).is_file()

def catalog():
    gpu=gpu_configuration()
    compute='GPU · '+gpu.get('adapter_name','DirectML') if gpu else 'CPU'
    return [{'id':id,'name':'Supertonic 3 · '+name,'lang':'es','engine':'supertonic','installed':ready(id),'compute':compute,'compute_warning':_gpu_error} for id,name in VOICES.items()]

def narration_parts(text):
    """Preserve comma prosody inside continuous synthesis units."""
    return [sentence['text'] for sentence in split_text(text)]

def synthesize(text,voice,speed,output,cancel=None,steps=10,variation=0):
    global _gpu_session,_gpu_error
    gpu=gpu_configuration()
    if gpu:
        from .engines import Cancelled
        from .narrator_session import NarratorSession
        if _gpu_session is None:
            _gpu_session=NarratorSession(Path(__file__).with_name('supertonic_gpu_worker.py'),'Supertonic 3 en GPU')
            atexit.register(_gpu_session.close)
        try:
            _gpu_session.synthesize({'text':text,'voice':voice,'speed':speed,'output':str(Path(output).resolve()),'steps':steps,'variation':variation,'device_id':gpu['device_id']},cancel,180)
            return
        except Cancelled:raise
        except RuntimeError as exc:
            _gpu_error='Se usa CPU porque falló la aceleración GPU: '+str(exc)
    return _synthesize_local(text,voice,speed,output,cancel,steps,variation)

def _synthesize_local(text,voice,speed,output,cancel=None,steps=10,variation=0,device_id=None):
    global _model,_gpu_infer
    if not ready(voice):raise ValueError('Primero prepara Supertonic 3 desde Voces y pruebas.')
    import numpy as np, onnxruntime as ort
    from . import supertonic_helper as helper
    from .engines import Cancelled
    with _lock:
        if cancel and cancel():raise Cancelled()
        if _model is None:
            opts=ort.SessionOptions()
            opts.intra_op_num_threads=min(4,os.cpu_count() or 1)
            opts.inter_op_num_threads=1
            providers=['CPUExecutionProvider']
            if device_id is not None:
                if 'DmlExecutionProvider' not in ort.get_available_providers():raise RuntimeError('El componente instalado no permite usar DirectML.')
                opts.enable_mem_pattern=False
                opts.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
                opts.intra_op_num_threads=2
                providers=[('DmlExecutionProvider',{'device_id':device_id}),'CPUExecutionProvider']
            onnx=str(FOLDER/'onnx')
            _model=helper.TextToSpeech(helper.load_cfgs(onnx),helper.load_text_processor(onnx),*helper.load_onnx_all(onnx,opts,providers))
            if device_id is not None:
                from .supertonic_gpu_inference import GpuInference
                _gpu_infer=GpuInference(_model,ort,device_id)
        if voice not in _styles:_styles[voice]=helper.load_voice_style([str(FOLDER/'voice_styles'/(voice.split('-')[-1]+'.json'))])
        pieces=[]
        for part in narration_parts(text):
            if cancel and cancel():raise Cancelled()
            seed_key=voice+'\0'+part+('\0variation:'+str(variation) if variation else '')
            seed=int.from_bytes(hashlib.sha256(seed_key.encode('utf-8')).digest()[:8],'little')
            infer=_gpu_infer.batch if _gpu_infer is not None else _model.batch
            audio,durations=infer([part],['es'],_styles[voice],total_step=steps,speed=speed,rng=np.random.default_rng(seed))
            audio=audio[0,:int(_model.sample_rate*float(durations[0]))]
            if not len(audio) or not np.isfinite(audio).all():raise RuntimeError('Supertonic no produjo audio válido.')
            pieces.append(audio)
        if cancel and cancel():raise Cancelled()
        if not pieces:raise ValueError('Introduce texto para narrar.')
        audio=np.concatenate(pieces)
        with wave.open(str(output),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(_model.sample_rate)
            wav.writeframes((np.clip(audio,-1,1)*32767).astype('<i2').tobytes())
