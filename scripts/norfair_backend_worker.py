#!/usr/bin/env python3
"""JSON worker for Norfair association of already-detected HOG observations."""
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def main() -> int:
    from src.heyaa.backends.contracts import NormalizedBox, SubjectDetection, SubjectFrame
    from src.heyaa.backends.norfair import NorfairAssociator

    payload: dict[str, Any] = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("worker payload must be a JSON object")
    raw_frames = payload.get("frames")
    if not isinstance(raw_frames, list):
        raise ValueError("frames must be a list")

    frames = []
    for raw_frame in raw_frames:
        if not isinstance(raw_frame, dict):
            raise ValueError("each frame must be an object")
        raw_detections = raw_frame.get("detections", [])
        if not isinstance(raw_detections, list):
            raise ValueError("frame detections must be a list")
        detections = []
        for raw in raw_detections:
            if not isinstance(raw, dict):
                raise ValueError("each detection must be an object")
            box = NormalizedBox(
                x=float(raw["x"]),
                y=float(raw["y"]),
                width=float(raw["width"]),
                height=float(raw["height"]),
            )
            appearance = raw.get("appearance", [])
            if not isinstance(appearance, list):
                raise ValueError("appearance must be a list")
            detections.append(SubjectDetection(
                timestamp_seconds=float(raw_frame["timestamp_seconds"]),
                box=box,
                confidence=float(raw.get("confidence", 0.0)),
                appearance=tuple(float(value) for value in appearance),
            ))
        frames.append(SubjectFrame(
            timestamp_seconds=float(raw_frame["timestamp_seconds"]),
            detections=tuple(detections),
        ))

    backend = NorfairAssociator()
    runtime = {
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "is_venv": sys.prefix != sys.base_prefix,
    }
    with redirect_stdout(sys.stderr):
        result = backend.associate(frames)
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
