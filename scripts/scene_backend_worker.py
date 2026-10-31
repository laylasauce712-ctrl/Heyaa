#!/usr/bin/env python3
"""JSON-lines-free stdin/stdout worker for the isolated PySceneDetect runtime."""
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
    from src.heyaa.backends.pyscenedetect import PySceneDetectBackend

    payload: dict[str, Any] = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("worker payload must be a JSON object")
    media_path = payload.get("media_path")
    windows = payload.get("windows")
    if not isinstance(media_path, str) or not media_path.strip():
        raise ValueError("media_path must be a non-empty string")
    if not isinstance(windows, list) or not windows:
        raise ValueError("windows must be a non-empty list")

    backend = PySceneDetectBackend(
        threshold=payload.get("threshold", 27.0),
        min_scene_len_seconds=payload.get("min_scene_len_seconds", 0.15),
    )
    items = []
    window_reports = []
    for window in windows:
        if not isinstance(window, dict):
            raise ValueError("each window must be an object")
        start = window.get("start_seconds")
        end = window.get("end_seconds")
        result = backend.detect(
            media_path,
            start_seconds=start,
            end_seconds=end,
        )
        window_reports.append({
            "start_seconds": start,
            "end_seconds": end,
            "status": result.status,
            "metadata": dict(result.metadata),
            "warnings": list(result.warnings),
        })
        if result.status != "ok":
            print(json.dumps({
                "backend_id": backend.backend_id,
                "status": result.status,
                "items": [],
                "warnings": list(result.warnings),
                "metadata": {
                    "windows": window_reports,
                    "failed_window": window,
                },
            }, separators=(",", ":")))
            return 0
        items.extend(asdict(item) for item in result.items)

    # Windows may touch or overlap after rounding. De-duplicate equivalent
    # boundary timestamps without shifting the original event time.
    ordered = sorted(items, key=lambda item: item["timestamp_seconds"])
    unique = []
    for item in ordered:
        if not unique or abs(item["timestamp_seconds"] - unique[-1]["timestamp_seconds"]) > 0.001:
            unique.append(item)

    print(json.dumps({
        "backend_id": backend.backend_id,
        "status": "ok",
        "items": unique,
        "warnings": [],
        "metadata": {
            "windows": window_reports,
            "version": "0.7.2",
            "detector": "ContentDetector",
            "cut_count": len(unique),
        },
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
