import unittest

from src.heyaa.subject_tracking import (
    _associate_detections,
    _pick_dominant_track,
    subject_observation_near,
)


def detection(center_x, center_y=0.55, height_ratio=0.7, histogram=None, score=0.8):
    return {
        "center_x": center_x,
        "center_y": center_y,
        "height_ratio": height_ratio,
        "color_histogram": histogram or [1.0, 0.0, 0.0],
        "detector_score": score,
    }


class SubjectTrackingTests(unittest.TestCase):
    def test_repeated_appearance_observations_form_one_track(self):
        frames = [
            {"time_seconds": 10.0, "detections": [detection(0.45)]},
            {"time_seconds": 10.75, "detections": [detection(0.47)]},
            {"time_seconds": 11.5, "detections": [detection(0.49)]},
            {"time_seconds": 12.25, "detections": [detection(0.50)]},
        ]
        tracks = _associate_detections(frames)
        dominant = _pick_dominant_track(tracks)
        self.assertIsNotNone(dominant)
        self.assertEqual(len(dominant["observations"]), 4)
        self.assertAlmostEqual(dominant["span_seconds"], 2.25)
        self.assertGreater(dominant["track_quality_proxy"], 0.0)

    def test_color_and_location_changes_split_unrelated_people(self):
        frames = [
            {"time_seconds": 1.0, "detections": [detection(0.2, histogram=[1.0, 0.0, 0.0])]},
            {"time_seconds": 1.75, "detections": [detection(0.22, histogram=[1.0, 0.0, 0.0])]},
            {"time_seconds": 2.5, "detections": [detection(0.8, histogram=[0.0, 0.0, 1.0])]},
            {"time_seconds": 3.25, "detections": [detection(0.82, histogram=[0.0, 0.0, 1.0])]},
        ]
        tracks = _associate_detections(frames)
        self.assertEqual(sorted(len(track["observations"]) for track in tracks), [2, 2])
        self.assertIsNone(_pick_dominant_track(tracks))

    def test_nearest_subject_observation_is_bounded_by_time(self):
        observations = [
            {"time_seconds": 10.0, "center_x": 0.25, "center_y": 0.5},
            {"time_seconds": 11.0, "center_x": 0.6, "center_y": 0.5},
        ]
        nearest = subject_observation_near(observations, 10.8, max_distance_seconds=0.5)
        self.assertEqual(nearest, observations[1])
        self.assertIsNone(subject_observation_near(observations, 14.0, max_distance_seconds=1.0))


if __name__ == "__main__":
    unittest.main()
