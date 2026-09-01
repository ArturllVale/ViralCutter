import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import tempfile
import shutil
import subprocess
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.download_video import convert_vtt_to_srt, validate_video_file
from scripts.transcribe_video import parse_srt, parse_vtt, is_valid_transcription_file
from scripts.cut_json import process_segments as process_cut_json_segments
from scripts.adjust_subtitles import format_time_ass, sanitize_word_for_ass, generate_ass_from_file
from scripts.burn_subtitles import escape_ffmpeg_filter_path, burn_video_file
from scripts.cut_segments import run_ffmpeg_cut
from scripts.organize_output import sanitize_filename, organize

class TestPostDownloadPipeline(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    # ---------------------------------------------------------
    # 1. VTT / SRT Conversion & Parsing Tests
    # ---------------------------------------------------------
    def test_vtt_to_srt_conversion_with_accents_and_settings(self):
        vtt_file = os.path.join(self.test_dir, "input.pt.vtt")
        vtt_content = """WEBVTT
Kind: captions
Language: pt

00:00:01.500 --> 00:00:04.200 position:50% align:middle
<c.colorE5E5E5>Olá mundo!</c> Este é um teste com acentuação: ação, café, coração.

00:00:04.200 --> 00:00:07.10
Segunda linha com milissegundos incompletos (apenas 2 dígitos).
"""
        with open(vtt_file, "w", encoding="utf-8") as f:
            f.write(vtt_content)

        convert_vtt_to_srt(self.test_dir)

        srt_file = os.path.join(self.test_dir, "input.srt")
        self.assertTrue(os.path.exists(srt_file))

        with open(srt_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Check Unicode preservation
        self.assertIn("ação, café, coração", content)
        # Check standard 3-digit millisecond timestamps
        self.assertIn("00:00:01,500 --> 00:00:04,200", content)
        self.assertIn("00:00:04,200 --> 00:00:07,100", content)

    def test_parse_srt_various_spacings(self):
        srt_file = os.path.join(self.test_dir, "test.srt")
        srt_content = """1
00:01:05,123 --> 00:01:10,456
Primeiro bloco de teste

2
00:01:10.500-->00:01:15.800
Segundo bloco com ponto e sem espaço
"""
        with open(srt_file, "w", encoding="utf-8") as f:
            f.write(srt_content)

        segments = parse_srt(srt_file)
        self.assertIsNotNone(segments)
        self.assertEqual(len(segments), 2)
        self.assertAlmostEqual(segments[0]["start"], 65.123, places=3)
        self.assertAlmostEqual(segments[0]["end"], 70.456, places=3)
        self.assertEqual(segments[0]["text"], "Primeiro bloco de teste")
        self.assertAlmostEqual(segments[1]["start"], 70.5, places=3)
        self.assertAlmostEqual(segments[1]["end"], 75.8, places=3)

    def test_parse_vtt_timestamps(self):
        vtt_file = os.path.join(self.test_dir, "test.vtt")
        vtt_content = """WEBVTT

01:05.100 --> 01:10.500
Trecho formatado em MM:SS.mmm

00:02:00.000 --> 00:02:05.000
Trecho formatado em HH:MM:SS.mmm
"""
        with open(vtt_file, "w", encoding="utf-8") as f:
            f.write(vtt_content)

        segments = parse_vtt(vtt_file)
        self.assertIsNotNone(segments)
        self.assertEqual(len(segments), 2)
        self.assertAlmostEqual(segments[0]["start"], 65.1, places=3)
        self.assertAlmostEqual(segments[0]["end"], 70.5, places=3)
        self.assertAlmostEqual(segments[1]["start"], 120.0, places=3)

    def test_is_valid_transcription_file(self):
        empty_file = os.path.join(self.test_dir, "empty.json")
        with open(empty_file, "w") as f:
            f.write("")
        self.assertFalse(is_valid_transcription_file(empty_file, is_json=True))

        invalid_json = os.path.join(self.test_dir, "invalid.json")
        with open(invalid_json, "w") as f:
            f.write("{invalid json")
        self.assertFalse(is_valid_transcription_file(invalid_json, is_json=True))

        valid_json = os.path.join(self.test_dir, "valid.json")
        with open(valid_json, "w", encoding="utf-8") as f:
            json.dump({"segments": [{"start": 0, "end": 5, "text": "ok"}]}, f)
        self.assertTrue(is_valid_transcription_file(valid_json, is_json=True))

    # ---------------------------------------------------------
    # 2. JSON Cutting & Word Synthesis Tests
    # ---------------------------------------------------------
    def test_process_cut_json_with_word_timestamps(self):
        data = {
            "segments": [
                {
                    "start": 10.0,
                    "end": 20.0,
                    "text": "palavra um dois",
                    "words": [
                        {"word": "palavra", "start": 10.0, "end": 12.0},
                        {"word": "um", "start": 12.0, "end": 15.0},
                        {"word": "dois", "start": 15.0, "end": 20.0},
                    ]
                }
            ]
        }
        # Cut from 11.0 to 18.0
        result = process_cut_json_segments(data, start_time=11.0, end_time=18.0)
        self.assertEqual(len(result["segments"]), 1)
        seg = result["segments"][0]
        # Start and end should be relative to cut start (0.0 to 7.0)
        self.assertEqual(seg["start"], 0.0)
        self.assertEqual(seg["end"], 7.0)
        self.assertEqual(len(seg["words"]), 3)

    def test_process_cut_json_synthesizes_words_when_empty(self):
        data = {
            "segments": [
                {
                    "start": 50.0,
                    "end": 60.0,
                    "text": "Segmento sem lista de palavras prévia",
                    "words": []
                }
            ]
        }
        result = process_cut_json_segments(data, start_time=50.0, end_time=60.0)
        self.assertEqual(len(result["segments"]), 1)
        seg = result["segments"][0]
        self.assertEqual(seg["start"], 0.0)
        self.assertEqual(seg["end"], 10.0)
        self.assertGreater(len(seg["words"]), 0)
        self.assertEqual(len(seg["words"]), 6)
        self.assertEqual(seg["words"][0]["word"], "Segmento")

    # ---------------------------------------------------------
    # 3. ASS Subtitle Generation & Time Formatting Tests
    # ---------------------------------------------------------
    def test_format_time_ass_carry_and_boundaries(self):
        # Regular
        self.assertEqual(format_time_ass(0.0), "0:00:00.00")
        self.assertEqual(format_time_ass(65.45), "0:01:05.45")
        self.assertEqual(format_time_ass(3665.99), "1:01:05.99")

        # Centisecond carry: 59.996 should round to 60.00s -> 0:01:00.00
        self.assertEqual(format_time_ass(59.996), "0:01:00.00")

        # Negative protection
        self.assertEqual(format_time_ass(-5.0), "0:00:00.00")

    def test_sanitize_word_for_ass(self):
        # Strips ASS brackets and standard punctuation while preserving Portuguese accents
        word = '{"Olá!",}'
        clean = sanitize_word_for_ass(word, remove_punct=True)
        self.assertEqual(clean, "Olá")

        word_with_accents = 'coração...'
        clean_accents = sanitize_word_for_ass(word_with_accents, remove_punct=True)
        self.assertEqual(clean_accents, "coração")

    def test_generate_ass_from_file(self):
        json_sub_path = os.path.join(self.test_dir, "000_Clip_processed.json")
        ass_sub_path = os.path.join(self.test_dir, "000_Clip_processed.ass")

        data = {
            "segments": [
                {
                    "start": 0.0,
                    "end": 3.0,
                    "text": "Olá mundo viral",
                    "words": [
                        {"word": "Olá", "start": 0.0, "end": 1.0},
                        {"word": "mundo", "start": 1.0, "end": 2.0},
                        {"word": "viral", "start": 2.0, "end": 3.0},
                    ]
                }
            ]
        }
        with open(json_sub_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        generate_ass_from_file(
            input_path=json_sub_path,
            output_path=ass_sub_path,
            project_folder=self.test_dir,
            base_color="&H00FFFFFF&",
            base_size=30,
            highlight_size=35,
            highlight_color="&H0000FF00&",
            words_per_block=3,
            gap_limit=0.5,
            mode="highlight",
            vertical_position=210,
            alignment=2,
            font="Montserrat-Regular",
            outline_color="&H00808080&",
            shadow_color="&H00000000&",
            bold=0,
            italic=0,
            underline=0,
            strikeout=0,
            border_style=2,
            outline_thickness=1.5,
            shadow_size=2,
            uppercase=False,
            remove_punctuation=True
        )

        self.assertTrue(os.path.exists(ass_sub_path))
        with open(ass_sub_path, "r", encoding="utf-8") as f:
            ass_content = f.read()

        self.assertIn("[Script Info]", ass_content)
        self.assertIn("Dialogue: 0,0:00:00.00,0:00:01.00", ass_content)
        self.assertIn("Olá", ass_content)

    # ---------------------------------------------------------
    # 4. FFmpeg Windows Path Escaping Tests
    # ---------------------------------------------------------
    def test_escape_ffmpeg_filter_path(self):
        # Windows drive path with single quote
        win_path = r"C:\Users\User\Videos\It's a clip\sub.ass"
        escaped = escape_ffmpeg_filter_path(win_path)
        # Directory separators must be forward slashes
        self.assertIn("/Users/User/Videos/", escaped)
        self.assertIn(r"C\:", escaped)   # drive colon escaped
        self.assertIn(r"\'", escaped)    # single quote escaped

    # ---------------------------------------------------------
    # 5. FFmpeg Cut & Burn Subtitles Error Handling & Idempotency
    # ---------------------------------------------------------
    @patch('scripts.cut_segments.subprocess.run')
    def test_run_ffmpeg_cut_fallback_on_error(self, mock_subproc):
        # Hardware fails, CPU succeeds
        def mock_run(cmd, *args, **kwargs):
            if "nvenc" in cmd:
                raise subprocess.CalledProcessError(1, cmd, stderr="NVENC session limit reached")
            # For CPU cut, write valid video file to output
            out_file = cmd[-1]
            with open(out_file, "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
                f.write(b"\x00" * 15000)
            return MagicMock(returncode=0)

        mock_subproc.side_effect = mock_run

        out_path = os.path.join(self.test_dir, "cut.mp4")
        success = run_ffmpeg_cut("input.mp4", "0.000", "15.000", out_path)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(out_path))

    @patch('scripts.burn_subtitles.subprocess.run')
    def test_burn_video_file_idempotency_and_cleanup_on_fatal_failure(self, mock_subproc):
        vid_path = os.path.join(self.test_dir, "input.mp4")
        sub_path = os.path.join(self.test_dir, "sub.ass")
        out_path = os.path.join(self.test_dir, "out_subtitled.mp4")

        # 1. Test idempotency: if valid output already exists, skip
        with open(out_path, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
            f.write(b"\x00" * 15000)

        ok, msg = burn_video_file(vid_path, sub_path, out_path)
        self.assertTrue(ok)
        self.assertIn("Already exists", msg)
        self.assertEqual(mock_subproc.call_count, 0)

        # 2. Test cleanup on fatal failure
        os.remove(out_path)
        mock_subproc.side_effect = subprocess.CalledProcessError(1, ["ffmpeg"], stderr="Fatal filter error")
        ok_fail, err = burn_video_file(vid_path, sub_path, out_path)
        self.assertFalse(ok_fail)
        self.assertFalse(os.path.exists(out_path))

    # ---------------------------------------------------------
    # 6. Organize Output Tests
    # ---------------------------------------------------------
    def test_sanitize_filename_windows(self):
        raw = '  Vídeo: 10 Dicas <Top> | Como Fazer? * "Viral"  '
        clean = sanitize_filename(raw)
        self.assertEqual(clean, "Vídeo 10 Dicas Top  Como Fazer  Viral")

    def test_organize_output_with_valid_structure(self):
        project_folder = self.test_dir
        burned_dir = os.path.join(project_folder, "burned_sub")
        os.makedirs(burned_dir, exist_ok=True)

        meta_file = os.path.join(project_folder, "viral_segments.txt")
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump({"segments": [{"title": "Momento Incrível", "start_time": 0, "end_time": 10}]}, f)

        video_file = os.path.join(burned_dir, "000_Momento_Incrível_subtitled.mp4")
        with open(video_file, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
            f.write(b"\x00" * 15000)

        organize(project_folder=project_folder)

        expected_viral_dir = os.path.join(project_folder, "virals_organized", "000_Momento Incrível")
        self.assertTrue(os.path.exists(expected_viral_dir))
        self.assertTrue(os.path.exists(os.path.join(expected_viral_dir, "Momento Incrível.mp4")))
        self.assertTrue(os.path.exists(os.path.join(expected_viral_dir, "Momento Incrível.json")))

if __name__ == '__main__':
    unittest.main()
