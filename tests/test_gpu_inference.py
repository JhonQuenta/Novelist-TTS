import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
from novelavoz.supertonic_gpu_inference import GpuInference


class Value:
    downloads=0
    def __init__(self,data):self.data=np.asarray(data)
    @staticmethod
    def ortvalue_from_numpy(data,*args):return Value(data.copy())
    def numpy(self):
        Value.downloads+=1
        return self.data.copy()


class Binding:
    def __init__(self):self.inputs={};self.outputs=[]
    def bind_cpu_input(self,name,value):self.inputs[name]=value
    def bind_ortvalue_input(self,name,value):self.inputs[name]=value.data
    def bind_output(self,*args):pass
    def get_outputs(self):return self.outputs


class Session:
    def __init__(self,compute):self.compute=compute
    def run(self,_,inputs):return [self.compute(inputs)]
    def io_binding(self):return Binding()
    def get_outputs(self):return [SimpleNamespace(name='output')]
    def run_with_iobinding(self,binding):binding.outputs=[Value(self.compute(binding.inputs))]


class GpuInferenceTests(unittest.TestCase):
    def test_same_calculation_and_single_final_download(self):
        model=SimpleNamespace(
            text_processor=lambda *args:(np.arange(5).reshape(1,5),np.ones((1,1,5),dtype=np.float32)),
            dp_ort=Session(lambda _:np.array([1.0],dtype=np.float32)),
            text_enc_ort=Session(lambda inputs:inputs['text_ids'][:,None,:].astype(np.float32)),
            vector_est_ort=Session(lambda x:x['noisy_latent']+.01*x['text_emb'].mean()+x['current_step'][0]/x['total_step'][0]),
            vocoder_ort=Session(lambda x:x['latent'].mean(axis=1)),
            sample_noisy_latent=lambda duration,rng:(rng.standard_normal((1,2,4)).astype(np.float32),np.ones((1,1,4),dtype=np.float32)))
        style=SimpleNamespace(dp=np.ones(1,dtype=np.float32),ttl=np.ones(1,dtype=np.float32))
        bound=GpuInference(model,SimpleNamespace(OrtValue=Value),0)
        for steps in (5,16):
            latent,_=model.sample_noisy_latent(None,np.random.default_rng(42))
            for step in range(steps):latent=latent+.02+np.float32(step)/np.float32(steps)
            expected=latent.mean(axis=1)
            Value.downloads=0
            actual,durations=bound.batch(['Texto'],['es'],style,steps,speed=1,rng=np.random.default_rng(42))
            np.testing.assert_array_equal(actual,expected)
            self.assertEqual(Value.downloads,1)
            np.testing.assert_array_equal(durations,[1.0])

    def test_fallback_restores_noise_seed_after_partial_execution(self):
        model=Mock()
        model.batch.side_effect=lambda *args:args[-1].standard_normal(8)
        bound=GpuInference(model,None,0)
        def failed(*args):
            args[-1].standard_normal(100)
            raise RuntimeError('Unsupported GPU binding')
        with patch.object(bound,'bound',side_effect=failed) as optimized:
            actual=bound.batch(['Texto'],['es'],None,5,rng=np.random.default_rng(42))
            np.testing.assert_array_equal(actual,np.random.default_rng(42).standard_normal(8))
            self.assertFalse(bound.enabled)
            bound.batch(['Otro'],['es'],None,5,rng=np.random.default_rng(42))
            self.assertEqual(optimized.call_count,1)
