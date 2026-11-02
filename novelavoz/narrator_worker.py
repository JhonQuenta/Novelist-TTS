"""Read compatible local models through the native Speech SDK; no cloud endpoint."""
import ctypes as C, json, os, sys, wave
from pathlib import Path
_runtime_cache={}

def load_runtime(runtime):
    if runtime not in _runtime_cache:
        cookie=os.add_dll_directory(runtime)
        core=C.WinDLL(str(Path(runtime)/'Microsoft.CognitiveServices.Speech.core.dll'))
        _runtime_cache[runtime]=(cookie,core)
    return _runtime_cache[runtime][1]

def synthesize(request):
    core=load_runtime(request['runtime'])
    H=C.c_void_p; P=C.POINTER(H); U=C.c_uint32; I=C.c_int32; S=C.c_char_p
    def fn(name,args,ret=I):
        method=getattr(core,name);method.argtypes=args;method.restype=ret;return method
    def check(code,stage):
        if code:raise RuntimeError(f'Voz local: {stage} (0x{code&0xffffffff:08x}).')
    create=fn('embedded_speech_config_create',[P]);add=fn('embedded_speech_config_add_path',[H,S])
    set_voice=fn('embedded_speech_config_set_speech_synthesis_voice',[H,S,S]);format=fn('speech_config_set_audio_output_format',[H,I])
    audio_create=fn('audio_config_create_audio_output_from_wav_file_name',[P,S]);synth_create=fn('synthesizer_create_speech_synthesizer_from_config',[P,H,H])
    get_voices=fn('synthesizer_get_voices_list',[H,S,P]);count_voices=fn('synthesis_voices_result_get_voice_num',[H,C.POINTER(U)])
    voice_info=fn('synthesis_voices_result_get_voice_info',[H,U,P]);voice_name=fn('voice_info_get_name',[H],S)
    speak=fn('synthesizer_speak_text',[H,S,U,P]);get_reason=fn('synth_result_get_reason',[H,C.POINTER(I)])
    synth_release=fn('synthesizer_handle_release',[H]);audio_release=fn('audio_config_release',[H]);config_release=fn('speech_config_release',[H])
    result_release=fn('synthesizer_result_handle_release',[H]);info_release=fn('voice_info_handle_release',[H])
    config=H();audio=H();synth=H();voices=H();info=H();result=H()
    try:
        check(create(C.byref(config)),'configuración');check(add(config,request['model'].encode()),'paquete local')
        check(format(config,13),'formato WAV')
        check(audio_create(C.byref(audio),request['output'].encode()),'archivo de salida')
        check(synth_create(C.byref(synth),config,audio),'inicialización')
        check(get_voices(synth,b'',C.byref(voices)),'lectura de voces');count=U();check(count_voices(voices,C.byref(count)),'catálogo local')
        if not count.value:raise RuntimeError('El paquete local no contiene una voz compatible.')
        check(voice_info(voices,0,C.byref(info)),'información de voz');name=voice_name(info)
        check(synth_release(synth),'liberar consulta');synth=H()
        configuration=json.loads(Path(request['configuration']).read_text(encoding='utf-8'))
        check(set_voice(config,name,('Key:'+configuration['model_configuration']).encode()),'selección de voz')
        check(synth_create(C.byref(synth),config,audio),'inicialización de narración')
        text=request['text'].encode('utf-8');check(speak(synth,text,len(text),C.byref(result)),'síntesis')
        reason=I();check(get_reason(result,C.byref(reason)),'resultado')
        if reason.value!=9:
            raise RuntimeError('La síntesis local fue rechazada. Comprueba que se usa el paquete compatible preparado para Novelist TTS, no el paquete reciente de Windows.')
    finally:
        for handle,release in ((result,result_release),(info,info_release),(voices,result_release),(synth,synth_release),(audio,audio_release),(config,config_release)):
            if handle.value:
                try:release(handle)
                except Exception:pass
    with wave.open(request['output'],'rb') as audio:
        if not audio.getnframes():raise RuntimeError('La voz local no produjo audio.')

if __name__=='__main__':
    if sys.argv[1:] == ['--serve']:
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8')
        for line in sys.stdin:
            try:
                synthesize(json.loads(line))
                response={'ok':True}
            except Exception as exc:
                response={'ok':False,'error':str(exc).strip() or 'La voz local rechazó el fragmento sin dar detalles.'}
            print(json.dumps(response,ensure_ascii=False),flush=True)
    else:
        try:synthesize(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
        except Exception as exc:raise SystemExit(str(exc))
