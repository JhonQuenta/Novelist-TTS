"""Cancellable Google Translate synthesis subprocess; no cloud key required."""
import json, sys, time
from pathlib import Path
from gtts import gTTS

if __name__=='__main__':
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    if request['tld'] not in ('com.mx','es','us'):
        raise SystemExit('Variante de Google no permitida.')
    for attempt in range(2):
        try:
            gTTS(text=request['text'],lang='es',tld=request['tld'],lang_check=False,timeout=(10,30)).save(request['output'])
            break
        except Exception as exc:
            if attempt==1:
                Path(request['output']).unlink(missing_ok=True)
                raise SystemExit('Google Traductor no pudo generar audio. Comprueba internet o reanuda más tarde. '+str(exc))
            time.sleep(2)
