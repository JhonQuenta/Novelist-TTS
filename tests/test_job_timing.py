import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from novelavoz import exporter


class JobTimingTests(unittest.TestCase):
    def test_lifecycle_uses_processing_start_not_queue_time(self):
        with tempfile.TemporaryDirectory() as directory:
            state={'test':{'created':10,'status':'queued'}}
            with patch.object(exporter,'STATES',state),patch.object(exporter,'JOBS',Path(directory)):
                with patch.object(exporter.time,'time',return_value=100):
                    exporter.update('test',status='running')
                with patch.object(exporter.time,'time',return_value=110):
                    exporter.update('test',stage='narration',eta_seconds=20)
                with patch.object(exporter.time,'time',return_value=120):
                    exporter.update('test',status='done')
            self.assertEqual(state['test']['started'],100)
            self.assertEqual(state['test']['finished'],120)
            self.assertIsNone(state['test']['eta_seconds'])

    def test_media_clock_estimates_remaining_and_checks_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            progress_file=Path(directory)/'progress.txt';samples=[]
            def fake_run(args,cancel,timeout,cwd=None):
                self.assertIn('-progress',args)
                progress_file.write_text('out_time_us=5000000\n',encoding='utf-8')
                self.assertFalse(cancel())
            with patch.object(exporter,'run',side_effect=fake_run),patch.object(exporter.time,'monotonic',side_effect=[100,102]):
                exporter.run_media(['ffmpeg','-i','in.wav','out.opus'],lambda:False,60,progress_file,10,lambda fraction,eta:samples.append((fraction,eta)))
            self.assertEqual(samples,[(.5,2),(1,0)])
            with patch.object(exporter,'run',side_effect=lambda args,cancel,*a,**kw:self.assertTrue(cancel())):
                with self.assertRaises(exporter.Cancelled):
                    exporter.run_media(['ffmpeg'],lambda:True,60,progress_file,10,lambda *args:self.fail('Cancelled progress'))
