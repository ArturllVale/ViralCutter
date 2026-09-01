import unittest
import os
import sys
import json
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.adjust_subtitles import format_time_ass, sanitize_word_for_ass, generate_ass_from_file

class TestAdjustSubtitles(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_format_time_ass(self):
        self.assertEqual(format_time_ass(0), '0:00:00.00')
        self.assertEqual(format_time_ass(1.234), '0:00:01.23')
        self.assertEqual(format_time_ass(65.5), '0:01:05.50')
        self.assertEqual(format_time_ass(3661.05), '1:01:01.05')

    def test_sanitize_word_for_ass(self):
        self.assertEqual(sanitize_word_for_ass('Hello!'), 'Hello')
        self.assertEqual(sanitize_word_for_ass(r'{Special} \Tags/'), 'Special Tags')
        self.assertEqual(sanitize_word_for_ass('Não é ótimo?', remove_punct=True), 'Não é ótimo')
        self.assertEqual(sanitize_word_for_ass('Wait, what?', remove_punct=False), 'Wait, what?')

    def test_generate_ass_from_file_basic(self):
        json_file = os.path.join(self.test_dir, '000_clip_processed.json')
        ass_output = os.path.join(self.test_dir, '000_clip_processed.ass')

        data = {
            'segments': [
                {
                    'start': 0.0,
                    'end': 3.0,
                    'text': 'This is a viral test.',
                    'words': [
                        {'word': 'This', 'start': 0.0, 'end': 0.5},
                        {'word': 'is', 'start': 0.6, 'end': 1.0},
                        {'word': 'a', 'start': 1.1, 'end': 1.3},
                        {'word': 'viral', 'start': 1.4, 'end': 2.0},
                        {'word': 'test.', 'start': 2.1, 'end': 3.0}
                    ]
                }
            ]
        }
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)

        generate_ass_from_file(
            input_path=json_file,
            output_path=ass_output,
            project_folder=self.test_dir,
            base_color='&H00FFFFFF&',
            base_size=50,
            highlight_size=55,
            highlight_color='&H0000FFFF&',
            words_per_block=2,
            gap_limit=1.0,
            mode='default',
            vertical_position=210,
            alignment=2,
            font='Arial',
            outline_color='&H00000000&',
            shadow_color='&H00000000&',
            bold=1,
            italic=0,
            underline=0,
            strikeout=0,
            border_style=1,
            outline_thickness=3,
            shadow_size=2,
            uppercase=1,
            face_modes={},
            remove_punctuation=True
        )

        self.assertTrue(os.path.exists(ass_output))
        with open(ass_output, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('[Script Info]', content)
        self.assertIn('[V4+ Styles]', content)
        self.assertIn('[Events]', content)
        self.assertIn('Dialogue:', content)

if __name__ == '__main__':
    unittest.main()
