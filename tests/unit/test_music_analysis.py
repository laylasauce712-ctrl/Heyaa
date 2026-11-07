import unittest

from src.heyaa.music_analysis import choose_drop_candidate


class DropTransitionTests(unittest.TestCase):
    def test_sustained_low_band_rise_qualifies_as_drop_candidate(self):
        values = [0.10] * 500 + [0.80] * 500
        result = choose_drop_candidate(values, [(0.9, 10.0)], hop_seconds=0.02)
        self.assertIsNotNone(result)
        self.assertEqual(result["timestamp_seconds"], 10.0)
        self.assertGreaterEqual(result["confidence"], 0.62)
        self.assertGreater(result["rise_ratio"], 1.35)
        self.assertFalse(result["semantic_drop_understanding"])

    def test_single_transient_does_not_qualify(self):
        values = [0.20] * 1000
        values[500] = 1.0
        result = choose_drop_candidate(values, [(0.9, 10.0)], hop_seconds=0.02)
        self.assertIsNone(result)

    def test_no_candidate_or_short_window_returns_none(self):
        self.assertIsNone(choose_drop_candidate([0.2] * 100, []))
        self.assertIsNone(choose_drop_candidate([0.2] * 10, [(1.0, 0.1)]))

    def test_malformed_nonfinite_energy_is_ignored(self):
        values = [0.1] * 500 + [0.8] * 500
        values[20] = float("nan")
        result = choose_drop_candidate(values, [(0.9, 10.0)])
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
