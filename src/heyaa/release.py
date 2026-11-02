"""Explicit user approval for technically verified Heyaa render artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReleaseApprovalError(RuntimeError):
    """Raised when a render cannot be promoted to an approved local release."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseApprovalError(f"Could not read {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseApprovalError(f"{label} must contain a JSON object.")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_media(path: Path) -> dict[str, Any]:
    command = [
        shutil.which("ffprobe") or "ffprobe",
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseApprovalError(f"Could not inspect the render with ffprobe: {exc}") from exc
    if result.returncode != 0:
        raise ReleaseApprovalError(
            f"ffprobe rejected the render (exit {result.returncode}): {(result.stderr or '')[-1000:]}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseApprovalError("ffprobe returned malformed JSON.") from exc
    if not isinstance(payload, dict):
        raise ReleaseApprovalError("ffprobe returned an unexpected media structure.")
    return payload


def _rate(value: Any) -> float | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    numerator, denominator = value.split("/", 1)
    try:
        top, bottom = float(numerator), float(denominator)
    except ValueError:
        return None
    if bottom == 0:
        return None
    result = top / bottom
    return result if result > 0 else None


def _verify_render(video_path: Path, report: dict[str, Any], edl: dict[str, Any]) -> dict[str, Any]:
    results = report.get("results")
    if not isinstance(results, dict):
        raise ReleaseApprovalError("Agent report has no structured results object.")
    inspector = results.get("inspector")
    exporter = results.get("export_storage")
    if not isinstance(inspector, dict) or inspector.get("status") != "ok":
        raise ReleaseApprovalError("Inspector did not report status=ok; this render cannot be approved.")
    if not isinstance(exporter, dict) or exporter.get("status") != "ok":
        raise ReleaseApprovalError("Export Storage did not report status=ok; this render cannot be approved.")
    if report.get("status") != "ready_for_human_review":
        raise ReleaseApprovalError(
            f"Director status is {report.get('status')!r}, not ready_for_human_review."
        )

    fps_num, fps_den = edl.get("fps_num"), edl.get("fps_den")
    total_frames = edl.get("total_frames")
    width, height = edl.get("width"), edl.get("height")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
           for value in (fps_num, fps_den, total_frames, width, height)):
        raise ReleaseApprovalError("EDL is missing valid frame rate, frame count or dimensions.")
    fps = fps_num / fps_den
    video_items = edl.get("video")
    if not isinstance(video_items, list) or not video_items:
        raise ReleaseApprovalError("EDL contains no video timeline.")
    final_freeze = video_items[-1]
    if not isinstance(final_freeze, dict) or final_freeze.get("type") != "freeze":
        raise ReleaseApprovalError("EDL does not end with an explicit final freeze.")
    if final_freeze.get("effect") != "phonk-freeze":
        raise ReleaseApprovalError("EDL final freeze is not the configured Phonk ending freeze.")
    freeze_frames = final_freeze.get("dur_f")
    freeze_start = final_freeze.get("start_f")
    if (isinstance(freeze_frames, bool) or not isinstance(freeze_frames, int) or
            isinstance(freeze_start, bool) or not isinstance(freeze_start, int) or
            freeze_frames <= 0 or freeze_start + freeze_frames != total_frames):
        raise ReleaseApprovalError("EDL final freeze frame boundaries are invalid.")
    freeze_seconds = freeze_frames / fps
    if abs(freeze_seconds - 2.0) > (0.5 / fps + 1e-6):
        raise ReleaseApprovalError(
            f"EDL final freeze is {freeze_seconds:.6f}s, not the required 2.0 seconds."
        )
    if not video_path.is_file() or video_path.stat().st_size <= 0:
        raise ReleaseApprovalError("Final video is missing or empty.")

    probe = _probe_media(video_path)
    streams = probe.get("streams", [])
    if not isinstance(streams, list):
        raise ReleaseApprovalError("ffprobe did not return a streams list.")
    video_stream = next((x for x in streams if isinstance(x, dict) and x.get("codec_type") == "video"), None)
    audio_stream = next((x for x in streams if isinstance(x, dict) and x.get("codec_type") == "audio"), None)
    if video_stream is None:
        raise ReleaseApprovalError("Final render has no video stream.")
    if audio_stream is None:
        raise ReleaseApprovalError("Final render has no audio stream.")
    actual_width, actual_height = video_stream.get("width"), video_stream.get("height")
    if actual_width != width or actual_height != height:
        raise ReleaseApprovalError(
            f"Final render is {actual_width}x{actual_height}; EDL requires {width}x{height}."
        )
    actual_fps = _rate(video_stream.get("avg_frame_rate")) or _rate(video_stream.get("r_frame_rate"))
    if actual_fps is None or abs(actual_fps - fps) > 0.1:
        raise ReleaseApprovalError(
            f"Final render FPS is {actual_fps!r}; EDL requires {fps:.6f}."
        )
    expected_duration = total_frames / fps
    try:
        actual_duration = float(probe.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        raise ReleaseApprovalError("ffprobe did not report a valid final duration.") from None
    if not abs(actual_duration - expected_duration) <= max(1.0 / fps, 0.02):
        raise ReleaseApprovalError(
            f"Final duration is {actual_duration:.6f}s; EDL requires {expected_duration:.6f}s."
        )
    return {
        "width": width,
        "height": height,
        "fps": round(fps, 6),
        "duration_seconds": round(actual_duration, 6),
        "final_freeze_seconds": round(freeze_seconds, 6),
        "video_codec": video_stream.get("codec_name"),
        "audio_codec": audio_stream.get("codec_name"),
        "file_size_bytes": video_path.stat().st_size,
    }


def approve_release(
    video: str | Path,
    *,
    confirm: bool = False,
    output_root: str | Path = "output",
) -> dict[str, Any]:
    """Copy one user-approved, technically verified run artifact into output/releases."""
    if confirm is not True:
        raise ReleaseApprovalError("Explicit user approval is required; rerun with --confirm.")
    root = Path(output_root).resolve()
    runs_root = (root / "runs").resolve()
    releases_root = root / "releases"
    try:
        source_video = Path(video).resolve(strict=True)
        relative = source_video.relative_to(runs_root)
    except (OSError, ValueError) as exc:
        raise ReleaseApprovalError("The selected video must be an existing file under output/runs/.") from exc
    if source_video.suffix.lower() != ".mp4" or not source_video.is_file():
        raise ReleaseApprovalError("Only a verified MP4 render can be approved.")
    if len(relative.parts) < 2:
        raise ReleaseApprovalError("The selected MP4 must belong to a timestamped run directory.")

    source_dir = source_video.parent
    report_path = source_dir / "agent_report.json"
    edl_path = source_dir / "edit_decision_list.json"
    if not report_path.is_file() or not edl_path.is_file():
        raise ReleaseApprovalError("The selected render must have agent_report.json and edit_decision_list.json beside it.")
    report = _read_json(report_path, "agent_report.json")
    edl = _read_json(edl_path, "edit_decision_list.json")
    technical = _verify_render(source_video, report, edl)
    digest = _sha256(source_video)

    run_id = relative.parts[0]
    item_name = source_dir.name if source_dir.name.startswith("edit_") else "primary"
    release_parent = releases_root / run_id
    release_parent.mkdir(parents=True, exist_ok=True)
    destination = release_parent / item_name
    if destination.exists():
        raise ReleaseApprovalError(f"An approved release already exists at {destination}; it will not be overwritten.")

    staging = Path(tempfile.mkdtemp(prefix=f".{item_name}.pending-", dir=release_parent))
    try:
        staged_video = staging / "final_phonk.mp4"
        shutil.copy2(source_video, staged_video)
        shutil.copy2(report_path, staging / "agent_report.json")
        shutil.copy2(edl_path, staging / "edit_decision_list.json")
        manifest = {
            "version": 1,
            "user_approved": True,
            "approval_method": "explicit_local_cli_confirmation",
            "approved_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_run": run_id,
            "source_relative_path": str(relative),
            "video_sha256": digest,
            "technical_verification": technical,
        }
        manifest_path = staging / "release_manifest.json"
        temporary_manifest = staging / ".release_manifest.json.tmp"
        temporary_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        os.replace(temporary_manifest, manifest_path)
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "status": "approved",
        "release_dir": str(destination),
        "video": str(destination / "final_phonk.mp4"),
        "manifest": str(destination / "release_manifest.json"),
        "sha256": digest,
        "technical_verification": technical,
    }
