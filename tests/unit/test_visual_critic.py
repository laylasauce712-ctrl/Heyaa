import unittest

from src.heyaa.agents import render_critic


class VisualCriticTests(unittest.TestCase):
    def _metrics(self, visual_quality):
        return {
            "black_segments": [],
            "duration_seconds": 20.0,
            "mean_volume_db": -18.0,
            "max_volume_db": -2.0,
            "true_peak_dbfs": -1.2,
            "audio_silent": False,
            "visual_quality": visual_quality,
        }

    def test_visual_warning_is_reported_as_review_not_block(self):
        result = render_critic(self._metrics({
            "status": "needs_review",
            "warnings": ["Most sampled frames are very dark."],
        }))
        self.assertEqual(result.status, "needs_review")
        self.assertIn("Most sampled frames are very dark.", result.findings)
        self.assertFalse(result.evidence["aesthetic_quality_assessed"])

    def test_unavailable_visual_sample_is_visible_but_not_blocking(self):
        result = render_critic(self._metrics({
            "status": "unavailable",
            "warnings": [],
            "measurement_errors": ["visual_metadata_filters_unavailable"],
        }))
        self.assertEqual(result.status, "needs_review")
        self.assertTrue(any("visual QA was unavailable" in item for item in result.findings))


if __name__ == "__main__":
    unittest.main()
