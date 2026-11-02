import io,tempfile,unittest,wave,zipfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from novelavoz import engines,exporter,supertonic_engine

def write_wave(path,seconds=1):
    t=np.arange(round(24000*seconds))/24000
    with wave.open(str(path),'wb') as w:
        w.setparams((1,2,24000,0,'NONE','not compressed'))
        w.writeframes((np.sin(t*2*np.pi*440)*5000).astype('<i2').tobytes())

class ExportEfficiencyTests(unittest.TestCase):
    def test_source_cache_reused_for_controls_but_not_quality_or_variation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';output=root/'out.wav';calls=[]
            def fake(text,voice,speed,path,cancel=None,**kwargs):
                calls.append(kwargs);write_wave(path)
            settings={'engine':'supertonic','voice':'supertonic-F5'}
            with patch.object(supertonic_engine,'synthesize',side_effect=fake):
                engines.synthesize('Texto.',settings,output,source_cache=source)
                engines.synthesize('Texto.',{**settings,'rate':15,'pitch':1,'volume':80,'pause':.05},output,source_cache=source)
                self.assertEqual(len(calls),1)
                engines.synthesize('Texto.',{**settings,'supertonic_steps':16},output,source_cache=source)
                engines.synthesize('Texto.',{**settings,'supertonic_steps':16,'supertonic_variation':2},output,source_cache=source)
                self.assertEqual(len(calls),3)
                for p in source.glob('*.wav'):p.write_bytes(b'broken')
                engines.synthesize('Texto.',settings,output,source_cache=source)
                self.assertEqual(len(calls),4)

    def test_interrupted_source_is_never_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source'
            def interrupted(text,voice,speed,path,cancel=None,**kwargs):
                path.write_bytes(b'incomplete');raise engines.Cancelled()
            with patch.object(supertonic_engine,'synthesize',side_effect=interrupted):
                with self.assertRaises(engines.Cancelled):engines.synthesize('Texto.',{'engine':'supertonic','voice':'supertonic-F5'},root/'out.wav',source_cache=source)
            self.assertEqual(list(source.iterdir()),[])

    def test_merged_pcm_and_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'in.wav';target=root/'merged.wav';write_wave(source,12)
            with wave.open(str(target),'wb') as merged:
                merged.setparams((1,2,24000,0,'NONE','not compressed'))
                self.assertEqual(exporter.append_audio(merged,source,lambda:False),12)
            self.assertEqual(source.read_bytes(),target.read_bytes())
            with wave.open(str(target),'wb') as merged:
                merged.setparams((1,2,24000,0,'NONE','not compressed'))
                with self.assertRaises(engines.Cancelled):exporter.append_audio(merged,source,lambda:True)

    def test_cache_key_ignores_other_engines_settings(self):
        first=engines.validate_settings({'engine':'edge','voice':'es-MX-JorgeNeural','supertonic_steps':5})
        second=engines.validate_settings({**first,'supertonic_steps':16,'supertonic_variation':9})
        self.assertEqual(exporter.fragment_cache_key('Hola.',first),exporter.fragment_cache_key('Hola.',second))
        self.assertNotEqual(exporter.fragment_cache_key('Hola.',first),exporter.fragment_cache_key('Hola.',engines.validate_settings({**first,'pitch':1})))

    def test_multi_output_matches_separate_encodes_and_cancels(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'in.wav';write_wave(source,2)
            paths=[root/('combined.'+ext) for ext in ('mp3','m4a','opus')]
            exporter.encode_audio_formats(source,paths,lambda:False)
            def pcm_hash(path):return engines.run([engines.ffmpeg(),'-v','error','-i',path,'-map','0:a:0','-f','hash','-hash','sha256','-'])
            for path,codec,bitrate in zip(paths,('libmp3lame','aac','libopus'),('96k','96k','48k')):
                separate=root/('separate'+path.suffix)
                engines.run([engines.ffmpeg(),'-v','error','-y','-i',source,'-c:a',codec,'-b:a',bitrate,separate])
                self.assertEqual(pcm_hash(path),pcm_hash(separate))
            with patch.object(exporter,'run',side_effect=engines.Cancelled()):
                with self.assertRaises(engines.Cancelled):exporter.encode_audio_formats(source,paths,lambda:True)

    def test_zip_keeps_media_and_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'prólogo.mp3').write_bytes(b'audio');(root/'letras.lrc').write_text('Letras',encoding='utf-8')
            files=[{'name':p,'path':p} for p in ('prólogo.mp3','letras.lrc')]
            exporter.package_files(root,files,lambda:False)
            with zipfile.ZipFile(root/'NovelistTTS.zip') as z:
                self.assertEqual(z.getinfo('prólogo.mp3').compress_type,zipfile.ZIP_STORED)
                self.assertEqual(z.getinfo('letras.lrc').compress_type,zipfile.ZIP_DEFLATED)
                self.assertEqual(z.read('prólogo.mp3'),b'audio');self.assertIsNone(z.testzip())
            with self.assertRaises(engines.Cancelled):exporter.package_files(root,files,lambda:True)
