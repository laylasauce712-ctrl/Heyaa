import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from src.heyaa.media_sources import (
    MediaSourceError,
    download_media_source,
    download_youtube,
    SOURCE_VIDEO_FORMAT,
    REFERENCE_VIDEO_FORMAT,
    VIDEO_DOWNLOAD_TIMEOUT_SECONDS,
    REFERENCE_DOWNLOAD_TIMEOUT_SECONDS,
    MUSIC_DOWNLOAD_TIMEOUT_SECONDS,
    validate_media_file,
    validate_media_url,
    validate_youtube_url,
    prepare_media_sources,
)


class YouTubeUrlTests(unittest.TestCase):
    def test_reference_video_does_not_replace_or_supply_the_music_track(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video_path = root / "source.mp4"
            music_path = root / "phonk.mp3"
            reference_path = root / "reference.mp4"

            def fake_download(url, target_path, kind):
                return Path(target_path)

            with patch("src.heyaa.media_sources.download_media_source", side_effect=fake_download) as downloader, \\
                 patch("src.heyaa.media_sources.validate_media_file") as validator, \\
                 patch("src.heyaa.media_sources.extract_reference_audio") as extract_audio:
                result = prepare_media_sources(
                    video_url="https://media.example/source.mp4",
                    music_url=None,
                    reference_url="https://media.example/reference.mp4",
                    video_path=video_path,
                    music_path=music_path,
                    reference_path=reference_path,
                )

            self.assertEqual(result, (str(video_path), str(music_path), str(reference_path)))
            downloaded_kinds = [call.args[2] for call in downloader.call_args_list]
            self.assertEqual(downloaded_kinds, ["video", "reference"])
            extract_audio.assert_not_called()
            self.assertTrue(any(call.args == (music_path, "music") for call in validator.call_args_list))

    def test_explicit_music_url_stays_separate_when_reference_is_supplied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video_path = root / "source.mp4"
            music_path = root / "phonk.mp3"
            reference_path = root / "reference.mp4"

            def fake_download(url, target_path, kind):
                return Path(target_path)

            with patch("src.heyaa.media_sources.download_media_source", side_effect=fake_download) as downloader, \\
                 patch("src.heyaa.media_sources.validate_media_file"), \\
                 patch("src.heyaa.media_sources.extract_reference_audio") as extract_audio:
                prepare_media_sources(
                    video_url="https://media.example/source.mp4",
                    music_url="https://music.example/phonk.mp3",
                    reference_url="https://media.example/reference.mp4",
                    video_path=video_path,
                    music_path=music_path,
                    reference_path=reference_path,
                )

            downloaded = [(call.args[0], call.args[2]) for call in downloader.call_args_list]
            self.assertIn(("https://music.example/phonk.mp3", "music"), downloaded)
            self.assertEqual([kind for _, kind in downloaded], ["video", "reference", "music"])
            extract_audio.assert_not_called()

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
            self.assertEqual(runner.call_args.kwargs["timeout"], VIDEO_DOWNLOAD_TIMEOUT_SECONDS)
            self.assertEqual(command[command.index("-f") + 1], SOURCE_VIDEO_FORMAT)
            report_path = input_dir / ".test_video.video.yt-dlp-path.txt"
            self.assertFalse(report_path.exists())

    def test_reference_download_is_capped_at_720p_and_has_15_minute_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            input_dir.mkdir()
            target = input_dir / "reference.mp4"
            target.write_bytes(b"valid fixture bytes")

            def fake_run(command, **kwargs):
                report_path = Path(command[command.index("--print-to-file") + 2])
                report_path.write_text(str(target), encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with patch("src.heyaa.media_sources.shutil.which", return_value="/usr/bin/yt-dlp"), \
                 patch("src.heyaa.media_sources.subprocess.run", side_effect=fake_run) as runner:
                result = download_youtube(
                    "https://www.youtube.com/shorts/abc123", target, "reference"
                )

            self.assertEqual(result, target.resolve())
            command = runner.call_args.args[0]
            self.assertEqual(command[command.index("-f") + 1], REFERENCE_VIDEO_FORMAT)
            self.assertEqual(runner.call_args.kwargs["timeout"], REFERENCE_DOWNLOAD_TIMEOUT_SECONDS)

    def test_music_download_has_bounded_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            input_dir.mkdir()
            target = input_dir / "phonk.mp3"
            target.write_bytes(b"valid fixture bytes")

            def fake_run(command, **kwargs):
                report_path = Path(command[command.index("--print-to-file") + 2])
                report_path.write_text(str(target), encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with patch("src.heyaa.media_sources.shutil.which", return_value="/usr/bin/yt-dlp"), \
                 patch("src.heyaa.media_sources.subprocess.run", side_effect=fake_run) as runner:
                result = download_youtube(
                    "https://www.youtube.com/watch?v=abc123", target, "music"
                )

            self.assertEqual(result, target.resolve())
            command = runner.call_args.args[0]
            self.assertEqual(command[command.index("-f") + 1], "ba/b")
            self.assertEqual(runner.call_args.kwargs["timeout"], MUSIC_DOWNLOAD_TIMEOUT_SECONDS)

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
