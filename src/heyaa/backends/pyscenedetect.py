"""Optional PySceneDetect 0.7.2 adapter.

This module imports no third-party package at import time. PySceneDetect is
loaded only when detect() is called, so the core Heyaa environment stays light.
"""
from __future__ import annotations

import importlib
import math
from typing import Any

from .contracts import BackendResult, SceneCut

DEFAULT_THRESHOLD = 27.0
DEFAULT_MIN_SCENE_LEN_SECONDS = 0.15
SUPPORTED_VERSION = "0.7.2"


class PySceneDetectBackend:
    """ContentDetector adapter that returns timestamped cuts as evidence only."""

    backend_id = "pyscenedetect.content.0.7.2"

    def __init__(
        self,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        min_scene_len_seconds: float = DEFAULT_MIN_SCENE_LEN_SECONDS,
    ) -> None:
        for name, value in (
            ("threshold", threshold),
            ("min_scene_len_seconds", min_scene_len_seconds),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value <= 0
            ):
                raise ValueError(f"{name} must be a finite number > 0")
        self.threshold = float(threshold)
        self.min_scene_len_seconds = float(min_scene_len_seconds)

    def detect(
        self,
        media_path: str,
        *,
        start_seconds: float = 0.0,
        end_seconds: float | None = None,
    ) -> BackendResult[SceneCut]:
        """Detect cuts in one bounded time window of a media file.

        A completed scan with zero cuts is a valid result. Missing optional
        dependencies and expected decode/seek failures are returned explicitly.
        """
        if not isinstance(media_path, str) or not media_path.strip():
            raise ValueError("media_path must be a non-empty string")
        if (
            isinstance(start_seconds, bool)
            or not isinstance(start_seconds, (int, float))
            or not math.isfinite(float(start_seconds))
            or start_seconds < 0
        ):
            raise ValueError("start_seconds must be a finite number >= 0")
        if end_seconds is not None and (
            isinstance(end_seconds, bool)
            or not isinstance(end_seconds, (int, float))
            or not math.isfinite(float(end_seconds))
            or end_seconds <= start_seconds
        ):
            raise ValueError("end_seconds must be finite and greater than start_seconds")

        try:
            scenedetect = importlib.import_module("scenedetect")
            stream_api = importlib.import_module("scenedetect.video_stream")
        except ImportError as exc:
            return BackendResult(
                backend_id=self.backend_id,
                status="unavailable",
                warnings=(
                    "PySceneDetect is not installed in this Python environment.",
                    str(exc),
                ),
                metadata={"expected_version": SUPPORTED_VERSION},
            )

        version = str(getattr(scenedetect, "__version__", "unknown"))
        if version != SUPPORTED_VERSION:
            return BackendResult(
                backend_id=self.backend_id,
                status="unavailable",
                warnings=(
                    f"Expected PySceneDetect {SUPPORTED_VERSION}; found {version}.",
                    "Install the isolated scene backend from requirements-scenes.txt.",
                ),
                metadata={"expected_version": SUPPORTED_VERSION, "found_version": version},
            )

        try:
            detector = scenedetect.ContentDetector(
                threshold=self.threshold,
                min_scene_len=self.min_scene_len_seconds,
            )
            scenes = scenedetect.detect(
                media_path,
                detector,
                show_progress=False,
                start_time=float(start_seconds),
                end_time=float(end_seconds) if end_seconds is not None else None,
                start_in_scene=True,
                backend="opencv",
            )
        except (
            stream_api.VideoOpenFailure,
            stream_api.SeekError,
            OSError,
            RuntimeError,
        ) as exc:
            return BackendResult(
                backend_id=self.backend_id,
                status="failed",
                warnings=(f"PySceneDetect could not analyze the requested window: {exc}",),
                metadata={
                    "version": version,
                    "start_seconds": float(start_seconds),
                    "end_seconds": float(end_seconds) if end_seconds is not None else None,
                },
            )

        cuts: list[SceneCut] = []
        for scene_start, _scene_end in scenes[1:]:
            timestamp = float(scene_start.seconds)
            if timestamp < float(start_seconds):
                continue
            if end_seconds is not None and timestamp >= float(end_seconds):
                continue
            cuts.append(SceneCut(timestamp_seconds=timestamp, transition="cut"))

        return BackendResult(
            backend_id=self.backend_id,
            status="ok",
            items=tuple(cuts),
            confidence=None,
            metadata={
                "version": version,
                "detector": "ContentDetector",
                "threshold": self.threshold,
                "min_scene_len_seconds": self.min_scene_len_seconds,
                "start_seconds": float(start_seconds),
                "end_seconds": float(end_seconds) if end_seconds is not None else None,
                "scene_count": len(scenes),
                "cut_count": len(cuts),
                "meaning": "visual shot-boundary candidates; not semantic scene understanding",
            },
        )
