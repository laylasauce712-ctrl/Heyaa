import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.heyaa.media_sources import MediaSourceError, validate_media_file, validate_youtube_url


class YouTubeUrlTests(unittest.TestCase):
    def test_accepts_watch_shorts_and_short_links(self):
        self.assertEqual(validate_youtube_url("https://www.youtube.com/watch?v=abc123"),
                         "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(validate_youtube_url("https://youtube.com/shorts/abc123"),
                         "https://youtube.com/shorts/abc123")
        self.assertEqual(validate_youtube_url("https://youtu.be/abc123"),
                         "https://youtu.be/abc123")
        self.assertEqual(validate_youtube_url("https://music.youtube.com/watch?v=abc123", "music"),
                         "https://music.youtube.com/watch?v=abc123")

    def test_rejects_non_youtube_hosts_and_non_https(self):
        urls = (
            "http://www.youtube.com/watch?v=abc123",
            "https://example.com/video.mp4",
            "https://youtube.com.evil.example/watch?v=abc123",
            "file:///tmp/video.mp4",
            "https://user:pass@youtube.com/watch?v=abc123",
        )
        for url in urls:
            with self.subTest(url=url), self.assertRaises(MediaSourceError):
                validate_youtube_url(url)

    def test_rejects_playlist_and_non_video_pages(self):
        urls = (
            "https://www.youtube.com/playlist?list=abc",
            "https://www.youtube.com/",
            "https://www.youtube.com/watch",
            "",
        )
        for url in urls:
            with self.subTest(url=url), self.assertRaises(MediaSourceError):
                validate_youtube_url(url)

    def test_validates_required_stream_and_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.mp4"
            path.write_bytes(b"fixture")
            probe = {
                "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
                "format": {"duration": "12.5"},
            }
            with patch("src.heyaa.media_sources._ffprobe", return_value=probe):
                self.assertEqual(validate_media_file(path, "video"), path)
                self.assertEqual(validate_media_file(path, "music"), path)
                self.assertEqual(validate_media_file(path, "reference"), path)

    def test_rejects_missing_expected_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.mp4"
            path.write_bytes(b"fixture")
            probe = {"streams": [{"codec_type": "audio"}], "format": {"duration": "12.5"}}
            with patch("src.heyaa.media_sources._ffprobe", return_value=probe):
                with self.assertRaisesRegex(MediaSourceError, "no video stream"):
                    validate_media_file(path, "video")
                with self.assertRaisesRegex(MediaSourceError, "no audio stream"):
                    validate_media_file(path, "music")

    def test_rejects_missing_or_empty_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(MediaSourceError):
                validate_media_file(Path(directory) / "missing.mp4", "video")
            empty = Path(directory) / "empty.mp4"
            empty.touch()
            with self.assertRaises(MediaSourceError):
                validate_media_file(empty, "video")


if __name__ == "__main__":
    unittest.main()
