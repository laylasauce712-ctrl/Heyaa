import types
import unittest
from unittest.mock import patch

from src.heyaa.backends.pyscenedetect import PySceneDetectBackend
from src.heyaa.backends.shadow_compare import compare_cut_timestamps


class PySceneDetectBackendTests(unittest.TestCase):
    def setUp(self):
        self.backend = PySceneDetectBackend(threshold=27.0, min_scene_len_seconds=0.15)

    def fake_modules(self, *, scenes=None, version="0.7.2", error=None):
        class VideoOpenFailure(Exception):
            pass

        class SeekError(Exception):
            pass

        fake = types.SimpleNamespace(
            __version__=version,
            ContentDetector=lambda **kwargs: ("content-detector", kwargs),
            detect=lambda *args, **kwargs: (
                (_ for _ in ()).throw(error) if error is not None else scenes
            ),
        )
        stream = types.SimpleNamespace(
            VideoOpenFailure=VideoOpenFailure,
            SeekError=SeekError,
        )
        return fake, stream, VideoOpenFailure, SeekError

    def test_detect_maps_scene_starts_after_first_scene_to_cut_events(self):
        scenes = [
            (types.SimpleNamespace(seconds=0.0), types.SimpleNamespace(seconds=1.0)),
            (types.SimpleNamespace(seconds=1.0), types.SimpleNamespace(seconds=2.25)),
            (types.SimpleNamespace(seconds=2.25), types.SimpleNamespace(seconds=4.0)),
        ]
        fake, stream, _, _ = self.fake_modules(scenes=scenes)
        with patch("src.heyaa.backends.pyscenedetect.importlib.import_module",
                   side_effect=[fake, stream]) as importer:
            result = self.backend.detect("clip.mp4", start_seconds=0.0, end_seconds=4.0)
        self.assertEqual(result.status, "ok")
        self.assertEqual([item.timestamp_seconds for item in result.items], [1.0, 2.25])
        self.assertEqual(result.metadata["version"], "0.7.2")
        self.assertEqual(importer.call_count, 2)

    def test_detect_passes_window_and_explicit_detector_parameters(self):
        scenes = [
            (types.SimpleNamespace(seconds=5.0), types.SimpleNamespace(seconds=6.0)),
            (types.SimpleNamespace(seconds=6.0), types.SimpleNamespace(seconds=8.0)),
        ]
        fake, stream, _, _ = self.fake_modules(scenes=scenes)
        with patch("src.heyaa.backends.pyscenedetect.importlib.import_module",
                   side_effect=[fake, stream]), patch.object(fake, "detect", wraps=fake.detect) as detect:
            result = self.backend.detect("clip.mp4", start_seconds=5.0, end_seconds=8.0)
        self.assertEqual(result.status, "ok")
        self.assertEqual([item.timestamp_seconds for item in result.items], [6.0])
        kwargs = detect.call_args.kwargs
        self.assertEqual(kwargs["start_time"], 5.0)
        self.assertEqual(kwargs["end_time"], 8.0)
        self.assertFalse(kwargs["show_progress"])

    def test_missing_optional_dependency_is_unavailable_not_fatal(self):
        with patch(
            "src.heyaa.backends.pyscenedetect.importlib.import_module",
            side_effect=ModuleNotFoundError("No module named scenedetect"),
        ):
            result = self.backend.detect("clip.mp4")
        self.assertEqual(result.status, "unavailable")
        self.assertIn("not installed", result.warnings[0])

    def test_wrong_upstream_version_is_not_used(self):
        fake, stream, _, _ = self.fake_modules(scenes=[], version="0.7.1")
        with patch("src.heyaa.backends.pyscenedetect.importlib.import_module",
                   side_effect=[fake, stream]):
            result = self.backend.detect("clip.mp4")
        self.assertEqual(result.status, "unavailable")
        self.assertIn("Expected PySceneDetect 0.7.2", result.warnings[0])

    def test_expected_decode_failure_is_reported(self):
        fake, stream, VideoOpenFailure, _SeekError = self.fake_modules()
        def fail_detection(*_args, **_kwargs):
            raise VideoOpenFailure("bad video")
        fake.detect = fail_detection
        with patch("src.heyaa.backends.pyscenedetect.importlib.import_module",
                   side_effect=[fake, stream]):
            result = self.backend.detect("clip.mp4")
        self.assertEqual(result.status, "failed")
        self.assertIn("bad video", result.warnings[0])

    def test_invalid_window_is_rejected_before_loading_dependency(self):
        with patch("src.heyaa.backends.pyscenedetect.importlib.import_module") as importer:
            with self.assertRaises(ValueError):
                self.backend.detect("clip.mp4", start_seconds=3.0, end_seconds=2.0)
        importer.assert_not_called()


class SceneShadowCompareTests(unittest.TestCase):
    def test_counts_only_one_to_one_matches_within_tolerance(self):
        report = compare_cut_timestamps(
            [1.0, 2.0, 4.0],
            [1.08, 2.25, 3.95, 8.0],
            tolerance_seconds=0.1,
        )
        self.assertEqual(report["shared_cut_count"], 2)
        self.assertEqual(report["primary_only_count"], 1)
        self.assertEqual(report["shadow_only_count"], 2)
        self.assertEqual(report["matches"][0]["absolute_delta_seconds"], 0.08)
        self.assertEqual(report["interpretation"], "agreement only; neither detector is ground truth")

    def test_no_matches_does_not_divide_by_zero(self):
        report = compare_cut_timestamps([1.0], [3.0])
        self.assertEqual(report["shared_cut_count"], 0)
        self.assertIsNone(report["mean_shared_delta_seconds"])

    def test_rejects_invalid_cut_timestamp(self):
        with self.assertRaises(ValueError):
            compare_cut_timestamps([float("nan")], [1.0])

    def test_rejects_negative_tolerance(self):
        with self.assertRaises(ValueError):
            compare_cut_timestamps([1.0], [1.0], tolerance_seconds=-0.1)


if __name__ == "__main__":
    unittest.main()
