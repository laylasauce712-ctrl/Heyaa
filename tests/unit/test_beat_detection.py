import unittest

from src.agent_director import _estimate_period_frames


class BeatPeriodTests(unittest.TestCase):
    def test_estimates_repeating_100_bpm_onsets(self):
        # 20 ms frames; one pulse every 30 frames is a 0.60 s period / 100 BPM.
        envelope = [0.0] * 600
        for index in range(12, len(envelope), 30):
            envelope[index] = 1.0
        period = _estimate_period_frames(envelope)
        self.assertIsNotNone(period)
        self.assertLessEqual(abs(period - 30), 1)


    def test_estimates_fast_160_bpm_phonk_pulses(self):
        # 19 frames at 20 ms is about 158 BPM, within normal tempo ambiguity.
        envelope = [0.0] * 600
        for index in range(7, len(envelope), 19):
            envelope[index] = 1.0
        period = _estimate_period_frames(envelope)
        self.assertIsNotNone(period)
        self.assertLessEqual(abs(period - 19), 1)

    def test_constant_signal_has_no_reliable_period(self):
        self.assertIsNone(_estimate_period_frames([0.0] * 600))


if __name__ == "__main__":
    unittest.main()
