import sys
import types
import unittest
from unittest.mock import patch

from src.heyaa.backends import (
    NormalizedBox,
    SubjectDetection,
    SubjectFrame,
)
from src.heyaa.backends import norfair as norfair_module
from src.heyaa.backends.norfair import NorfairAssociator


class FakeDetection:
    def __init__(self, points, scores=None, data=None, label=None):
        self.points = points
        self.scores = scores
        self.data = data
        self.label = label


class FakeTracker:
    def __init__(self, **kwargs):
        self.last = None

    def update(self, detections=None):
        if detections:
            self.last = detections[0]
        if self.last is None:
            return []
        frame_index = self.last.data["frame_index"]
        return [types.SimpleNamespace(
            id=17,
            last_detection=self.last,
            age=frame_index,
            estimate=self.last.points,
        )]


class NorfairAssociatorTests(unittest.TestCase):
    def setUp(self):
        self.backend = NorfairAssociator()
        self.frames = [
            SubjectFrame(
                timestamp_seconds=float(index),
                detections=(
                    SubjectDetection(
                        timestamp_seconds=float(index),
                        box=NormalizedBox(0.2 + index * 0.01, 0.2, 0.2, 0.4),
                        confidence=0.9,
                        appearance=(1.0, 0.0, 0.0, 1.0),
                    ),
                ),
            )
            for index in range(4)
        ]

    def test_no_detections_preserves_insufficient_evidence_without_importing_norfair(self):
        frames = [SubjectFrame(0.0, ())]
        with patch.object(norfair_module.metadata, "version") as version:
            result = self.backend.associate(frames)
        self.assertEqual(result.status, "insufficient_evidence")
        version.assert_not_called()

    def test_missing_norfair_distribution_is_unavailable(self):
        with patch.object(
            norfair_module.metadata,
            "version",
            side_effect=norfair_module.metadata.PackageNotFoundError("norfair"),
        ):
            result = self.backend.associate(self.frames)
        self.assertEqual(result.status, "unavailable")

    def test_unsupported_version_is_not_imported(self):
        with (
            patch.object(norfair_module.metadata, "version", return_value="9.9.9"),
            patch.dict(sys.modules, {"norfair": None}),
        ):
            result = self.backend.associate(self.frames)
        self.assertEqual(result.status, "unavailable")
        self.assertIn("Expected Norfair 2.3.0", result.warnings[0])

    def test_out_of_order_frame_timestamps_are_rejected_before_import(self):
        frames = [SubjectFrame(2.0), SubjectFrame(1.0)]
        with patch.object(norfair_module.metadata, "version") as version:
            with self.assertRaises(ValueError):
                self.backend.associate(frames)
        version.assert_not_called()

    def test_appearance_signature_size_is_bounded(self):
        frames = [SubjectFrame(0.0, (
            SubjectDetection(
                0.0, NormalizedBox(0.1, 0.1, 0.2, 0.3),
                appearance=tuple([0.0] * 257),
            ),
        ))]
        with patch.object(norfair_module.metadata, "version") as version:
            with self.assertRaises(ValueError):
                self.backend.associate(frames)
        version.assert_not_called()

    def test_maps_norfair_track_ids_to_normalized_subject_observations(self):
        fake_norfair = types.ModuleType("norfair")
        fake_norfair.Detection = FakeDetection
        fake_norfair.Tracker = FakeTracker
        with (
            patch.object(norfair_module.metadata, "version", return_value="2.3.0"),
            patch.dict(sys.modules, {"norfair": fake_norfair}),
        ):
            result = self.backend.associate(self.frames)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.backend_id, "norfair.hog-association.2.3.0")
        self.assertEqual(len(result.items), 4)
        self.assertEqual({item.track_id for item in result.items}, {"17"})
        self.assertAlmostEqual(result.items[0].box.x, 0.2)
        self.assertEqual(result.metadata["track_count"], 1)
        self.assertEqual(result.metadata["version"], "2.3.0")


class SubjectDetectionContractTests(unittest.TestCase):
    def test_subject_detection_rejects_nonfinite_appearance(self):
        with self.assertRaises(ValueError):
            SubjectDetection(
                0.0, NormalizedBox(0.1, 0.1, 0.2, 0.3),
                appearance=(float("nan"),),
            )

    def test_subject_frame_accepts_only_subject_detections(self):
        with self.assertRaises(ValueError):
            SubjectFrame(0.0, detections=({"x": 1},))


if __name__ == "__main__":
    unittest.main()
