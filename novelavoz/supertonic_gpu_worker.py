"""Isolate optional DirectML libraries from the application's CPU runtime."""
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from novelavoz.books import DATA
sys.path.insert(0,str(DATA/'supertonic-gpu-runtime'))
from novelavoz.supertonic_engine import _synthesize_local

if __name__=='__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for line in sys.stdin:
        try:
            item=json.loads(line)
            _synthesize_local(item['text'],item['voice'],item['speed'],item['output'],
                steps=item['steps'],variation=item['variation'],device_id=item['device_id'])
            result={'ok':True}
        except Exception as exc:
            result={'ok':False,'error':str(exc).strip() or 'Supertonic no pudo generar audio con la GPU.'}
        print(json.dumps(result,ensure_ascii=False),flush=True)
