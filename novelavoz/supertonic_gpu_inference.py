"""Keep intermediate inference tensors on DirectML instead of round-tripping.

https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html
Text, tensor shapes, precision, model steps and seeded noise stay unchanged.
"""
import numpy as np


class GpuInference:
    def __init__(self,model,runtime,device_id):
        self.model=model
        self.runtime=runtime
        self.device_id=device_id
        self.enabled=True
        self.disabled_reason=None

    def upload(self,value):
        return self.runtime.OrtValue.ortvalue_from_numpy(np.ascontiguousarray(value),'dml',self.device_id)

    def run(self,session,inputs):
        binding=session.io_binding()
        for name,value in inputs.items():
            if isinstance(value,self.runtime.OrtValue):binding.bind_ortvalue_input(name,value)
            else:binding.bind_cpu_input(name,value)
        for output in session.get_outputs():binding.bind_output(output.name,'dml',self.device_id)
        session.run_with_iobinding(binding)
        return binding.get_outputs()

    def batch(self,text_list,lang_list,style,total_step,speed=1.05,rng=None):
        if not self.enabled:return self.model.batch(text_list,lang_list,style,total_step,speed,rng)
        # Preserve RNG state if a device/driver cannot support these bindings.
        from copy import deepcopy
        state=deepcopy(rng.bit_generator.state) if rng is not None else None
        try:
            return self.bound(text_list,lang_list,style,total_step,speed,rng)
        except (RuntimeError,ValueError) as exc:
            self.enabled=False;self.disabled_reason=str(exc)
            if state is not None:rng.bit_generator.state=state
            return self.model.batch(text_list,lang_list,style,total_step,speed,rng)

    def bound(self,text_list,lang_list,style,total_step,speed,rng):
        model=self.model;bsz=len(text_list)
        ids,mask=model.text_processor(text_list,lang_list)
        durations,*_=model.dp_ort.run(None,{'text_ids':ids,'style_dp':style.dp,'text_mask':mask})
        durations=durations/speed
        embedding=self.run(model.text_enc_ort,{'text_ids':ids,'style_ttl':style.ttl,'text_mask':mask})[0]
        latent,latent_mask=model.sample_noisy_latent(durations,rng)
        latent=self.upload(latent)
        static={'text_emb':embedding,'style_ttl':self.upload(style.ttl),'text_mask':self.upload(mask),
            'latent_mask':self.upload(latent_mask),'total_step':self.upload(np.array([total_step]*bsz,dtype=np.float32))}
        for step in range(total_step):
            latent=self.run(model.vector_est_ort,{**static,'noisy_latent':latent,
                'current_step':np.array([step]*bsz,dtype=np.float32)})[0]
        audio=self.run(model.vocoder_ort,{'latent':latent})[0].numpy()
        return audio,durations
