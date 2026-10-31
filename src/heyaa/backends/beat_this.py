"""Optional Beat This! 1.1.0 beat/downbeat adapter.

This module is safe to import from the core interpreter: PyTorch, torchaudio,
and Beat This! are imported only inside analyze(), which runs in a dedicated
worker/virtual environment.
"""
from __future__ import annotations

import importlib
from importlib import metadata
import math
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from .contracts import BackendResult, BeatEvent

SUPPORTED_VERSION = "1.1.0"
DEFAULT_CHECKPOINT = "small0"
DEFAULT_ANALYSIS_SECONDS = 45.0
DEFAULT_FFMPEG_TIMEOUT_SECONDS = 90


class BeatThisBackend:
    """Run Beat This! on a bounded CPU audio window and return timing evidence."""

    backend_id = "beat-this.small0.1.1.0"

    def __init__(
        self,
        *,
        checkpoint: str = DEFAULT_CHECKPOINT,
        max_analysis_seconds: float = DEFAULT_ANALYSIS_SECONDS,
        ffmpeg_timeout_seconds: int = DEFAULT_FFMPEG_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(checkpoint, str) or not checkpoint.strip():
            raise ValueError("checkpoint must be a non-empty string")
        if (
            isinstance(max_analysis_seconds, bool)
            or not isinstance(max_analysis_seconds, (int, float))
            or not math.isfinite(float(max_analysis_seconds))
            or max_analysis_seconds <= 0
        ):
            raise ValueError("max_analysis_seconds must be a finite number > 0")
        if (
            isinstance(ffmpeg_timeout_seconds, bool)
            or not isinstance(ffmpeg_timeout_seconds, int)
            or ffmpeg_timeout_seconds <= 0
        ):
            raise ValueError("ffmpeg_timeout_seconds must be a positive integer")
        self.checkpoint = checkpoint
        self.max_analysis_seconds = float(max_analysis_seconds)
        self.ffmpeg_timeout_seconds = ffmpeg_timeout_seconds

    def analyze(
        self,
        media_path: str,
        *,
        duration_seconds: float | None = None,
    ) -> BackendResult[BeatEvent]:
        if not isinstance(media_path, str) or not media_path.strip():
            raise ValueError("media_path must be a non-empty string")
        source = Path(media_path).expanduser()
        if not source.is_file():
            return BackendResult(
                backend_id=self.backend_id,
                status="failed",
                warnings=(f"Audio source does not exist or is not a file: {source}",),
            )
        if duration_seconds is not None and (
            isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(float(duration_seconds))
            or duration_seconds <= 0
        ):
            raise ValueError("duration_seconds must be finite and > 0 when supplied")

        try:
            installed_version = metadata.version("beat-this")
        except metadata.PackageNotFoundError as exc:
            return BackendResult(
                backend_id=self.backend_id,
                status="unavailable",
                warnings=("Beat This! is not installed in this Python environment.", str(exc)),
                metadata={"expected_version": SUPPORTED_VERSION},
            )

        if installed_version != SUPPORTED_VERSION:
            return BackendResult(
                backend_id=self.backend_id,
                status="unavailable",
                warnings=(
                    f"Expected Beat This! {SUPPORTED_VERSION}; found {installed_version}.",
                ),
                metadata={
                    "expected_version": SUPPORTED_VERSION,
                    "found_version": installed_version,
                },
            )

        analysis_seconds = min(
            self.max_analysis_seconds,
            float(duration_seconds) if duration_seconds is not None else self.max_analysis_seconds,
        )
        if analysis_seconds <= 0.25:
            return BackendResult(
                backend_id=self.backend_id,
                status="insufficient_evidence",
                warnings=("Audio window is too short for beat analysis.",),
                metadata={"analysis_duration_seconds": analysis_seconds},
            )

        try:
            torch = importlib.import_module("torch")
            torchaudio = importlib.import_module("torchaudio")
            inference = importlib.import_module("beat_this.inference")
            File2Beats = inference.File2Beats
        except ImportError as exc:
            return BackendResult(
                backend_id=self.backend_id,
                status="unavailable",
                warnings=("Beat This! runtime dependencies are incomplete.", str(exc)),
                metadata={"version": installed_version},
            )

        runtime = {
            "torch_version": str(getattr(torch, "__version__", "unknown")),
            "torchaudio_version": str(getattr(torchaudio, "__version__", "unknown")),
            "device": "cpu",
        }
        try:
            with tempfile.TemporaryDirectory(prefix="heyaa-beat-shadow-") as temp_dir:
                wav_path = Path(temp_dir) / "analysis.wav"
                command = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(source.resolve()),
                    "-t", f"{analysis_seconds:.6f}",
                    "-vn", "-ac", "1", "-ar", "22050",
                    "-c:a", "pcm_s16le", str(wav_path),
                ]
                completed = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=self.ffmpeg_timeout_seconds,
                )
                if completed.returncode != 0 or not wav_path.is_file() or wav_path.stat().st_size == 0:
                    detail = (completed.stderr or "FFmpeg did not produce an audio window.").strip()
                    return BackendResult(
                        backend_id=self.backend_id,
                        status="failed",
                        warnings=(detail[-1200:],),
                        metadata={
                            "version": installed_version,
                            "analysis_duration_seconds": analysis_seconds,
                            "runtime": runtime,
                        },
                    )
                tracker = File2Beats(
                    checkpoint_path=self.checkpoint,
                    device="cpu",
                    dbn=False,
                )
                beat_times, downbeat_times = tracker(str(wav_path))
        except subprocess.TimeoutExpired:
            return BackendResult(
                backend_id=self.backend_id,
                status="failed",
                warnings=("FFmpeg audio preparation exceeded its timeout.",),
                metadata={
                    "version": installed_version,
                    "analysis_duration_seconds": analysis_seconds,
                    "runtime": runtime,
                },
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return BackendResult(
                backend_id=self.backend_id,
                status="failed",
                warnings=(f"Beat This! inference failed: {type(exc).__name__}: {exc}",),
                metadata={
                    "version": installed_version,
                    "checkpoint": self.checkpoint,
                    "analysis_duration_seconds": analysis_seconds,
                    "runtime": runtime,
                },
            )

        def finite_times(values: Any, label: str) -> list[float]:
            output = []
            for value in values:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"Beat This! returned a non-numeric {label} timestamp")
                timestamp = float(value)
                if not math.isfinite(timestamp) or timestamp < 0:
                    raise ValueError(f"Beat This! returned an invalid {label} timestamp")
                if timestamp <= analysis_seconds + 0.001:
                    output.append(timestamp)
            return sorted(set(output))

        beats = finite_times(beat_times, "beat")
        downbeats = finite_times(downbeat_times, "downbeat")
        events = [BeatEvent(timestamp, kind="beat") for timestamp in beats]
        events.extend(BeatEvent(timestamp, kind="downbeat") for timestamp in downbeats)

        return BackendResult(
            backend_id=self.backend_id,
            status="ok",
            items=tuple(sorted(events, key=lambda event: (event.timestamp_seconds, event.kind))),
            confidence=None,
            warnings=(),
            metadata={
                "version": installed_version,
                "checkpoint": self.checkpoint,
                "device": "cpu",
                "analysis_duration_seconds": analysis_seconds,
                "beat_count": len(beats),
                "downbeat_count": len(downbeats),
                "runtime": runtime,
                "meaning": "model beat/downbeat timestamps; not a semantic musical-drop detector",
            },
        )
