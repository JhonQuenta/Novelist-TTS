import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from novelavoz import supertonic_engine as engine
from novelavoz.engines import Cancelled


class SupertonicGpuTests(unittest.TestCase):
    def test_only_verified_configuration_enables_gpu(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(engine,'DATA',Path(directory)),patch.object(engine,'_gpu_error',None):
            runtime=Path(directory)/'supertonic-gpu-runtime/onnxruntime';runtime.mkdir(parents=True);(runtime/'__init__.py').touch()
            config=Path(directory)/'supertonic-compute.json'
            for item in ({'provider':'directml','device_id':0}, {'provider':'directml','device_id':True,'verified':True}):
                config.write_text(json.dumps(item),encoding='utf-8');self.assertIsNone(engine.gpu_configuration())
            config.write_text(json.dumps({'provider':'directml','device_id':0,'verified':True}),encoding='utf-8')
            self.assertEqual(engine.gpu_configuration()['device_id'],0)

    def test_gpu_failure_falls_back_but_cancellation_does_not(self):
        configuration={'device_id':0}
        session=Mock();session.synthesize.side_effect=RuntimeError('GPU unavailable')
        with patch.object(engine,'gpu_configuration',return_value=configuration),patch.object(engine,'_gpu_session',session),patch.object(engine,'_gpu_error',None),patch.object(engine,'_synthesize_local') as cpu:
            engine.synthesize('Texto.','supertonic-F5',1,Path('unused.wav'),steps=5,variation=2)
            self.assertEqual(cpu.call_count,1)
            request=session.synthesize.call_args.args[0]
            self.assertEqual((request['steps'],request['variation'],request['device_id']),(5,2,0))
            self.assertIn('GPU unavailable',engine._gpu_error)
            session.synthesize.side_effect=Cancelled();cpu.reset_mock()
            with self.assertRaises(Cancelled):engine.synthesize('Texto.','supertonic-F5',1,Path('unused.wav'))
            cpu.assert_not_called()
