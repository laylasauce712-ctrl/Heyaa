"""Stable, dependency-free contracts for pluggable Heyaa analysis backends.

Backends return observations only. They do not edit the EDL, render media, or
make export decisions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Generic, Literal, Mapping, Protocol, Sequence, TypeVar

BackendStatus = Literal["ok", "insufficient_evidence", "unavailable", "failed"]
BeatKind = Literal["beat", "downbeat", "onset", "drop_candidate"]

T = TypeVar("T")


def _validate_timestamp(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number >= 0")
    if not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"{field_name} must be a finite number >= 0")


def _validate_confidence(value: float | None, field_name: str = "confidence") -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be between 0 and 1")
    if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class BackendResult(Generic[T]):
    """Evidence returned by one backend, with provenance and explicit status."""

    backend_id: str
    status: BackendStatus
    items: tuple[T, ...] = ()
    confidence: float | None = None
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.backend_id, str) or not self.backend_id.strip():
            raise ValueError("backend_id must be a non-empty string")
        if self.status not in {"ok", "insufficient_evidence", "unavailable", "failed"}:
            raise ValueError(f"unsupported backend status: {self.status!r}")
        _validate_confidence(self.confidence)
        if not isinstance(self.items, tuple):
            raise ValueError("items must be a tuple")
        if not isinstance(self.warnings, tuple) or not all(
            isinstance(item, str) for item in self.warnings
        ):
            raise ValueError("warnings must be a tuple of strings")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")


@dataclass(frozen=True, slots=True)
class SceneCut:
    timestamp_seconds: float
    confidence: float | None = None
    transition: str = "cut"

    def __post_init__(self) -> None:
        _validate_timestamp(self.timestamp_seconds, "timestamp_seconds")
        _validate_confidence(self.confidence)
        if not isinstance(self.transition, str) or not self.transition.strip():
            raise ValueError("transition must be a non-empty string")


@dataclass(frozen=True, slots=True)
class BeatEvent:
    timestamp_seconds: float
    kind: BeatKind = "beat"
    confidence: float | None = None

    def __post_init__(self) -> None:
        _validate_timestamp(self.timestamp_seconds, "timestamp_seconds")
        _validate_confidence(self.confidence)
        if self.kind not in {"beat", "downbeat", "onset", "drop_candidate"}:
            raise ValueError(f"unsupported beat event kind: {self.kind!r}")


@dataclass(frozen=True, slots=True)
class NormalizedBox:
    """Bounding box in normalized source-frame coordinates [0, 1]."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in values
        ):
            raise ValueError("bounding-box values must be finite numbers")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("bounding-box width and height must be positive")
        if self.x < 0 or self.y < 0 or self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("normalized bounding box must stay inside [0, 1]")


@dataclass(frozen=True, slots=True)
class SubjectObservation:
    timestamp_seconds: float
    box: NormalizedBox
    confidence: float | None = None
    track_id: str | None = None

    def __post_init__(self) -> None:
        _validate_timestamp(self.timestamp_seconds, "timestamp_seconds")
        _validate_confidence(self.confidence)
        if self.track_id is not None and (
            not isinstance(self.track_id, str) or not self.track_id.strip()
        ):
            raise ValueError("track_id must be None or a non-empty string")


@dataclass(frozen=True, slots=True)
class SemanticFinding:
    start_seconds: float
    end_seconds: float
    label: str
    summary: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        _validate_timestamp(self.start_seconds, "start_seconds")
        _validate_timestamp(self.end_seconds, "end_seconds")
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("label must be a non-empty string")
        if not isinstance(self.summary, str):
            raise ValueError("summary must be a string")
        _validate_confidence(self.confidence)


class SceneDetector(Protocol):
    backend_id: str

    def detect(
        self, media_path: str, *, start_seconds: float = 0.0,
        end_seconds: float | None = None,
    ) -> BackendResult[SceneCut]: ...


class BeatAnalyzer(Protocol):
    backend_id: str

    def analyze(
        self, media_path: str, *, duration_seconds: float | None = None,
    ) -> BackendResult[BeatEvent]: ...


class SubjectTracker(Protocol):
    backend_id: str

    def track(
        self, media_path: str, *, start_seconds: float = 0.0,
        end_seconds: float | None = None,
    ) -> BackendResult[SubjectObservation]: ...


@dataclass(frozen=True, slots=True)
class SubjectDetection:
    """One detector observation passed to an association/tracking backend."""

    timestamp_seconds: float
    box: NormalizedBox
    confidence: float | None = None
    appearance: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _validate_timestamp(self.timestamp_seconds, "timestamp_seconds")
        _validate_confidence(self.confidence)
        if not isinstance(self.appearance, tuple) or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in self.appearance
        ):
            raise ValueError("appearance must be a tuple of finite numbers")


@dataclass(frozen=True, slots=True)
class SubjectFrame:
    """Timestamped detector output for one sampled source frame."""

    timestamp_seconds: float
    detections: tuple[SubjectDetection, ...] = ()

    def __post_init__(self) -> None:
        _validate_timestamp(self.timestamp_seconds, "timestamp_seconds")
        if not isinstance(self.detections, tuple) or not all(
            isinstance(item, SubjectDetection) for item in self.detections
        ):
            raise ValueError("detections must be a tuple of SubjectDetection")


class SubjectAssociator(Protocol):
    """Association-only backend; does not run a detector or choose a subject."""

    backend_id: str

    def associate(
        self, frames: Sequence[SubjectFrame],
    ) -> BackendResult[SubjectObservation]: ...


class SemanticReviewer(Protocol):
    backend_id: str

    def review(
        self, media_path: str, *,
        intervals: Sequence[tuple[float, float]],
    ) -> BackendResult[SemanticFinding]: ...
