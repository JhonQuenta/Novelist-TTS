import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from novelavoz import exporter,engines
from novelavoz.books import split_text


class NaturalPauseTests(unittest.TestCase):
    def test_only_quiet_edges_change_and_boundaries_differ(self):
        rate=24000
        speech=array('h',[5000]*rate)
        source_pcm=array('h',[0]*1920)+speech+array('h',[0]*19200)
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'in.wav'
            with wave.open(str(source),'wb') as audio:
                audio.setparams((1,2,rate,0,'NONE','not compressed'));audio.writeframes(source_pcm.tobytes())
            lengths=[]
            for boundary in ('sentence','paragraph','chapter'):
                target=Path(directory)/(boundary+'.wav')
                with wave.open(str(target),'wb') as merged:
                    merged.setparams((1,2,rate,0,'NONE','not compressed'))
                    seconds=exporter.append_audio(merged,source,lambda:False,boundary,.15)
                with wave.open(str(target),'rb') as audio:
                    pcm=array('h',audio.readframes(audio.getnframes()))
                    self.assertEqual(audio.getnframes()/rate,seconds)
                self.assertEqual(array('h',(v for v in pcm if v)),speech)
                lengths.append(seconds)
            self.assertLess(lengths[0],lengths[1]);self.assertLess(lengths[1],lengths[2])

    def test_offsets_distinguish_paragraphs_without_splitting_commas(self):
        text='Primera frase, con una coma. Segunda frase.\nNuevo párrafo.'
        parts=split_text(text,limit=1)
        self.assertEqual(parts[0]['text'],'Primera frase, con una coma.')
        self.assertEqual(exporter.narration_boundary(text,parts,0),'sentence')
        self.assertEqual(exporter.narration_boundary(text,parts,1),'paragraph')
        self.assertEqual(exporter.narration_boundary(text,parts,2,'chapter'),'chapter')

    def test_pause_mode_reuses_the_same_speech_cache(self):
        settings=engines.validate_settings({'engine':'narrator','voice':'sample'})
        self.assertTrue(settings['natural_pauses'])
        self.assertEqual(exporter.fragment_cache_key('Hola.',settings),exporter.fragment_cache_key('Hola.',{**settings,'natural_pauses':False}))
        with self.assertRaises(ValueError):engines.validate_settings({**settings,'natural_pauses':'true'})
