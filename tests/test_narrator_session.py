import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from novelavoz import narrator_session
from novelavoz.engines import Cancelled

WORKER='''import json,os,sys,time
for line in sys.stdin:
    request=json.loads(line)
    if request.get('mode')=='crash':os._exit(7)
    if request.get('mode')=='wait':time.sleep(2)
    print(json.dumps({'ok':request.get('mode')!='reject','error':'Texto rechazado'}),flush=True)
'''


class NarratorSessionTests(unittest.TestCase):
    def test_reuse_and_recovery_after_crash_or_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            worker=Path(directory)/'worker.py';worker.write_text(WORKER,encoding='utf-8')
            session=narrator_session.NarratorSession()
            try:
                with patch.object(narrator_session,'WORKER',worker):
                    session.synthesize({'text':'niña, canción, ¿qué?'})
                    process=session.process
                    session.synthesize({'text':'Segunda frase.'})
                    self.assertIs(process,session.process)
                    with self.assertRaisesRegex(RuntimeError,'Texto rechazado'):session.synthesize({'mode':'reject'})
                    self.assertIsNone(session.process)
                    session.synthesize({})
                    with self.assertRaisesRegex(RuntimeError,'inesperadamente'):session.synthesize({'mode':'crash'})
                    session.synthesize({})
            finally:session.close()

    def test_timeout_and_cancellation_stop_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            worker=Path(directory)/'worker.py';worker.write_text(WORKER,encoding='utf-8')
            session=narrator_session.NarratorSession()
            try:
                with patch.object(narrator_session,'WORKER',worker):
                    session.synthesize({})
                    with self.assertRaisesRegex(RuntimeError,'tiempo permitido'):session.synthesize({'mode':'wait'},timeout=.05)
                    self.assertIsNone(session.process)
                    session.synthesize({})
                    calls=[]
                    def cancel():
                        calls.append(1)
                        return len(calls)>2
                    with self.assertRaises(Cancelled):session.synthesize({'mode':'wait'},cancel=cancel)
                    self.assertIsNone(session.process)
                    session.synthesize({})
            finally:session.close()
