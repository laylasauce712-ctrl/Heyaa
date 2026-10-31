#!/usr/bin/env python3
"""Run Beat This! in its isolated environment and emit one JSON result."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def main() -> int:
    from src.heyaa.backends.beat_this import BeatThisBackend

    payload: dict[str, Any] = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("worker payload must be a JSON object")
    media_path = payload.get("media_path")
    if not isinstance(media_path, str) or not media_path.strip():
        raise ValueError("media_path must be a non-empty string")

    backend = BeatThisBackend(
        checkpoint=payload.get("checkpoint", "small0"),
        max_analysis_seconds=payload.get("max_analysis_seconds", 45.0),
        ffmpeg_timeout_seconds=payload.get("ffmpeg_timeout_seconds", 90),
    )
    runtime = {
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "is_venv": sys.prefix != sys.base_prefix,
    }
    result = backend.analyze(
        media_path,
        duration_seconds=payload.get("duration_seconds"),
    )
    print(json.dumps({
        "backend_id": result.backend_id,
        "status": result.status,
        "items": [asdict(item) for item in result.items],
        "warnings": list(result.warnings),
        "metadata": {**dict(result.metadata), "worker_runtime": runtime},
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
