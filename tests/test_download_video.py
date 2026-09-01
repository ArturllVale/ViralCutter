import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.download_video import (
    DownloadErrorCategory,
    classify_ytdlp_error,
    sanitize_log_message,
    resolve_cookie_config,
    build_ydl_options,
    validate_video_file,
    cleanup_corrupted_or_temp_files,
    download,
    sanitize_filename
)

class TestDownloadVideo(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    # ---------------------------------------------------------
    # 1. Error Classification Tests
    # ---------------------------------------------------------
    def test_classify_invalid_url(self):
        err = Exception("ERROR: 'not_a_url' is not a valid URL. Set --default-search 'gvsearch' to search")
        category, is_transient, msg = classify_ytdlp_error(err)
        self.assertEqual(category, DownloadErrorCategory.INVALID_URL)
        self.assertFalse(is_transient)

    def test_classify_private_unavailable_video(self):
        err1 = Exception("ERROR: Private video. Sign in if you've been granted access to this video")
        category, is_transient, msg = classify_ytdlp_error(err1)
        self.assertEqual(category, DownloadErrorCategory.UNAVAILABLE_OR_PRIVATE)
        self.assertFalse(is_transient)

        err2 = Exception("ERROR: [youtube] Video unavailable. This video has been removed by the uploader")
        category2, is_transient2, _ = classify_ytdlp_error(err2)
        self.assertEqual(category2, DownloadErrorCategory.UNAVAILABLE_OR_PRIVATE)
        self.assertFalse(is_transient2)

    def test_classify_anti_bot_and_auth(self):
        err_bot = Exception("ERROR: Sign in to confirm you're not a bot. This helps protect our community.")
        category, is_transient, _ = classify_ytdlp_error(err_bot)
        self.assertEqual(category, DownloadErrorCategory.ANTI_BOT)
        self.assertFalse(is_transient)

        err_auth = Exception("ERROR: This video requires authentication. Sign in to view.")
        category_auth, is_transient_auth, _ = classify_ytdlp_error(err_auth)
        self.assertEqual(category_auth, DownloadErrorCategory.AUTHENTICATION_REQUIRED)
        self.assertFalse(is_transient_auth)

    def test_classify_rate_limit(self):
        err = Exception("HTTP Error 429: Too Many Requests")
        category, is_transient, _ = classify_ytdlp_error(err)
        self.assertEqual(category, DownloadErrorCategory.RATE_LIMIT)
        self.assertTrue(is_transient)

    def test_classify_transient_network_errors(self):
        transient_errors = [
            "Connection reset by peer",
            "RemoteDisconnected('Remote end closed connection without response')",
            "timed out",
            "HTTP Error 503: Service Unavailable",
            "HTTP Error 502: Bad Gateway",
            "Failed to resolve 'www.youtube.com'",
            "IncompleteRead(0 bytes read)"
        ]
        for err_text in transient_errors:
            cat, is_transient, _ = classify_ytdlp_error(Exception(err_text))
            self.assertEqual(cat, DownloadErrorCategory.NETWORK_TRANSIENT, f"Failed on {err_text}")
            self.assertTrue(is_transient, f"Expected transient for {err_text}")

    # ---------------------------------------------------------
    # 2. Log Sanitization Tests
    # ---------------------------------------------------------
    def test_sanitize_log_message_strips_sensitive_data(self):
        raw_msg = "Error using cookies: SID=AbCdEf123456; HSID=789xyz; with Bearer token_secret_12345"
        clean = sanitize_log_message(raw_msg)
        self.assertNotIn("AbCdEf123456", clean)
        self.assertNotIn("token_secret_12345", clean)
        self.assertIn("***REDACTED***", clean)

    def test_sanitize_filename(self):
        raw = 'Vídeo Especial: Como Criar "Shorts" & Reels? 😱 <PRO>'
        clean = sanitize_filename(raw)
        self.assertNotIn('"', clean)
        self.assertNotIn(':', clean)
        self.assertNotIn('?', clean)
        self.assertNotIn('<', clean)
        self.assertNotIn('>', clean)

    # ---------------------------------------------------------
    # 3. Cookie Configuration Resolution Tests
    # ---------------------------------------------------------
    def test_resolve_cookie_config_priority(self):
        # 1. Explicit arguments
        b, f = resolve_cookie_config(cookies_from_browser="Firefox")
        self.assertEqual(b, "firefox")
        self.assertIsNone(f)

        b, f = resolve_cookie_config(cookiefile="/path/to/cookies.txt")
        self.assertIsNone(b)
        self.assertEqual(f, "/path/to/cookies.txt")

        # 2. Environment variables fallback
        with patch.dict(os.environ, {"VIRALCUTTER_COOKIES_FROM_BROWSER": "brave"}):
            b, f = resolve_cookie_config()
            self.assertEqual(b, "brave")
            self.assertIsNone(f)

        # 3. None when not configured
        with patch.dict(os.environ, {}, clear=True):
            b, f = resolve_cookie_config(config_path="/non/existent/config.json")
            self.assertIsNone(b)
            self.assertIsNone(f)

    # ---------------------------------------------------------
    # 4. YDL Options Builder Tests
    # ---------------------------------------------------------
    def test_build_ydl_options_cookies_and_subs(self):
        opts = build_ydl_options(
            output_path_base="/tmp/input",
            selected_format="bestvideo+bestaudio/best",
            download_subs=True,
            cookies_from_browser="chrome",
            quiet=True
        )
        self.assertEqual(opts['cookiesfrombrowser'], ('chrome',))
        self.assertTrue(opts['writesubtitles'])
        self.assertTrue(opts['quiet'])
        self.assertEqual(opts['outtmpl'], "/tmp/input")

        opts_file = build_ydl_options(
            output_path_base="/tmp/input",
            download_subs=False,
            cookiefile="/tmp/cookies.txt"
        )
        self.assertEqual(opts_file['cookiefile'], "/tmp/cookies.txt")
        self.assertFalse(opts_file['writesubtitles'])

    # ---------------------------------------------------------
    # 5. File Validation and Cleanup Tests
    # ---------------------------------------------------------
    def test_validate_video_file_valid_mp4(self):
        valid_file = os.path.join(self.test_dir, "valid.mp4")
        # Write valid MP4 header (ftyp box) + padding > 10KB
        with open(valid_file, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
            f.write(b"\x00" * 12000)
        self.assertTrue(validate_video_file(valid_file))

    def test_validate_video_file_corrupt_or_empty(self):
        empty_file = os.path.join(self.test_dir, "empty.mp4")
        with open(empty_file, "wb") as f:
            f.write(b"")
        self.assertFalse(validate_video_file(empty_file))

        corrupt_file = os.path.join(self.test_dir, "corrupt.mp4")
        with open(corrupt_file, "wb") as f:
            f.write(b"NOT_A_VIDEO_STREAM")
        self.assertFalse(validate_video_file(corrupt_file))

    def test_cleanup_corrupted_or_temp_files(self):
        base = os.path.join(self.test_dir, "input")
        temp1 = os.path.join(self.test_dir, "input.temp.mp4")
        temp2 = os.path.join(self.test_dir, "input.part")
        keep = os.path.join(self.test_dir, "other.txt")
        
        with open(temp1, "w") as f: f.write("temp")
        with open(temp2, "w") as f: f.write("part")
        with open(keep, "w") as f: f.write("keep")

        cleanup_corrupted_or_temp_files(base)
        self.assertFalse(os.path.exists(temp1))
        self.assertFalse(os.path.exists(temp2))
        self.assertTrue(os.path.exists(keep))

    # ---------------------------------------------------------
    # 6. End-to-End Download Flow Mock Tests
    # ---------------------------------------------------------
    @patch('scripts.download_video.yt_dlp.YoutubeDL')
    def test_download_success(self, mock_ydl_class):
        mock_ydl_instance = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = {"title": "Test Video Title"}

        def side_effect_download(urls):
            # Create the valid video file as yt-dlp would
            video_path = os.path.join(self.test_dir, "Test Video Title", "input.mp4")
            os.makedirs(os.path.dirname(video_path), exist_ok=True)
            with open(video_path, "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
                f.write(b"\x00" * 15000)

        mock_ydl_instance.download.side_effect = side_effect_download

        final_path, proj_folder = download(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            base_root=self.test_dir,
            download_subs=False,
            cookies_from_browser="firefox"
        )

        self.assertTrue(os.path.exists(final_path))
        self.assertIn("Test Video Title", proj_folder)

    @patch('scripts.download_video.yt_dlp.YoutubeDL')
    def test_download_fatal_error_stops_immediately(self, mock_ydl_class):
        mock_ydl_instance = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.side_effect = Exception("ERROR: 'invalid' is not a valid URL")

        with self.assertRaises(RuntimeError) as ctx:
            download(
                url="invalid_url",
                base_root=self.test_dir,
                max_retries=3
            )
        self.assertIn("URL inválida", str(ctx.exception))
        # Should not exhaust 3 retries for invalid URL
        self.assertEqual(mock_ydl_instance.extract_info.call_count, 1)

    @patch('scripts.download_video.time.sleep', return_value=None)
    @patch('scripts.download_video.yt_dlp.YoutubeDL')
    def test_download_retry_on_transient_error(self, mock_ydl_class, mock_sleep):
        mock_ydl_instance = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl_instance

        # Fail with connection reset on first try, succeed on second
        mock_ydl_instance.extract_info.side_effect = [
            Exception("Connection reset by peer"),
            {"title": "Recovered Title"}
        ]

        def side_effect_download(urls):
            video_path = os.path.join(self.test_dir, "Recovered Title", "input.mp4")
            os.makedirs(os.path.dirname(video_path), exist_ok=True)
            with open(video_path, "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
                f.write(b"\x00" * 15000)

        mock_ydl_instance.download.side_effect = side_effect_download

        final_path, proj_folder = download(
            url="https://www.youtube.com/watch?v=valid",
            base_root=self.test_dir,
            download_subs=False,
            max_retries=3
        )

        self.assertEqual(mock_ydl_instance.extract_info.call_count, 2)
        self.assertTrue(os.path.exists(final_path))

    @patch('scripts.download_video.time.sleep', return_value=None)
    @patch('scripts.download_video.yt_dlp.YoutubeDL')
    def test_download_subtitle_failure_fallback(self, mock_ydl_class, mock_sleep):
        mock_ydl_instance = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = {"title": "Sub Fallback Test"}

        attempts = {"count": 0}
        def side_effect_download(urls):
            attempts["count"] += 1
            if attempts["count"] == 1:
                # First attempt fails with subtitle rate limit
                raise Exception("Unable to download video subtitles: HTTP Error 429: Too Many Requests")
            else:
                # Second attempt succeeds without subtitles
                video_path = os.path.join(self.test_dir, "Sub Fallback Test", "input.mp4")
                os.makedirs(os.path.dirname(video_path), exist_ok=True)
                with open(video_path, "wb") as f:
                    f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
                    f.write(b"\x00" * 15000)

        mock_ydl_instance.download.side_effect = side_effect_download

        final_path, proj_folder = download(
            url="https://www.youtube.com/watch?v=subs_fail",
            base_root=self.test_dir,
            download_subs=True,
            max_retries=2
        )

        self.assertTrue(os.path.exists(final_path))
        self.assertEqual(attempts["count"], 2)

if __name__ == '__main__':
    unittest.main()
