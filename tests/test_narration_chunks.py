import unittest
from novelavoz.books import split_text

class NarrationChunkTests(unittest.TestCase):
    def test_prologue_phrases_remain_in_one_utterance(self):
        text=('El árbol del jardín era tan mayor como la casa; sus ramas cubrían todo el camino. Cada primavera los vecinos organizaban una pequeña feria junto a la fuente y colocaban faroles de papel entre las hojas. Después recogían las mesas antes de que llegara la noche.\n'
              'Durante la representación, los pequeños autómatas le tiraban del cabello al muñeco de madera y escondían su sombrero detrás del escenario. El público esperaba el final con curiosidad, mientras la directora preparaba la siguiente escena sin interrumpir la función.')
        parts=split_text(text)
        for phrase in ('era tan mayor como','le tiraban del cabello'):
            self.assertTrue(any(phrase in p['text'] for p in parts))
        self.assertEqual(len(parts),2)
        self.check_offsets(text,parts)

    def check_offsets(self,text,parts):
        self.assertEqual(' '.join(text.split()),' '.join(' '.join(p['text'] for p in parts).split()))
        for p in parts:self.assertEqual(text[p['offset']:p['end_offset']],p['text'])

    def test_long_sentence_can_exceed_soft_target(self):
        text='Una frase que sigue '+('sin perder su continuidad '*15)+'hasta el final.'
        self.assertGreater(len(text),280)
        self.assertEqual(len(split_text(text)),1)

    def test_quotes_abbreviations_decimals_and_paragraphs(self):
        text='El Dr. Pérez pagó 3.14 euros. «¿Vendrá mañana?» Sí, vendrá.\n\nPrólogo\nUna nueva historia.'
        parts=split_text(text,limit=10)
        self.assertIn('El Dr. Pérez pagó 3.14 euros.',[p['text'] for p in parts])
        self.assertIn('«¿Vendrá mañana?»',[p['text'] for p in parts])
        self.check_offsets(text,parts)

    def test_extreme_unpunctuated_text_and_clause_fallback(self):
        for text in (('palabra '*800),('primera parte '*40)+', '+('segunda parte '*120)+'.'):
            parts=split_text(text)
            self.assertTrue(all(len(p['text'])<=1200 for p in parts))
            self.check_offsets(text,parts)
        self.assertEqual(split_text(' \n\n  '),[])

if __name__=='__main__':unittest.main()
