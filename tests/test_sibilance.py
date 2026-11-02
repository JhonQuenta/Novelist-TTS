import shutil, tempfile, unittest, wave
from pathlib import Path
from unittest.mock import patch
from novelavoz import engines

class SibilanceTests(unittest.TestCase):
    def test_defaults_scope_and_invalid_values(self):
        for engine in engines.MICROSOFT_ENGINES:
            self.assertEqual(engines.validate_settings({'engine':engine,'voice':'sample'})['deess'],'medium')
        self.assertEqual(engines.validate_settings({'engine':'gtts','voice':'google-es-MX','deess':'strong'})['deess'],'off')
        for value in ('invalid',None,[],{}):
            with self.assertRaises(ValueError):
                engines.validate_settings({'engine':'edge','voice':'sample','deess':value})

    def test_real_filter_in_shared_synthesis_pipeline(self):
        # The native backend is stubbed; the final FFmpeg conversion is real.
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'input.wav'
            rng=np.random.default_rng(52);t=np.arange(24000)/24000
            signal=.25*np.sin(2*np.pi*400*t)+.15*np.sin(2*np.pi*7000*t)+.025*rng.normal(size=t.size)
            with wave.open(str(source),'wb') as wav:
                wav.setparams((1,2,24000,0,'NONE','not compressed'))
                wav.writeframes((signal*32767).astype('<i2').tobytes())
            original_run=engines.run
            calls=[]
            def worker_or_ffmpeg(args,*a,**kw):
                if str(args[0])==engines.ffmpeg():
                    calls.append(args)
                    return original_run(args,*a,**kw)
                shutil.copyfile(source,root/'result.source.wav')
                return ''
            def fake_online(coroutine):
                coroutine.close()
                shutil.copyfile(source,root/'result.source.mp3')
            for engine in ('edge','narrator','sapi','onecore'):
                with patch.object(engines,'run',side_effect=worker_or_ffmpeg),patch('novelavoz.narrator.request',return_value={}),patch('novelavoz.narrator_session.SESSION.synthesize',side_effect=lambda *args:shutil.copyfile(source,root/'result.source.wav')),patch.object(engines.asyncio,'run',side_effect=fake_online):
                    for level in ('off','medium'):
                        engines.synthesize('Texto',{'engine':engine,'voice':'sample','deess':level,'pause':0},root/'result.wav')
                        chain=calls[-1][calls[-1].index('-af')+1]
                        self.assertEqual('deesser=' in chain,level!='off')
                        with wave.open(str(root/'result.wav')) as wav:
                            self.assertEqual(wav.getnframes(),24000)
                            result=np.frombuffer(wav.readframes(24000),dtype='<i2').astype(float)
                        energy=abs(np.fft.rfft(result))[7000]**2
                        if level=='off':original_energy=energy
                        else:self.assertLess(energy,original_energy*.6)

if __name__=='__main__':unittest.main()
