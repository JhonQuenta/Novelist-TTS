import unittest
from novelavoz.engines import validate_settings,narration_text,MICROSOFT_ENGINES

class QuestionTests(unittest.TestCase):
    def test_opt_in_and_scope(self):
        text='Ella sonrió. ¿Qué veían? ¡No! El Dr. pagó 3.14 euros.'
        for engine in MICROSOFT_ENGINES:
            original={'engine':engine,'voice':'sample'}
            self.assertEqual(narration_text(text,validate_settings(original)),text)
            selected=validate_settings({**original,'neutral_questions':True})
            self.assertEqual(narration_text(text,selected),'Ella sonrió. Qué veían. No. El Dr. pagó 3.14 euros.')
            self.assertNotIn('neutral_questions',original)
        selected=validate_settings({'engine':'gtts','voice':'google-es-MX','neutral_questions':True})
        self.assertEqual(narration_text(text,selected),text)

    def test_invalid_value_rejected(self):
        for value in ('false',1,None,[]):
            with self.assertRaises(ValueError):validate_settings({'engine':'narrator','voice':'sample','neutral_questions':value})

    def test_quoted_questions_and_emphatic_punctuation(self):
        text='«¿De verdad?!» ¡¡Sí!!\n¿Por qué?'
        self.assertEqual(narration_text(text,{'engine':'narrator','neutral_questions':True}),'«De verdad.» Sí.\nPor qué.')
