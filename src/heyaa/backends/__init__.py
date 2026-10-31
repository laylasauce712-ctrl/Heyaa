"""Optional analysis backend interfaces for Heyaa.

Importing this package loads only the standard library. Third-party engines
are loaded lazily by their adapters or dedicated worker processes.
"""
from .contracts import (
    BackendResult,
    BeatAnalyzer,
    BeatEvent,
    NormalizedBox,
    SceneCut,
    SceneDetector,
    SemanticFinding,
    SemanticReviewer,
    SubjectAssociator,
    SubjectDetection,
    SubjectFrame,
    SubjectObservation,
    SubjectTracker,
)
from .pyscenedetect import PySceneDetectBackend
from .beat_this import BeatThisBackend
from .norfair import NorfairAssociator
from .shadow_compare import compare_cut_timestamps
from .registry import (
    BACKEND_ROLES,
    BackendAttempt,
    BackendExecutionError,
    BackendOutcome,
    BackendRegistry,
    BackendUnavailableError,
    execute_with_fallback,
)

__all__ = [
    "BACKEND_ROLES",
    "BackendAttempt",
    "BackendExecutionError",
    "BackendOutcome",
    "BackendRegistry",
    "BackendResult",
    "BackendUnavailableError",
    "PySceneDetectBackend",
    "BeatThisBackend",
    "NorfairAssociator",
    "compare_cut_timestamps",
    "BeatAnalyzer",
    "BeatEvent",
    "NormalizedBox",
    "SceneCut",
    "SceneDetector",
    "SemanticFinding",
    "SemanticReviewer",
    "SubjectAssociator",
    "SubjectDetection",
    "SubjectFrame",
    "SubjectObservation",
    "SubjectTracker",
    "execute_with_fallback",
]
