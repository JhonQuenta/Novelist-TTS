import tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch
import numpy as np
from novelavoz import engines,supertonic_engine as engine

class SupertonicQualityTests(unittest.TestCase):
    def test_commas_preserve_words_and_decimal_numbers(self):
        text='«Mañana comenzará», pensó, mientras contaba 3,14 monedas. Después sonrió.'
        parts=engine.narration_parts(text)
        self.assertEqual(parts,[text])
        self.assertIn('3,14',parts[0])

    def test_high_speed_applied_after_model_and_quality_forwarded(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'result.wav';calls=[]
            def fake(text,voice,speed,output,cancel=None,**kwargs):
                calls.append((text,speed,kwargs))
                t=np.arange(24000)/24000
                with wave.open(str(output),'wb') as w:
                    w.setparams((1,2,24000,0,'NONE','not compressed'));w.writeframes((np.sin(440*2*np.pi*t)*5000).astype('<i2').tobytes())
            with patch.object(engine,'synthesize',side_effect=fake):
                duration=engines.synthesize('Texto, con pausa.',{'engine':'supertonic','voice':'supertonic-F5','rate':0,'pause':0,'supertonic_steps':16,'supertonic_commas':True},path)
                previous=path.read_bytes()
                engines.synthesize('Texto, con pausa.',{'engine':'supertonic','voice':'supertonic-F5','rate':0,'supertonic_base_rate':50,'pause':0,'supertonic_steps':16},path)
                self.assertEqual(path.read_bytes(),previous)
            self.assertEqual(calls[0][1],1.0)
            self.assertEqual(calls[0][2],{'steps':16,'variation':0})
            self.assertTrue(.75<duration<.85,duration)

    def test_invalid_quality_and_flags(self):
        for change in ({'supertonic_steps':True},{'supertonic_steps':7},{'supertonic_steps':'10'},{'supertonic_variation':-1},{'supertonic_variation':True}):
            with self.assertRaises(ValueError):engines.validate_settings({'engine':'supertonic','voice':'supertonic-F5',**change})

    def test_old_saved_comma_option_is_ignored(self):
        settings=engines.validate_settings({'engine':'supertonic','voice':'supertonic-F5','rate':50,'supertonic_commas':True})
        self.assertNotIn('supertonic_commas',settings)
        self.assertEqual(settings['rate'],50)
        self.assertNotIn('supertonic_base_rate',settings)

    def test_seeded_latents_do_not_use_global_random_state(self):
        from novelavoz.supertonic_helper import TextToSpeech
        model=object.__new__(TextToSpeech)
        model.sample_rate=24000;model.base_chunk_size=512;model.chunk_compress_factor=2;model.ldim=4
        with patch('numpy.random.randn',side_effect=AssertionError('global RNG used')):
            first,_=model.sample_noisy_latent(np.array([.5]),np.random.default_rng(123))
            second,_=model.sample_noisy_latent(np.array([.5]),np.random.default_rng(123))
        np.testing.assert_array_equal(first,second)
