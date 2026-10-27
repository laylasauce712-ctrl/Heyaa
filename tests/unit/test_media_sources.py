import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from src.heyaa.media_sources import (
    MediaSourceError,
    download_media_source,
    download_youtube,
    validate_media_file,
    validate_media_url,
    validate_youtube_url,
)


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

    def test_accepts_direct_https_media_links(self):
        url = "https://cdn.example.org/media/clip"
        self.assertEqual(validate_media_url(url, "video"), url)
        self.assertEqual(
            validate_media_url("https://www.youtube.com/watch?v=abc123", "video"),
            "https://www.youtube.com/watch?v=abc123",
        )

    def test_rejects_unsafe_or_non_media_direct_urls(self):
        for url in ("http://cdn.example.org/clip.mp4", "https://user:pass@cdn.example.org/clip.mp4",
                    "https://cdn.example.org/"):
            with self.subTest(url=url), self.assertRaises(MediaSourceError):
                validate_media_url(url, "video")

    def test_routes_youtube_and_direct_links_to_their_handlers(self):
        with patch("src.heyaa.media_sources.download_youtube", return_value=Path("yt.mp4")) as yt, \
             patch("src.heyaa.media_sources.download_direct_https", return_value=Path("direct.mp4")) as direct:
            self.assertEqual(download_media_source("https://youtu.be/abc", "out.mp4", "video"), Path("yt.mp4"))
            self.assertEqual(download_media_source("https://cdn.example.org/clip.mp4", "out.mp4", "video"),
                             Path("direct.mp4"))
            yt.assert_called_once()
            direct.assert_called_once()

    def test_youtube_downloader_streams_progress_and_reads_reported_path(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            input_dir.mkdir()
            target = input_dir / "test_video.mp4"
            downloaded = input_dir / "test_video.mp4"
            downloaded.write_bytes(b"valid fixture bytes")

            def fake_run(command, **kwargs):
                report_path = Path(command[command.index("--print-to-file") + 2])
                report_path.write_text(str(downloaded), encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with patch("src.heyaa.media_sources.shutil.which", return_value="/usr/bin/yt-dlp"), \
                 patch("src.heyaa.media_sources.subprocess.run", side_effect=fake_run) as runner:
                result = download_youtube(
                    "https://www.youtube.com/watch?v=abc123", target, "video"
                )

            self.assertEqual(result, downloaded.resolve())
            command = runner.call_args.args[0]
            self.assertIn("--progress", command)
            self.assertIn("--newline", command)
            self.assertIn("--force-ipv4", command)
            self.assertIn("--no-playlist", command)
            self.assertNotIn("--quiet", command)
            self.assertNotIn("--no-progress", command)
            self.assertNotIn("capture_output", runner.call_args.kwargs)
            report_path = input_dir / ".test_video.video.yt-dlp-path.txt"
            self.assertFalse(report_path.exists())

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
            audio_only = {"streams": [{"codec_type": "audio"}], "format": {"duration": "12.5"}}
            video_only = {"streams": [{"codec_type": "video"}], "format": {"duration": "12.5"}}
            with patch("src.heyaa.media_sources._ffprobe", return_value=audio_only):
                with self.assertRaisesRegex(MediaSourceError, "no video stream"):
                    validate_media_file(path, "video")
            with patch("src.heyaa.media_sources._ffprobe", return_value=video_only):
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
