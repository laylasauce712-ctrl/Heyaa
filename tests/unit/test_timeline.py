import unittest
from src.heyaa.edl.timeline import frames_to_seconds, seconds_to_frames, timeline_end_frame
from src.heyaa.edl.schema import EDLValidationError

class TimelineTests(unittest.TestCase):
    def test_rational_fps(self):
        self.assertAlmostEqual(frames_to_seconds(30,30),1.0)
        self.assertAlmostEqual(frames_to_seconds(30,30000,1001),1.001)
    def test_rounding(self):
        self.assertEqual(seconds_to_frames(0.5,30),15)
        self.assertEqual(seconds_to_frames(0.01,30),0)
    def test_bad_values(self):
        with self.assertRaises(EDLValidationError): frames_to_seconds(True,30)
        with self.assertRaises(EDLValidationError): seconds_to_frames(-1,30)
    def test_end_frame(self):
        self.assertEqual(timeline_end_frame([{"start_f":0,"dur_f":12},{"start_f":12,"dur_f":3}]),15)
        self.assertEqual(timeline_end_frame([]),0)

if __name__ == "__main__": unittest.main()
