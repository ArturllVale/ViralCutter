import unittest
import os
import sys
import json
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.translate_json import (
    substituir_texto,
    join_sentences,
    unjoin_sentences,
    adjust_segments,
    separator
)

class TestTranslateJson(unittest.TestCase):
    def test_substituir_texto(self):
        text = 'Hello world test'
        subs = {'Hello': 'Ola'}
        result = substituir_texto(text, subs)
        self.assertEqual(result, 'Ola world test')

    def test_join_and_unjoin_sentences(self):
        texts = ['Hi there.', 'This is a test.']
        joined = join_sentences(texts, max_chars=500)
        self.assertGreaterEqual(len(joined), 1)

        modified = joined[0].replace('Hi there.', 'Ola todos.').replace('This is a test.', 'Isto e um teste.')
        unjoined = unjoin_sentences(joined[0], modified, separator)
        self.assertGreaterEqual(len(unjoined), 1)

    def test_adjust_segments(self):
        segments = [
            {'start': 0.0, 'end': 2.0, 'text': 'First segment', 'words': []},
            {'start': 2.5, 'end': 5.0, 'text': 'Second segment', 'words': []}
        ]
        adjusted = adjust_segments(segments)
        self.assertEqual(len(adjusted), 2)
        self.assertGreater(adjusted[0]['end'], 0.0)
        self.assertEqual(len(adjusted[0]['words']), 2)

if __name__ == '__main__':
    unittest.main()
