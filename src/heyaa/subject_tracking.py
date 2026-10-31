"""Optional OpenCV HOG person-track proxy for choosing and framing a source context.

This is not face recognition or semantic identity verification. It provides a
low-confidence, clothing/position appearance track when OpenCV is installed;
otherwise the renderer falls back to its scene-cut-density context heuristic.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any


def _appearance_distance(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 1.0
    # Both histograms are L1-normalized; half their L1 distance lies in [0, 1].
    return min(1.0, 0.5 * sum(abs(a - b) for a, b in zip(left, right)))


def _associate_detections(frames: list[dict[str, Any]], max_gap_seconds: float = 2.2):
    """Greedy short-gap tracking of detected people using location and clothing color."""
    tracks: list[dict[str, Any]] = []
    next_track_id = 0
    for frame in frames:
        timestamp = float(frame["time_seconds"])
        detections = sorted(frame.get("detections", []),
                            key=lambda item: float(item.get("detector_score", 0.0)), reverse=True)
        used_tracks: set[int] = set()
        for detection in detections:
            center_x = float(detection["center_x"])
            center_y = float(detection["center_y"])
            height_ratio = max(1e-4, float(detection["height_ratio"]))
            best_track = None
            best_cost = float("inf")
            for track in tracks:
                if track["track_id"] in used_tracks:
                    continue
                previous = track["observations"][-1]
                gap = timestamp - float(previous["time_seconds"])
                if gap < 0 or gap > max_gap_seconds:
                    continue
                spatial = math.hypot(center_x - previous["center_x"], center_y - previous["center_y"])
                color_distance = _appearance_distance(
                    detection.get("color_histogram", []), previous.get("color_histogram", [])
                )
                size_distance = abs(math.log(height_ratio / max(1e-4, previous["height_ratio"])))
                if spatial > 0.45 or color_distance > 0.82 or size_distance > 1.25:
                    continue
                cost = spatial + 0.35 * color_distance + 0.10 * size_distance
                if cost < best_cost:
                    best_cost, best_track = cost, track
            observation = {
                "time_seconds": timestamp,
                "center_x": max(0.0, min(1.0, center_x)),
                "center_y": max(0.0, min(1.0, center_y)),
                "height_ratio": height_ratio,
                "detector_score": float(detection.get("detector_score", 0.0)),
                "color_histogram": list(detection.get("color_histogram", [])),
            }
            if best_track is None:
                best_track = {"track_id": next_track_id, "observations": []}
                tracks.append(best_track)
                next_track_id += 1
            best_track["observations"].append(observation)
            used_tracks.add(best_track["track_id"])
    return tracks


def _pick_dominant_track(tracks: list[dict[str, Any]]) -> dict[str, Any] | None:
    viable = []
    for track in tracks:
        observations = track.get("observations", [])
        if len(observations) < 3:
            continue
        span = float(observations[-1]["time_seconds"]) - float(observations[0]["time_seconds"])
        if span < 1.5:
            continue
        average_score = sum(max(0.0, float(obs["detector_score"])) for obs in observations) / len(observations)
        # Presence over time and stable repeated detections are proxies, not an identity confidence.
        track["span_seconds"] = round(span, 3)
        track["track_quality_proxy"] = round(min(1.0, 0.6 * min(1.0, span / 8.0)
                                                       + 0.4 * min(1.0, len(observations) / 8.0)), 4)
        track["average_detector_score"] = round(average_score, 4)
        viable.append(track)
    if not viable:
        return None
    return max(viable, key=lambda track: (
        track["track_quality_proxy"], len(track["observations"]), track["average_detector_score"]
    ))


def _norfair_worker_python() -> Path | None:
    """Find the optional Norfair venv without resolving its Python symlink."""
    root = Path(__file__).resolve().parents[2]
    configured = os.environ.get("HEYAA_NORFAIR_SHADOW_PYTHON")
    candidates = (
        [Path(configured).expanduser()] if configured else [
            root / "tools" / "norfair-analysis" / ".venv" / "bin" / "python",
            root / "tools" / "norfair-analysis" / ".venv" / "Scripts" / "python.exe",
        ]
    )
    for candidate in candidates:
        try:
            if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
                return candidate.absolute()
        except OSError:
            continue
    return None


def _run_norfair_shadow(
    frames: list[dict[str, Any]],
    custom_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Associate existing HOG boxes in an isolated Norfair process."""
    worker_python = _norfair_worker_python()
    if worker_python is None or not frames:
        return None
    root = Path(__file__).resolve().parents[2]
    worker_script = root / "scripts" / "norfair_backend_worker.py"
    if not worker_script.is_file():
        return {
            "backend_id": "norfair.hog-association.2.3.0",
            "status": "failed",
            "items": [],
            "warnings": [f"Norfair worker script is missing: {worker_script}"],
            "metadata": {},
        }

    payload_frames = []
    total_detections = 0
    for frame in frames:
        converted = []
        for detection in frame.get("detections", []):
            cx = max(0.0, min(1.0, float(detection.get("center_x", 0.5))))
            cy = max(0.0, min(1.0, float(detection.get("center_y", 0.5))))
            width = max(1e-4, min(1.0, float(detection.get("width_ratio", 0.08))))
            height = max(1e-4, min(1.0, float(detection.get("height_ratio", 0.2))))
            x0 = max(0.0, min(1.0, cx - width / 2.0))
            y0 = max(0.0, min(1.0, cy - height / 2.0))
            x1 = max(x0, min(1.0, cx + width / 2.0))
            y1 = max(y0, min(1.0, cy + height / 2.0))
            if x1 <= x0 or y1 <= y0:
                continue
            converted.append({
                "x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0,
                "confidence": max(0.0, min(1.0, float(detection.get("detector_score", 0.0)))),
                "appearance": list(detection.get("color_histogram", [])),
            })
        payload_frames.append({
            "timestamp_seconds": float(frame["time_seconds"]),
            "detections": converted,
        })
        total_detections += len(converted)
    if total_detections == 0:
        return None

    try:
        completed = subprocess.run(
            [str(worker_python), str(worker_script)],
            input=json.dumps({"frames": payload_frames}, separators=(",", ":")),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            cwd=str(root),
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        return {
            "backend_id": "norfair.hog-association.2.3.0",
            "status": "failed",
            "items": [],
            "warnings": ["Norfair shadow worker exceeded its 90-second timeout."],
            "metadata": {"input_frames": len(payload_frames), "detection_count": total_detections},
        }
    except OSError as exc:
        return {
            "backend_id": "norfair.hog-association.2.3.0",
            "status": "failed",
            "items": [],
            "warnings": [f"Could not start isolated Norfair worker: {exc}"],
            "metadata": {"input_frames": len(payload_frames), "detection_count": total_detections},
        }

    try:
        report = json.loads(completed.stdout)
    except (TypeError, ValueError):
        detail = (completed.stderr or completed.stdout or "worker returned no JSON").strip()[-1200:]
        return {
            "backend_id": "norfair.hog-association.2.3.0",
            "status": "failed",
            "items": [],
            "warnings": [f"Could not decode Norfair worker output: {detail}"],
            "metadata": {"input_frames": len(payload_frames), "detection_count": total_detections},
        }
    if not isinstance(report, dict):
        return {
            "backend_id": "norfair.hog-association.2.3.0",
            "status": "failed",
            "items": [],
            "warnings": ["Norfair worker returned JSON that was not an object."],
            "metadata": {"input_frames": len(payload_frames), "detection_count": total_detections},
        }
    if report.get("status") not in {"ok", "insufficient_evidence", "unavailable", "failed"}:
        return {
            "backend_id": "norfair.hog-association.2.3.0",
            "status": "failed",
            "items": [],
            "warnings": ["Norfair worker returned an unsupported status."],
            "metadata": {"input_frames": len(payload_frames), "detection_count": total_detections},
        }
    if completed.returncode != 0 and report.get("status") == "ok":
        report["status"] = "failed"
        report.setdefault("warnings", []).append(
            f"Worker exited with code {completed.returncode}: {(completed.stderr or '').strip()[-800:]}"
        )
    report.setdefault("metadata", {})["selected_python"] = str(worker_python)
    report["metadata"]["configured_python_override"] = bool(
        os.environ.get("HEYAA_NORFAIR_SHADOW_PYTHON")
    )
    if custom_observations and report.get("status") == "ok":
        norfair_items = report.get("items", [])
        matched_track_ids: dict[str, int] = {}
        matched_count = 0
        for observation in custom_observations:
            target_time = float(observation["time_seconds"])
            cx = float(observation["center_x"])
            cy = float(observation["center_y"])
            candidates = [
                item for item in norfair_items
                if isinstance(item, dict)
                and isinstance(item.get("timestamp_seconds"), (int, float))
                and abs(float(item["timestamp_seconds"]) - target_time) <= 0.03
                and isinstance(item.get("box"), dict)
            ]
            nearest = None
            nearest_distance = float("inf")
            for item in candidates:
                box = item["box"]
                shadow_cx = float(box["x"]) + float(box["width"]) / 2.0
                shadow_cy = float(box["y"]) + float(box["height"]) / 2.0
                distance = math.hypot(cx - shadow_cx, cy - shadow_cy)
                if distance < nearest_distance:
                    nearest_distance, nearest = distance, item
            if nearest is not None and nearest_distance <= 0.18:
                matched_count += 1
                track_id = str(nearest.get("track_id", ""))
                if track_id:
                    matched_track_ids[track_id] = matched_track_ids.get(track_id, 0) + 1
        dominant = (
            max(matched_track_ids.items(), key=lambda item: item[1])
            if matched_track_ids else None
        )
        report["comparison"] = {
            "custom_observation_count": len(custom_observations),
            "matched_observation_count": matched_count,
            "matched_track_ids": matched_track_ids,
            "dominant_norfair_track_id": dominant[0] if dominant else None,
            "dominant_track_share": (
                round(dominant[1] / matched_count, 4)
                if dominant and matched_count else None
            ),
            "tolerance_seconds": 0.03,
            "center_distance_threshold": 0.18,
            "interpretation": "association agreement only; neither tracker is ground truth",
        }
    return report


def detect_person_track(video_path: str, start_seconds: float, end_seconds: float,
                        sample_interval_seconds: float = 0.75,
                        max_frame_side: int = 480,
                        norfair_shadow_enabled: bool = True) -> dict[str, Any]:
    """Run optional OpenCV's built-in HOG people detector on one bounded source window."""
    try:
        import cv2
    except ImportError:
        return {
            "available": False, "detected": False, "method": "opencv-hog-unavailable",
            "reason": "OpenCV is not installed; scene-cut-density fallback remains active.",
            "observations": [], "track_id": None, "track_quality_proxy": None,
            "identity_semantics": False,
        }

    if (not math.isfinite(float(start_seconds)) or not math.isfinite(float(end_seconds)) or
            start_seconds < 0 or end_seconds <= start_seconds or sample_interval_seconds <= 0):
        return {
            "available": True, "detected": False, "method": "opencv-hog-invalid-window",
            "reason": "Invalid video time window.", "observations": [], "track_id": None,
            "track_quality_proxy": None, "identity_semantics": False,
        }

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        capture.release()
        return {
            "available": True, "detected": False, "method": "opencv-hog-open-failed",
            "reason": "OpenCV could not open the source file.", "observations": [],
            "track_id": None, "track_quality_proxy": None, "identity_semantics": False,
        }

    frames: list[dict[str, Any]] = []
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if not math.isfinite(fps) or fps <= 0:
            fps = 25.0
        capture.set(cv2.CAP_PROP_POS_MSEC, float(start_seconds) * 1000.0)
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        next_sample = float(start_seconds)
        sample_step = max(1.0 / fps, float(sample_interval_seconds))
        frame_index = max(0, int(round(start_seconds * fps)))
        frame_limit = int(round(end_seconds * fps))
        while frame_index <= frame_limit:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = frame_index / fps
            frame_index += 1
            if timestamp + 0.001 < next_sample:
                continue
            next_sample = timestamp + sample_step
            height, width = frame.shape[:2]
            scale = min(1.0, float(max_frame_side) / max(height, width))
            if scale < 1.0:
                small = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))),
                                   interpolation=cv2.INTER_AREA)
            else:
                small = frame
            small_height, small_width = small.shape[:2]
            rectangles, weights = hog.detectMultiScale(
                small, winStride=(8, 8), padding=(8, 8), scale=1.05
            )
            detections = []
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            for index, rect in enumerate(rectangles):
                x, y, box_width, box_height = [int(value) for value in rect]
                if box_height < 60 or box_width < 18 or box_width / max(1, box_height) > 1.3:
                    continue
                x1, y1 = max(0, x), max(0, y)
                x2, y2 = min(small_width, x + box_width), min(small_height, y + box_height)
                patch = hsv[y1:y2, x1:x2]
                histogram = cv2.calcHist([patch], [0, 1], None, [12, 8], [0, 180, 0, 256])
                cv2.normalize(histogram, histogram, alpha=1.0, norm_type=cv2.NORM_L1)
                weight = float(weights[index][0] if hasattr(weights[index], "__len__") else weights[index])
                detections.append({
                    "center_x": (x + box_width / 2.0) / max(1, small_width),
                    "center_y": (y + box_height / 2.0) / max(1, small_height),
                    "height_ratio": box_height / max(1, small_height),
                    "width_ratio": box_width / max(1, small_width),
                    "detector_score": weight,
                    "color_histogram": histogram.reshape(-1).tolist(),
                })
            frames.append({"time_seconds": timestamp, "detections": detections})
    except (AttributeError, TypeError, ValueError, cv2.error) as exc:
        return {
            "available": True, "detected": False, "method": "opencv-hog-failed",
            "reason": str(exc), "observations": [], "track_id": None,
            "track_quality_proxy": None, "identity_semantics": False,
        }
    finally:
        capture.release()

    tracks = _associate_detections(frames)
    chosen = _pick_dominant_track(tracks)
    custom_observations = (
        [{
            key: observation[key]
            for key in ("time_seconds", "center_x", "center_y", "height_ratio", "detector_score")
        } for observation in chosen["observations"]]
        if chosen is not None else []
    )
    norfair_shadow = None
    if norfair_shadow_enabled:
        try:
            norfair_shadow = _run_norfair_shadow(frames, custom_observations)
        except Exception as exc:
            # The optional association observer must never break the established HOG path.
            norfair_shadow = {
                "backend_id": "norfair.hog-association.2.3.0",
                "status": "failed",
                "items": [],
                "warnings": [f"Unexpected Norfair shadow error: {type(exc).__name__}: {exc}"],
                "metadata": {"sampled_frame_count": len(frames)},
            }
    if chosen is None:
        return {
            "available": True, "detected": False, "method": "opencv-hog-no-stable-track",
            "reason": "No person track had at least three detections across 1.5 seconds.",
            "sample_count": len(frames), "detection_count": sum(len(frame["detections"]) for frame in frames),
            "observations": [], "track_id": None, "track_quality_proxy": None,
            "identity_semantics": False, "norfair_shadow": norfair_shadow,
        }

    observations = [{
        key: observation[key] for key in ("time_seconds", "center_x", "center_y", "height_ratio", "detector_score")
    } for observation in chosen["observations"]]
    return {
        "available": True, "detected": True, "method": "opencv-hog-appearance-consistency-proxy",
        "reason": "A recurring person-shaped appearance track was detected; this is not identity recognition.",
        "sample_count": len(frames), "detection_count": sum(len(frame["detections"]) for frame in frames),
        "track_id": chosen["track_id"], "track_start_seconds": observations[0]["time_seconds"],
        "track_end_seconds": observations[-1]["time_seconds"], "track_span_seconds": chosen["span_seconds"],
        "track_quality_proxy": chosen["track_quality_proxy"], "average_detector_score": chosen["average_detector_score"],
        "observations": observations, "identity_semantics": False,
        "norfair_shadow": norfair_shadow,
    }


def subject_observation_near(observations: list[dict[str, Any]], target_seconds: float,
                             max_distance_seconds: float = 1.5) -> dict[str, Any] | None:
    """Return the closest track observation only when it is temporally near the target."""
    if not observations:
        return None
    nearest = min(observations, key=lambda obs: abs(float(obs["time_seconds"]) - float(target_seconds)))
    if abs(float(nearest["time_seconds"]) - float(target_seconds)) > max_distance_seconds:
        return None
    return nearest
