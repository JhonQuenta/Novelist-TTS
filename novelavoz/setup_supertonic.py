"""Download a pinned archived Supertonic 3 model; no package installation."""
import hashlib,json,sys,urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from novelavoz.supertonic_engine import FOLDER,REVISION

BASE=f'https://huggingface.co/supertone-oss-archive/supertonic-3/resolve/{REVISION}/'

def prepare(item):
    path=(FOLDER/item['path']).resolve()
    if not path.is_relative_to(FOLDER.resolve()):raise ValueError('Ruta de modelo insegura.')
    path.parent.mkdir(parents=True,exist_ok=True)
    expected=item.get('sha256')
    if path.exists() and path.stat().st_size==item['size'] and (not expected or hashlib.sha256(path.read_bytes()).hexdigest()==expected):return
    print('Descargando '+item['path']+'…',flush=True)
    partial=path.with_suffix(path.suffix+'.part')
    try:
        digest=hashlib.sha256()
        with urllib.request.urlopen(urllib.request.Request(BASE+item['path'],headers={'User-Agent':'Novelist TTS'}),timeout=120) as response,partial.open('wb') as file:
            while block:=response.read(1024*1024):file.write(block);digest.update(block)
        if partial.stat().st_size!=item['size'] or (expected and digest.hexdigest()!=expected):raise RuntimeError('Descarga incompleta o hash incorrecto: '+item['path'])
        partial.replace(path)
    finally:partial.unlink(missing_ok=True)

def setup():
    assets=json.loads(Path(__file__).with_name('supertonic_assets.json').read_text(encoding='utf-8'))
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(prepare,assets))
    (FOLDER/'NOTICE.txt').write_text('Supertonic 3 archived models: OpenRAIL-M (see LICENSE). Helper code: MIT.\nhttps://github.com/supertone-oss-archive/supertonic\nhttps://huggingface.co/supertone-oss-archive/supertonic-3\nRevision: '+REVISION+'\n',encoding='utf-8')
    print('Supertonic 3 preparado: cinco voces masculinas y cinco femeninas.',flush=True)

if __name__=='__main__':
    try:setup()
    except Exception as exc:raise SystemExit(str(exc))
