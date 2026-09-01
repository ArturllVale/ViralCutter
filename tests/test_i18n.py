import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from i18n.i18n import I18nAuto, load_language_list

class TestI18n(unittest.TestCase):
    def test_load_existing_language(self):
        en_map = load_language_list('en_US')
        self.assertIsInstance(en_map, dict)
        pt_map = load_language_list('pt_BR')
        self.assertIsInstance(pt_map, dict)

    def test_load_nonexistent_language_returns_empty(self):
        nonexistent = load_language_list('non_existent_lang_xyz')
        self.assertEqual(nonexistent, {})

    def test_i18n_auto_fallback_to_en(self):
        i18n_instance = I18nAuto('non_existent_lang')
        self.assertEqual(i18n_instance.language, 'en_US')
        self.assertIn('Use Language: en_US', repr(i18n_instance))

    def test_i18n_translation_and_fallback(self):
        i18n_pt = I18nAuto('pt_BR')
        # Known key in pt_BR or missing key
        self.assertEqual(i18n_pt('Totally Random Nonexistent Key 123'), 'Totally Random Nonexistent Key 123')

    def test_i18n_auto_init(self):
        i18n_auto = I18nAuto('Auto')
        self.assertIsNotNone(i18n_auto.language)
        self.assertIsInstance(i18n_auto.language_map, dict)

if __name__ == '__main__':
    unittest.main()
