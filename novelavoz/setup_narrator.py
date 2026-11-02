"""Install compatible packages into the application's data directory only."""
import re,shutil,sys,time,urllib.request,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from novelavoz.narrator import RUNTIME,MODELS,VOICES
from novelavoz.books import DATA,atomic_json

def extract(archive,directory):
    directory.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        if any(not (directory/name).resolve().is_relative_to(directory.resolve()) for name in z.namelist()):raise ValueError('Archivo con rutas inseguras.')
        z.extractall(directory)
def download(url,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    partial=path.with_suffix(path.suffix+'.part')
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'NovelistTTS-local-voices'}),timeout=60) as response,partial.open('wb') as file:
            shutil.copyfileobj(response,file)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
def setup():
    if sys.platform!='win32':raise RuntimeError('Las voces locales requieren Windows de 64 bits.')
    import struct
    if struct.calcsize('P')!=8:raise RuntimeError('Se necesita Python de 64 bits.')
    downloads=DATA/'narrator-downloads';downloads.mkdir(parents=True,exist_ok=True)
    print('Preparando runtime local…',flush=True)
    archive=downloads/'adapter-v0.2.9.zip'
    if not archive.exists():download('https://github.com/gexgd0419/NaturalVoiceSAPIAdapter/releases/download/v0.2.9/NaturalVoiceSAPIAdapter_v0.2.9_x86_x64.zip',archive)
    extracted=downloads/'adapter';extract(archive,extracted)
    (RUNTIME/'x64').mkdir(parents=True,exist_ok=True)
    for file in (extracted/'x64').glob('*.dll'):shutil.copyfile(file,RUNTIME/'x64'/file.name)
    source=urllib.request.urlopen('https://raw.githubusercontent.com/gexgd0419/NaturalVoiceSAPIAdapter/v0.2.9/NaturalVoiceSAPIAdapter/SpeechServiceConstants.h',timeout=30).read().decode('utf-8-sig')
    match=re.search(r'MS_TTS_KEY\s*=\s*L"([^"]+)"',source)
    if not match:raise RuntimeError('La configuración local del adaptador cambió.')
    atomic_json(RUNTIME/'config.json',{'model_configuration':match.group(1),'adapter_version':'0.2.9','sdk_version':'1.41.1','configuration_source':'gexgd0419/NaturalVoiceSAPIAdapter/v0.2.9'})
    for id,(name,display,locale,version) in VOICES.items():
        print(f'Preparando {display} {version}…',flush=True)
        archive=downloads/(name+'-'+version+'.msix')
        if not archive.exists():
            url=f'https://dl.nvdacn.com/NVDA-Addons/TTS/NaturalVoices/MicrosoftWindows.Voice.{locale}.{name}.1_{version}_x64__cw5n1h2txyewy.Msix?novelavoz='+str(int(time.time()))
            download(url,archive)
        extract(archive,MODELS/name)
    (RUNTIME/'NOTICE.txt').write_text('Runtime obtenido de NaturalVoiceSAPIAdapter v0.2.9 (MIT), con componentes Microsoft Speech SDK 1.41.1. Modelos compatibles de Narrador obtenidos de los enlaces documentados por ese proyecto. No se registra software ni se modifican paquetes instalados de Windows.\nFuentes: https://github.com/gexgd0419/NaturalVoiceSAPIAdapter\nhttps://github.com/gexgd0419/NaturalVoiceSAPIAdapter/wiki/Narrator-natural-voice-download-links\n',encoding='utf-8')
    print('Voces preparadas. Reinicia Novelist TTS y selecciona Microsoft Natural · Local.',flush=True)
if __name__=='__main__':
    try:setup()
    except Exception as exc:raise SystemExit(str(exc))
