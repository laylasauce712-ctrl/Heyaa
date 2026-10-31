import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.heyaa.backends.beat_this import BeatThisBackend


class BeatThisBackendTests(unittest.TestCase):
    def make_audio(self, root):
        path = Path(root) / "music.mp3"
        path.write_bytes(b"fixture")
        return str(path)

    def set_up_runtime(self, beats=(0.5, 1.0, 1.5), downbeats=(0.5, 1.5)):
        fake_torch = SimpleNamespace(__version__="2.fake")
        fake_audio = SimpleNamespace(__version__="2.fake")
        fake_inference = SimpleNamespace(
            File2Beats=lambda **kwargs: (lambda path: (beats, downbeats))
        )
        return fake_torch, fake_audio, fake_inference

    def fake_ffmpeg(self, command, **kwargs):
        Path(command[-1]).write_bytes(b"wav-fixture")
        return SimpleNamespace(returncode=0, stderr="")

    def test_maps_beats_and_downbeats_to_separate_event_kinds(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.make_audio(temp)
            runtime = self.set_up_runtime()
            with (
                patch("src.heyaa.backends.beat_this.metadata.version", return_value="1.1.0"),
                patch("src.heyaa.backends.beat_this.importlib.import_module",
                      side_effect=runtime),
                patch("src.heyaa.backends.beat_this.subprocess.run", side_effect=self.fake_ffmpeg),
            ):
                result = BeatThisBackend().analyze(source, duration_seconds=20.0)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metadata["beat_count"], 3)
        self.assertEqual(result.metadata["downbeat_count"], 2)
        self.assertEqual([e.kind for e in result.items].count("beat"), 3)
        self.assertEqual([e.kind for e in result.items].count("downbeat"), 2)
        self.assertEqual(result.metadata["checkpoint"], "small0")
        self.assertEqual(result.metadata["device"], "cpu")

    def test_missing_distribution_reports_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.make_audio(temp)
            from importlib.metadata import PackageNotFoundError
            with patch(
                "src.heyaa.backends.beat_this.metadata.version",
                side_effect=PackageNotFoundError("beat-this"),
            ):
                result = BeatThisBackend().analyze(source)
        self.assertEqual(result.status, "unavailable")

    def test_unsupported_version_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.make_audio(temp)
            with (
                patch("src.heyaa.backends.beat_this.metadata.version", return_value="9.9.9"),
                patch("src.heyaa.backends.beat_this.importlib.import_module") as importer,
            ):
                result = BeatThisBackend().analyze(source)
        self.assertEqual(result.status, "unavailable")
        importer.assert_not_called()

    def test_missing_source_fails_without_loading_runtime(self):
        with patch("src.heyaa.backends.beat_this.importlib.import_module") as importer:
            result = BeatThisBackend().analyze("/missing/music.mp3")
        self.assertEqual(result.status, "failed")
        importer.assert_not_called()

    def test_invalid_duration_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.make_audio(temp)
            with self.assertRaises(ValueError):
                BeatThisBackend().analyze(source, duration_seconds=0.0)

    def test_rejects_invalid_model_timestamps(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.make_audio(temp)
            runtime = self.set_up_runtime(beats=(float("nan"),), downbeats=())
            with (
                patch("src.heyaa.backends.beat_this.metadata.version", return_value="1.1.0"),
                patch("src.heyaa.backends.beat_this.importlib.import_module",
                      side_effect=runtime),
                patch("src.heyaa.backends.beat_this.subprocess.run", side_effect=self.fake_ffmpeg),
            ):
                with self.assertRaises(ValueError):
                    BeatThisBackend().analyze(source, duration_seconds=20.0)


if __name__ == "__main__":
    unittest.main()
