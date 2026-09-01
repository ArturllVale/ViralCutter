import unittest
import os
import sys
import json
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.cut_json import process_segments, cut_json_transcript

class TestCutJson(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_process_segments_basic_trim(self):
        data = {
            'segments': [
                {
                    'start': 5.0,
                    'end': 15.0,
                    'text': 'Hello world test segment',
                    'words': [
                        {'word': 'Hello', 'start': 5.0, 'end': 6.0},
                        {'word': 'world', 'start': 6.5, 'end': 8.0},
                        {'word': 'test', 'start': 8.5, 'end': 11.0},
                        {'word': 'segment', 'start': 11.5, 'end': 15.0}
                    ]
                },
                {
                    'start': 20.0,
                    'end': 30.0,
                    'text': 'Second segment out of bounds'
                }
            ]
        }
        # Cut from 6.0 to 12.0
        result = process_segments(data, start_time=6.0, end_time=12.0)
        self.assertEqual(len(result['segments']), 1)
        seg = result['segments'][0]
        self.assertEqual(seg['start'], 0.0) # 6.0 - 6.0 = 0.0
        self.assertEqual(seg['end'], 6.0)   # 12.0 - 6.0 = 6.0
        # Words inside 6.0-12.0 should be shifted
        self.assertGreaterEqual(len(seg['words']), 2)
        for w in seg['words']:
            self.assertGreaterEqual(w['start'], 0.0)
            self.assertLessEqual(w['end'], 6.0)

    def test_process_segments_synthesize_words_fallback(self):
        data = {
            'segments': [
                {
                    'start': 10.0,
                    'end': 20.0,
                    'text': 'One Two Three Four',
                    'words': []
                }
            ]
        }
        result = process_segments(data, start_time=10.0, end_time=20.0)
        self.assertEqual(len(result['segments']), 1)
        seg = result['segments'][0]
        self.assertEqual(len(seg['words']), 4)
        self.assertEqual(seg['words'][0]['word'], 'One')
        self.assertEqual(seg['words'][-1]['word'], 'Four')

    def test_cut_json_transcript_e2e(self):
        in_path = os.path.join(self.test_dir, 'input.json')
        out_path = os.path.join(self.test_dir, 'output.json')
        sample_data = {
            'segments': [
                {
                    'start': 10.0,
                    'end': 25.0,
                    'text': 'Viral clip text',
                    'words': [
                        {'word': 'Viral', 'start': 10.0, 'end': 12.0},
                        {'word': 'clip', 'start': 12.5, 'end': 15.0},
                        {'word': 'text', 'start': 15.5, 'end': 20.0}
                    ]
                }
            ]
        }
        with open(in_path, 'w', encoding='utf-8') as f:
            json.dump(sample_data, f)

        cut_json_transcript(in_path, out_path, start_time=10.0, end_time=25.0)
        self.assertTrue(os.path.exists(out_path))

        with open(out_path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        self.assertEqual(len(loaded['segments']), 1)
        self.assertEqual(loaded['segments'][0]['start'], 0.0)

    def test_cut_json_missing_input_handled(self):
        nonexistent = os.path.join(self.test_dir, 'missing.json')
        out_path = os.path.join(self.test_dir, 'out.json')
        # Should not raise exception
        cut_json_transcript(nonexistent, out_path, 0, 10)
        self.assertFalse(os.path.exists(out_path))

if __name__ == '__main__':
    unittest.main()
