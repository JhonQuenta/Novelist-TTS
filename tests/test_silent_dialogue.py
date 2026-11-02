import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from novelavoz import engines


class SilentDialogueTests(unittest.TestCase):
    def test_punctuation_only_preserves_a_silent_cue_without_calling_engine(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(engines,'run',side_effect=AssertionError('No synthesis needed')):
            for text in ('“…”','...','***','—','¿…?'):
                path=Path(directory)/'pause.wav'
                seconds=engines.synthesize(text,{'engine':'narrator','voice':'narrator-es-MX-Jorge-1.0.2.0','pause':.15},path)
                with wave.open(str(path),'rb') as audio:
                    self.assertEqual(audio.getparams()[:3],(1,2,24000))
                    self.assertEqual(audio.readframes(audio.getnframes()),b'\0\0'*12000)
                self.assertEqual(seconds,.5)

    def test_blank_worker_errors_have_a_visible_description(self):
        with self.assertRaisesRegex(RuntimeError,'código 1.*sin un mensaje'):
            engines.run([sys.executable,'-c',"import sys;sys.stderr.write('\\r\\n');sys.exit(1)"])
