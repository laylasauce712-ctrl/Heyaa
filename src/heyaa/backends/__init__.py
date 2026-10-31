"""Optional analysis backend interfaces for Heyaa.

Importing this package loads only the standard library. Third-party engines
must be installed and registered explicitly by a future integration.
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
    SubjectObservation,
    SubjectTracker,
)
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
    "BeatAnalyzer",
    "BeatEvent",
    "NormalizedBox",
    "SceneCut",
    "SceneDetector",
    "SemanticFinding",
    "SemanticReviewer",
    "SubjectObservation",
    "SubjectTracker",
    "execute_with_fallback",
]
