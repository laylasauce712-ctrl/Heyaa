"""Optional Norfair association backend for existing HOG detections.

Norfair receives detector observations already produced by Heyaa. It does not
read video, run a detector, recognize identity, or change the authoritative
HOG/EDL decision path.
"""
from __future__ import annotations

from importlib import metadata
import math
from typing import Sequence

from .contracts import BackendResult, SubjectAssociator, SubjectFrame, SubjectObservation

SUPPORTED_VERSION = "2.3.0"
MAX_FRAMES = 1200
MAX_DETECTIONS_PER_FRAME = 64
MAX_APPEARANCE_VALUES = 256
MAX_TRACK_GAP_SECONDS = 2.2


class NorfairAssociator:
    """Kalman-based association using center motion and HOG color histograms."""

    backend_id = "norfair.hog-association.2.3.0"

    def associate(
        self, frames: Sequence[SubjectFrame],
    ) -> BackendResult[SubjectObservation]:
        if not isinstance(frames, (list, tuple)):
            raise ValueError("frames must be a list or tuple of SubjectFrame")
        if len(frames) > MAX_FRAMES:
            raise ValueError(f"frames exceeds the maximum of {MAX_FRAMES}")
        if not all(isinstance(frame, SubjectFrame) for frame in frames):
            raise ValueError("every frame must be a SubjectFrame")

        previous_timestamp = -1.0
        detection_count = 0
        for frame in frames:
            if frame.timestamp_seconds <= previous_timestamp:
                raise ValueError("frame timestamps must be strictly increasing")
            previous_timestamp = frame.timestamp_seconds
            if len(frame.detections) > MAX_DETECTIONS_PER_FRAME:
                raise ValueError("a frame contains too many subject detections")
            for detection in frame.detections:
                detection_count += 1
                if len(detection.appearance) > MAX_APPEARANCE_VALUES:
                    raise ValueError("appearance signature exceeds the supported size")

        try:
            installed_version = metadata.version("norfair")
        except metadata.PackageNotFoundError as exc:
            return BackendResult(
                backend_id=self.backend_id,
                status="unavailable",
                warnings=("Norfair is not installed in this Python environment.", str(exc)),
            )
        if installed_version != SUPPORTED_VERSION:
            return BackendResult(
                backend_id=self.backend_id,
                status="unavailable",
                warnings=(
                    f"Expected Norfair {SUPPORTED_VERSION}; found {installed_version}.",
                ),
                metadata={
                    "expected_version": SUPPORTED_VERSION,
                    "found_version": installed_version,
                },
            )

        if not frames or detection_count == 0:
            return BackendResult(
                backend_id=self.backend_id,
                status="insufficient_evidence",
                warnings=("No HOG subject detections were available for association.",),
                metadata={
                    "version": installed_version,
                    "frame_count": len(frames),
                    "detection_count": detection_count,
                },
            )

        try:
            import numpy as np
            from norfair import Detection, Tracker
        except ImportError as exc:
            return BackendResult(
                backend_id=self.backend_id,
                status="unavailable",
                warnings=("Norfair runtime dependencies are incomplete.", str(exc)),
                metadata={"version": installed_version},
            )

        def appearance_distance(left: Sequence[float], right: Sequence[float]) -> float:
            if not left or len(left) != len(right):
                return 1.0
            return min(1.0, 0.5 * sum(
                abs(float(a) - float(b)) for a, b in zip(left, right)
            ))

        def distance_function(detection, tracked_object) -> float:
            current = detection.data
            previous = tracked_object.last_detection.data
            gap = float(current["timestamp_seconds"]) - float(previous["timestamp_seconds"])
            if gap < 0 or gap > MAX_TRACK_GAP_SECONDS:
                return 1e6

            spatial = float(np.linalg.norm(
                detection.points[0] - tracked_object.estimate[0]
            ))
            color_distance = appearance_distance(
                current.get("appearance", ()),
                previous.get("appearance", ()),
            )
            current_height = max(1e-4, float(current["height_ratio"]))
            previous_height = max(1e-4, float(previous["height_ratio"]))
            size_distance = abs(math.log(current_height / previous_height))

            if spatial > 0.45 or color_distance > 0.82 or size_distance > 1.25:
                return 1e6
            return spatial + 0.35 * color_distance + 0.10 * size_distance

        tracker = Tracker(
            distance_function=distance_function,
            distance_threshold=0.75,
            hit_counter_max=3,
            initialization_delay=0,
            pointwise_hit_counter_max=4,
            detection_threshold=0.0,
            past_detections_length=4,
        )

        observations: list[SubjectObservation] = []
        frame_detection_count = 0
        for frame_index, frame in enumerate(frames):
            detections = []
            for item in frame.detections:
                box = item.box
                center_x = box.x + box.width / 2.0
                center_y = box.y + box.height / 2.0
                score = float(item.confidence or 0.0)
                confidence = max(0.0, min(1.0, score))
                detections.append(Detection(
                    points=np.asarray([[center_x, center_y]], dtype=np.float32),
                    scores=np.asarray([max(0.001, confidence)], dtype=np.float32),
                    data={
                        "timestamp_seconds": float(frame.timestamp_seconds),
                        "frame_index": frame_index,
                        "width_ratio": float(box.width),
                        "height_ratio": float(box.height),
                        "appearance": tuple(float(value) for value in item.appearance),
                        "confidence": confidence,
                        "box": (box.x, box.y, box.width, box.height),
                    },
                    label="subject",
                ))
            frame_detection_count += len(detections)
            active = tracker.update(detections=detections or None)
            for tracked in active:
                if tracked.id is None:
                    continue
                last = tracked.last_detection
                data = last.data or {}
                if data.get("frame_index") != frame_index:
                    continue
                x, y, width, height = data["box"]
                # HOG rectangles are clipped to frame dimensions before they enter
                # this backend, but clamp defensively before emitting the contract.
                x0 = max(0.0, min(1.0, float(x)))
                y0 = max(0.0, min(1.0, float(y)))
                x1 = max(x0, min(1.0, float(x) + float(width)))
                y1 = max(y0, min(1.0, float(y) + float(height)))
                if x1 <= x0 or y1 <= y0:
                    continue
                from .contracts import NormalizedBox
                observations.append(SubjectObservation(
                    timestamp_seconds=float(data["timestamp_seconds"]),
                    box=NormalizedBox(x0, y0, x1 - x0, y1 - y0),
                    confidence=float(data["confidence"]),
                    track_id=str(tracked.id),
                ))

        observations.sort(key=lambda item: (item.timestamp_seconds, item.track_id or ""))
        grouped: dict[str, list[float]] = {}
        for item in observations:
            grouped.setdefault(item.track_id or "", []).append(item.timestamp_seconds)
        track_summaries = [
            {
                "track_id": track_id,
                "observation_count": len(times),
                "start_seconds": times[0],
                "end_seconds": times[-1],
                "span_seconds": round(times[-1] - times[0], 3),
            }
            for track_id, times in sorted(grouped.items())
            if track_id
        ]
        status = "ok" if observations else "insufficient_evidence"
        return BackendResult(
            backend_id=self.backend_id,
            status=status,
            items=tuple(observations),
            warnings=(),
            metadata={
                "version": installed_version,
                "frame_count": len(frames),
                "detection_count": frame_detection_count,
                "track_count": len(track_summaries),
                "tracks": track_summaries,
                "max_track_gap_seconds": MAX_TRACK_GAP_SECONDS,
                "association": "Norfair Kalman + gated center motion and HOG color-histogram distance",
                "meaning": "short-gap appearance/motion association; not identity recognition",
            },
        )
