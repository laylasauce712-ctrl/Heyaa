"""Explicit backend registration and conservative fallback execution.

No backend is auto-imported or auto-discovered. Optional packages stay out of
the base runtime until a caller explicitly registers an implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from .contracts import BackendResult

BACKEND_ROLES = (
    "scene_detector",
    "beat_analyzer",
    "subject_tracker",
    "semantic_reviewer",
)

_REQUIRED_METHODS = {
    "scene_detector": "detect",
    "beat_analyzer": "analyze",
    "subject_tracker": "track",
    "semantic_reviewer": "review",
}


class BackendError(RuntimeError):
    """Base class for expected backend integration failures."""


class BackendUnavailableError(BackendError):
    """The backend cannot run, commonly because an optional dependency is absent."""


class BackendExecutionError(BackendError):
    """The backend was selected but could not complete its analysis."""


@dataclass(frozen=True, slots=True)
class BackendAttempt:
    backend_id: str
    status: str
    detail: str | None = None


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BackendOutcome(Generic[T]):
    result: BackendResult[T] | None
    attempts: tuple[BackendAttempt, ...]
    fallback_used: bool
    error: str | None = None


class BackendRegistry:
    """In-memory registry; callers must choose backend IDs explicitly."""

    def __init__(self) -> None:
        self._backends: dict[str, dict[str, object]] = {
            role: {} for role in BACKEND_ROLES
        }

    def register(self, role: str, backend: object) -> None:
        if role not in _REQUIRED_METHODS:
            raise ValueError(f"unsupported backend role: {role!r}")
        backend_id = getattr(backend, "backend_id", None)
        if not isinstance(backend_id, str) or not backend_id.strip():
            raise ValueError("backend must expose a non-empty backend_id")
        method = _REQUIRED_METHODS[role]
        if not callable(getattr(backend, method, None)):
            raise TypeError(f"{role} backend must implement callable {method}()")
        if backend_id in self._backends[role]:
            raise ValueError(f"{role} backend {backend_id!r} is already registered")
        self._backends[role][backend_id] = backend

    def get(self, role: str, backend_id: str) -> object:
        if role not in self._backends:
            raise ValueError(f"unsupported backend role: {role!r}")
        try:
            return self._backends[role][backend_id]
        except KeyError as exc:
            raise BackendUnavailableError(
                f"No {role} backend named {backend_id!r} is registered"
            ) from exc

    def names(self, role: str) -> tuple[str, ...]:
        if role not in self._backends:
            raise ValueError(f"unsupported backend role: {role!r}")
        return tuple(self._backends[role])


def execute_with_fallback(
    primary: object,
    fallback: object | None,
    *,
    run: Callable[[object], BackendResult[T]],
) -> BackendOutcome[T]:
    """Run a preferred backend, then an explicit fallback on expected failures.

    insufficient_evidence is preserved rather than silently retried: absence
    of evidence is not the same as a broken backend. Unexpected exceptions are
    deliberately allowed to propagate so programming bugs are not hidden.
    """

    attempts: list[BackendAttempt] = []
    candidates = (primary,) if fallback is None else (primary, fallback)
    last_result: BackendResult[T] | None = None
    last_error: str | None = None

    for index, backend in enumerate(candidates):
        backend_id = getattr(backend, "backend_id", None)
        if not isinstance(backend_id, str) or not backend_id.strip():
            raise ValueError("backend must expose a non-empty backend_id")

        try:
            result = run(backend)
        except BackendUnavailableError as exc:
            last_error = str(exc)
            attempts.append(BackendAttempt(backend_id, "unavailable", last_error))
            continue
        except BackendExecutionError as exc:
            last_error = str(exc)
            attempts.append(BackendAttempt(backend_id, "failed", last_error))
            continue

        if not isinstance(result, BackendResult):
            raise TypeError(
                f"backend {backend_id!r} returned {type(result).__name__}, "
                "expected BackendResult"
            )
        if result.backend_id != backend_id:
            raise ValueError(
                f"backend result provenance mismatch: selected {backend_id!r}, "
                f"reported {result.backend_id!r}"
            )

        last_result = result
        detail = "; ".join(result.warnings) or None
        attempts.append(BackendAttempt(backend_id, result.status, detail))
        if result.status not in {"unavailable", "failed"}:
            return BackendOutcome(
                result=result,
                attempts=tuple(attempts),
                fallback_used=index > 0,
            )
        last_error = detail or f"backend returned status {result.status!r}"

    return BackendOutcome(
        result=last_result,
        attempts=tuple(attempts),
        fallback_used=len(attempts) > 1,
        error=last_error,
    )
