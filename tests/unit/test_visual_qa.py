import unittest

from src.heyaa.visual_qa import _percentile, analyze_visual_quality


class VisualQualityTests(unittest.TestCase):
    def test_percentile_uses_ordered_values(self):
        self.assertEqual(_percentile([100.0, 1.0, 10.0], 0.5), 10.0)

    def test_invalid_duration_is_reported_without_calling_ffmpeg(self):
        result = analyze_visual_quality("unused.mp4", float("nan"))
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("settings_out_of_range", result["measurement_errors"])
        self.assertFalse(result["aesthetic_quality_assessed"])

    def test_missing_path_is_reported(self):
        result = analyze_visual_quality("", 20.0)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("media_path_invalid", result["measurement_errors"])


if __name__ == "__main__":
    unittest.main()
