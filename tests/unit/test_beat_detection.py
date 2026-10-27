import unittest

from src.agent_director import _estimate_period_frames, extend_looped_beats


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

    def test_looped_music_repeats_measured_beat_candidates_to_edit_end(self):
        beats = extend_looped_beats([0.5, 1.0, 1.5], music_duration=2.0, limit=5.0, loop_enabled=True)
        self.assertEqual(beats, [0.5, 1.0, 1.5, 2.5, 3.0, 3.5, 4.5])

    def test_non_looped_music_does_not_invent_later_beat_candidates(self):
        beats = extend_looped_beats([0.5, 1.0, 1.5], music_duration=2.0, limit=5.0, loop_enabled=False)
        self.assertEqual(beats, [0.5, 1.0, 1.5])

    def test_looped_music_ignores_source_candidates_beyond_one_cycle(self):
        beats = extend_looped_beats([0.5, 1.0, 1.5, 4.2], music_duration=2.0, limit=5.0, loop_enabled=True)
        self.assertEqual(beats, [0.5, 1.0, 1.5, 2.5, 3.0, 3.5, 4.5])

    def test_constant_signal_has_no_reliable_period(self):
        self.assertIsNone(_estimate_period_frames([0.0] * 600))


if __name__ == "__main__":
    unittest.main()
