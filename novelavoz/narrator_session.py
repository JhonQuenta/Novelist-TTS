"""Keep the isolated local speech worker alive between synthesis requests."""
import atexit
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

WORKER=Path(__file__).with_name('narrator_worker.py')


class NarratorSession:
    def __init__(self,worker=None,description='la voz local'):
        self.lock=threading.Lock()
        self.process=None
        self.worker=worker
        self.description=description

    def close(self):
        process=self.process
        self.process=None
        if process is not None:
            if process.poll() is None:process.kill()
            process.wait()
            for stream in (process.stdin,process.stdout,process.stderr):
                if stream is not None:stream.close()

    def _start(self):
        self.close()
        self.responses=queue.Queue()
        responses=self.responses
        self.process=subprocess.Popen([sys.executable,str(self.worker or WORKER),'--serve'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        process=self.process
        def read():
            try:
                for line in process.stdout:
                    try:responses.put(json.loads(line))
                    except ValueError:continue
            except (OSError,ValueError):pass
            finally:responses.put(None)
        self.reader=threading.Thread(target=read,daemon=True)
        self.reader.start()

    def synthesize(self,request,cancel=None,timeout=120):
        from .engines import Cancelled
        with self.lock:
            try:
                if cancel and cancel():raise Cancelled()
                if self.process is None or self.process.poll() is not None:self._start()
                try:
                    self.process.stdin.write(json.dumps(request,ensure_ascii=False)+'\n')
                    self.process.stdin.flush()
                except (OSError,ValueError) as exc:
                    raise RuntimeError(f'El proceso de {self.description} se cerró al recibir el texto. Puedes reanudar.') from exc
                deadline=time.monotonic()+timeout
                while True:
                    if cancel and cancel():raise Cancelled()
                    if time.monotonic()>=deadline:raise RuntimeError(f'{self.description.capitalize()} no respondió en el tiempo permitido. Puedes reanudar.')
                    try:response=self.responses.get(timeout=.05)
                    except queue.Empty:continue
                    if response is None:
                        code=self.process.poll()
                        raise RuntimeError(f'El proceso de {self.description} terminó inesperadamente (código {code}). Puedes reanudar.')
                    if response.get('ok') is not True:
                        raise RuntimeError(response.get('error') or 'La voz local rechazó el fragmento sin dar detalles. Puedes reanudar.')
                    return
            except BaseException:
                self.close()
                raise


SESSION=NarratorSession()
atexit.register(SESSION.close)
