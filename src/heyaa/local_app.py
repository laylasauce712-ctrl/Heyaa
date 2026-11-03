"""Local-only Heyaa Studio server.

The UI is a thin localhost control surface over the existing FFmpeg renderer.
It adds no web framework or second rendering engine.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"
INPUT_ROOT = ROOT / "input"
OUTPUT_ROOT = ROOT / "output"
RUNS_ROOT = OUTPUT_ROOT / "runs"
RELEASES_ROOT = OUTPUT_ROOT / "releases"
BASE_SETTINGS = ROOT / "params.json"
LOCAL_SETTINGS = ROOT / "params.local.json"
HOST = "127.0.0.1"
PORT = 8765
MAX_JSON_BYTES = 32 * 1024
MAX_UPLOAD_BYTES = {
    "video": 2 * 1024 * 1024 * 1024,
    "music": 512 * 1024 * 1024,
    "reference": 2 * 1024 * 1024 * 1024,
}
ALLOWED_EXTENSIONS = {
    "video": {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"},
    "music": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"},
    "reference": {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"},
}
DEFAULT_MEDIA = {
    "video": "input/test_video.mp4",
    "music": "input/phonk.mp3",
    "reference": "input/reference.mp4",
}
EDIT_KEYS = {
    "duration_seconds", "speed", "layout_mode", "mirror_enabled",
    "reference_pacing", "subject_lock_enabled", "ending_skull_enabled",
    "impact_sfx_enabled",
}
AUDIO_KEYS = {"beat_sync", "beat_flash", "bass_boost", "music_loop"}
VIDEO_KEYS = {"ai_upscale_enabled"}

_STATE_LOCK = threading.RLock()
_ACTIVE_PROCESS: subprocess.Popen | None = None
_ACTIVE_STARTED_AT: str | None = None
_ACTIVE_LOG: Path | None = None


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _load_profile() -> tuple[dict[str, Any], str]:
    path = LOCAL_SETTINGS if LOCAL_SETTINGS.is_file() else BASE_SETTINGS
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{path.name} must contain a JSON object.")
    return data, path.name


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _validate_profile(config: dict[str, Any]) -> None:
    from src.heyaa.agents import settings_agent

    result = settings_agent(config)
    if result.status != "ok":
        details = "; ".join(result.findings) or "settings validation failed"
        raise ValueError(details)


def _save_profile(changes: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(changes, dict):
        raise ValueError("Settings payload must be an object.")
    config, _ = _load_profile()
    edit = config.setdefault("edit_settings", {})
    audio = config.setdefault("audio_settings", {})
    video = config.setdefault("video_settings", {})
    if not all(isinstance(section, dict) for section in (edit, audio, video)):
        raise ValueError("The settings sections are malformed.")
    incoming_edit = changes.get("edit_settings", {})
    incoming_audio = changes.get("audio_settings", {})
    incoming_video = changes.get("video_settings", {})
    for section_name, incoming, allowed, target in (
        ("edit_settings", incoming_edit, EDIT_KEYS, edit),
        ("audio_settings", incoming_audio, AUDIO_KEYS, audio),
        ("video_settings", incoming_video, VIDEO_KEYS, video),
    ):
        if not isinstance(incoming, dict):
            raise ValueError(f"{section_name} must be an object.")
        unknown = set(incoming) - allowed
        if unknown:
            raise ValueError(f"Unsupported {section_name} options: {', '.join(sorted(unknown))}.")
        target.update(incoming)
    _validate_profile(config)
    _atomic_json(LOCAL_SETTINGS, config)
    return {"settings_file": LOCAL_SETTINGS.name, "settings": config}


def _media_files() -> list[dict[str, Any]]:
    INPUT_ROOT.mkdir(parents=True, exist_ok=True)
    result = []
    for path in INPUT_ROOT.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        suffix = path.suffix.lower()
        slot = next((kind for kind, extensions in ALLOWED_EXTENSIONS.items() if suffix in extensions), None)
        if slot is None:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        result.append({
            "name": path.name,
            "path": f"input/{path.name}",
            "slot": slot,
            "size_bytes": size,
            "size_label": _format_bytes(size),
        })
    return sorted(result, key=lambda x: (x["slot"], x["name"].lower()))


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{amount:.1f} GB"


def _ai_upscale_status(config: dict[str, Any]) -> dict[str, Any]:
    video = config.get("video_settings", {})
    binary_value = video.get("ai_upscale_binary", "tools/realesrgan/realesrgan-ncnn-vulkan")
    model_dir_value = video.get("ai_upscale_model_dir", "tools/realesrgan/models")
    model_name = video.get("ai_upscale_model", "realesrgan-x4plus")
    scale = video.get("ai_upscale_scale", 2)
    binary = Path(binary_value)
    if not binary.is_absolute():
        binary = ROOT / binary
    model_dir = Path(model_dir_value) if model_dir_value else ROOT / "tools/realesrgan/models"
    if not model_dir.is_absolute():
        model_dir = ROOT / model_dir
    stem = f"{model_name}-x{scale}" if model_name == "realesr-animevideov3" else str(model_name)
    weights = [model_dir / f"{stem}.param", model_dir / f"{stem}.bin"]
    available = binary.is_file() and os.access(binary, os.X_OK) and all(p.is_file() for p in weights)
    return {
        "enabled": video.get("ai_upscale_enabled") is True,
        "available": available,
        "binary_exists": binary.is_file(),
        "model_weights_exist": all(p.is_file() for p in weights),
        "model": model_name,
        "scale": scale,
        "note": "Asset preflight only; a real neural-upscale render still needs visual verification.",
    }


def _run_report(run_dir: Path) -> dict[str, Any]:
    if not run_dir.is_dir():
        return {}
    manifest_path = run_dir / "edits_manifest.json"
    if manifest_path.is_file():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    report_path = run_dir / "agent_report.json"
    if report_path.is_file():
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _run_outputs(run_dir: Path) -> list[dict[str, Any]]:
    outputs = []
    if not run_dir.is_dir():
        return outputs
    for path in run_dir.rglob("*.mp4"):
        if not path.is_file() or path.is_symlink():
            continue
        if path.name != "preview.mp4" and not path.name.startswith("final_phonk"):
            continue
        try:
            relative = path.resolve().relative_to(RUNS_ROOT.resolve())
        except (OSError, ValueError):
            continue
        is_preview = path.name == "preview.mp4"
        report_path = path.parent / "agent_report.json"
        status = "preview" if is_preview else "ready_for_human_review"
        if not is_preview and report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                status = str(report.get("status") or status)
            except (OSError, json.JSONDecodeError):
                status = "report_unreadable"
        outputs.append({
            "path": str(Path("output") / "runs" / relative),
            "name": path.name,
            "folder": path.parent.name,
            "size_label": _format_bytes(path.stat().st_size),
            "status": status,
            "is_preview": is_preview,
            "can_approve": not is_preview and status == "ready_for_human_review",
        })
    return sorted(outputs, key=lambda x: x["path"])


def _read_events(run_dir: Path, limit: int = 36) -> list[dict[str, Any]]:
    records = []
    if not run_dir.is_dir():
        return records
    for path in run_dir.rglob("progress.jsonl"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            continue
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
    records.sort(key=lambda x: str(x.get("timestamp", "")))
    return records[-limit:]


def _release_list() -> list[dict[str, Any]]:
    result = []
    if not RELEASES_ROOT.is_dir():
        return result
    for manifest_path in RELEASES_ROOT.glob("*/*/release_manifest.json"):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            video_path = manifest_path.parent / "final_phonk.mp4"
            if not video_path.is_file():
                continue
            result.append({
                "path": str(video_path.relative_to(ROOT)),
                "run_id": data.get("source_run"),
                "folder": manifest_path.parent.name,
                "approved_at": data.get("approved_at_utc"),
                "size_label": _format_bytes(video_path.stat().st_size),
            })
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(result, key=lambda x: str(x.get("approved_at") or ""), reverse=True)[:8]


def _local_tool_status() -> dict[str, Any]:
    return {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "opencv": _opencv_available(),
    }


def _opencv_available() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except Exception:
        return False


def _state() -> dict[str, Any]:
    global _ACTIVE_PROCESS
    config, settings_file = _load_profile()
    with _STATE_LOCK:
        process = _ACTIVE_PROCESS
        running = process is not None and process.poll() is None
        exit_code = None if process is None or running else process.returncode
        started_at = _ACTIVE_STARTED_AT
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    run_dirs = sorted(
        (p for p in RUNS_ROOT.iterdir() if p.is_dir() and not p.is_symlink()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    latest = run_dirs[0] if run_dirs else None
    report = _run_report(latest) if latest else {}
    contact_sheet = latest / "contact_sheet.png" if latest else None
    sheet_url = (
        "/api/artifact?path=" + quote(str(contact_sheet.relative_to(ROOT)))
        if contact_sheet and contact_sheet.is_file() else None
    )
    outputs = _run_outputs(latest) if latest else []
    return {
        "project": "Heyaa",
        "mode": "local",
        "running": running,
        "process_id": process.pid if process else None,
        "exit_code": exit_code,
        "started_at": started_at,
        "settings_file": settings_file,
        "settings": config,
        "ai_upscale": _ai_upscale_status(config),
        "tools": _local_tool_status(),
        "media": _media_files(),
        "latest_run": str(latest.relative_to(ROOT)) if latest else None,
        "latest_status": report.get("status") or report.get("summary"),
        "latest_manifest": report if report.get("requested_edits") is not None else None,
        "contact_sheet": sheet_url,
        "events": _read_events(latest) if latest else [],
        "outputs": outputs,
        "releases": _release_list(),
        "run_history": [
            {
                "id": p.name,
                "status": (_run_report(p).get("status") or _run_report(p).get("summary") or "in progress"),
                "output_count": len(_run_outputs(p)),
            }
            for p in run_dirs[:6]
        ],
    }


def _validate_render_request(data: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    if not isinstance(data, dict):
        raise ValueError("Render request must be a JSON object.")
    config, _ = _load_profile()
    media_urls = {}
    for slot in ("video", "music", "reference"):
        value = data.get(f"{slot}_url", "")
        if not isinstance(value, str):
            raise ValueError(f"{slot}_url must be text.")
        media_urls[slot] = value.strip()
        if media_urls[slot]:
            from src.heyaa.media_sources import validate_media_url
            validate_media_url(media_urls[slot], slot)
    if media_urls["reference"] and data.get("reference_path"):
        raise ValueError("Choose either a local reference or a reference URL, not both.")
    if media_urls["video"] and data.get("video_path"):
        raise ValueError("Choose either a local source file or a source URL, not both.")
    if media_urls["music"] and data.get("music_path"):
        raise ValueError("Choose either a local soundtrack or a music URL, not both.")

    from src.heyaa.media_sources import validate_input_media_path, validate_media_file

    video_path = validate_input_media_path(
        str(data.get("video_path") or DEFAULT_MEDIA["video"]), "video"
    )
    music_path = validate_input_media_path(
        str(data.get("music_path") or DEFAULT_MEDIA["music"]), "music"
    )
    reference_path = validate_input_media_path(
        str(data.get("reference_path") or ""), "reference"
    )
    if not media_urls["video"]:
        validate_media_file(video_path, "video")
    if not media_urls["music"]:
        validate_media_file(music_path, "music")
    if reference_path and not media_urls["reference"]:
        validate_media_file(reference_path, "reference")

    edits = data.get("edits", 1)
    if isinstance(edits, bool) or not isinstance(edits, int) or edits not in (1, 2, 3, 4, 5):
        raise ValueError("Choose between 1 and 5 distinct edits.")
    preview = data.get("preview") is True
    if preview and edits != 1:
        raise ValueError("Preview mode is one edit only.")
    clip_count = data.get("clip_count")
    command = [sys.executable, str(ROOT / "src" / "agent_director.py")]
    command.extend(["--edits", str(edits)])
    command.extend(["--video-path", video_path, "--music-path", music_path, "--reference-path", reference_path])
    for slot, flag in (("video", "--video-url"), ("music", "--music-url"), ("reference", "--reference-url")):
        if media_urls[slot]:
            target = {
                "video": f"input/ui_link_source_{uuid.uuid4().hex[:10]}.mp4",
                "music": f"input/ui_link_music_{uuid.uuid4().hex[:10]}.mp3",
                "reference": f"input/ui_link_reference_{uuid.uuid4().hex[:10]}.mp4",
            }[slot]
            command[command.index("--video-path" if slot == "video" else "--music-path" if slot == "music" else "--reference-path") + 1] = str(ROOT / target)
            command.extend([flag, media_urls[slot]])
    if clip_count is not None:
        if isinstance(clip_count, bool) or not isinstance(clip_count, int):
            raise ValueError("clip_count must be an integer or null for Auto.")
        minimum = config["edit_settings"]["min_clips"]
        maximum = config["edit_settings"]["max_clips"]
        if not minimum <= clip_count <= maximum:
            raise ValueError(f"Motion clip count must be between {minimum} and {maximum}.")
        command.extend(["--clip-count", str(clip_count)])
    if preview:
        command.append("--preview")
    return command, {"edits": edits, "preview": preview, "video_path": video_path, "music_path": music_path,
                     "reference_path": reference_path, "clip_count": clip_count}


def _normalize_upload_slot(slot: str) -> str:
    """Map the UI's source slot onto the renderer's video media kind."""
    if slot not in {"source", "video", "music", "reference"}:
        raise ValueError("Upload slot must be source, music or reference.")
    return "video" if slot in {"source", "video"} else slot


def _parse_byte_range(value: str | None, size: int) -> tuple[int, int] | None:
    """Parse one HTTP bytes range; return inclusive bounds or None for a full response."""
    if value is None:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match or (not match.group(1) and not match.group(2)) or size <= 0:
        raise ValueError("Unsupported or unsatisfiable byte range.")
    left, right = match.groups()
    if not left:
        suffix = int(right)
        if suffix <= 0:
            raise ValueError("Unsupported or unsatisfiable byte range.")
        return max(0, size - suffix), size - 1
    start = int(left)
    end = int(right) if right else size - 1
    if start >= size or end < start:
        raise ValueError("Unsupported or unsatisfiable byte range.")
    return start, min(end, size - 1)


def _safe_artifact_path(value: str) -> Path:
    candidate = (ROOT / value).resolve(strict=True)
    allowed_roots = (RUNS_ROOT.resolve(), RELEASES_ROOT.resolve())
    if not any(candidate == base or base in candidate.parents for base in allowed_roots):
        raise ValueError("Only render and release artifacts can be opened from the Studio.")
    if not candidate.is_file():
        raise ValueError("Artifact is not a file.")
    if candidate.suffix.lower() not in {".mp4", ".png", ".jpg", ".jpeg", ".webp", ".json"}:
        raise ValueError("This artifact type is not available through the Studio.")
    return candidate


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "HeyaaStudio/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print("[studio]", format % args)

    def _local_request(self) -> bool:
        host = self.headers.get("Host", "")
        parsed = urlparse("//" + host)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            return False
        origin = self.headers.get("Origin")
        if origin:
            if urlparse(origin).hostname not in {"127.0.0.1", "localhost"}:
                return False
        site = self.headers.get("Sec-Fetch-Site")
        if site and site not in {"same-origin", "none"}:
            return False
        return True

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

    def _read_json(self) -> dict[str, Any]:
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ValueError("Expected application/json.")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_JSON_BYTES:
            raise ValueError("Request body is empty or too large.")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Request body must be an object.")
        return value

    def do_GET(self) -> None:
        if not self._local_request():
            self._json(403, {"error": "The Studio only accepts localhost requests."})
            return
        route = urlparse(self.path)
        if route.path == "/":
            path = WEB_ROOT / "index.html"
            return self._serve_static(path)
        if route.path.startswith("/assets/"):
            relative = route.path.removeprefix("/assets/")
            path = (WEB_ROOT / relative).resolve()
            try:
                path.relative_to(WEB_ROOT.resolve())
            except ValueError:
                return self._json(404, {"error": "Asset not found."})
            return self._serve_static(path)
        if route.path == "/api/state":
            try:
                return self._json(200, _state())
            except Exception as exc:
                return self._json(500, {"error": str(exc)})
        if route.path == "/api/artifact":
            query = parse_qs(route.query)
            value = query.get("path", [""])[0]
            try:
                path = _safe_artifact_path(value)
            except (OSError, ValueError) as exc:
                return self._json(404, {"error": str(exc)})
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            try:
                size = path.stat().st_size
                try:
                    selected_range = _parse_byte_range(self.headers.get("Range"), size)
                except ValueError:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                start, end = selected_range if selected_range else (0, max(0, size - 1))
                length = max(0, end - start + 1)
                self.send_response(206 if selected_range else 200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                if selected_range:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with path.open("rb") as handle:
                    handle.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = handle.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except OSError:
                return
            return
        self._json(404, {"error": "Not found."})

    def _serve_static(self, path: Path) -> None:
        if not path.is_file():
            return self._json(404, {"error": "Studio asset not found."})
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), content_type + ("; charset=utf-8" if content_type.startswith(("text/", "application/javascript")) else ""))

    def do_POST(self) -> None:
        if not self._local_request():
            self._json(403, {"error": "The Studio only accepts localhost requests."})
            return
        route = urlparse(self.path)
        try:
            if route.path == "/api/settings":
                result = _save_profile(self._read_json())
                return self._json(200, {"ok": True, **result})
            if route.path == "/api/render":
                data = self._read_json()
                command, summary = _validate_render_request(data)
                return self._start_render(command, summary)
            if route.path == "/api/approve":
                data = self._read_json()
                video = data.get("video")
                if not isinstance(video, str) or not video:
                    raise ValueError("Select one render to approve.")
                from src.heyaa.release import approve_release
                result = approve_release(
                    video, confirm=data.get("confirm") is True, output_root=OUTPUT_ROOT,
                )
                return self._json(200, {"ok": True, "release": result})
            if route.path == "/api/upload":
                return self._upload(route.query)
            return self._json(404, {"error": "Not found."})
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:
            return self._json(500, {"error": f"Studio request failed: {exc}"})

    def _start_render(self, command: list[str], summary: dict[str, Any]) -> None:
        global _ACTIVE_PROCESS, _ACTIVE_STARTED_AT, _ACTIVE_LOG
        with _STATE_LOCK:
            if _ACTIVE_PROCESS is not None and _ACTIVE_PROCESS.poll() is None:
                return self._json(409, {"error": "A render is already running."})
            OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
            log_path = OUTPUT_ROOT / "studio-render.log"
            handle = log_path.open("a", encoding="utf-8")
            environment = os.environ.copy()
            environment["HEYAA_PARAMS_PATH"] = str(LOCAL_SETTINGS if LOCAL_SETTINGS.is_file() else BASE_SETTINGS)
            try:
                process = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    env=environment,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
            except OSError:
                handle.close()
                raise
            handle.close()
            _ACTIVE_PROCESS = process
            _ACTIVE_STARTED_AT = datetime.now(timezone.utc).isoformat()
            _ACTIVE_LOG = log_path
        self._json(202, {"ok": True, "started": True, "process_id": process.pid, "request": summary})

    def _upload(self, query_string: str) -> None:
        query = parse_qs(query_string)
        slot = _normalize_upload_slot(query.get("slot", [""])[0])
        raw_name = self.headers.get("X-Filename", "upload")
        filename = Path(raw_name.replace("\\", "/")).name
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS[slot]:
            raise ValueError(f"Unsupported {slot} file extension: {suffix or '(none)'}.")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_UPLOAD_BYTES[slot]:
            raise ValueError(f"{slot.capitalize()} upload must be between 1 byte and {_format_bytes(MAX_UPLOAD_BYTES[slot])}.")
        INPUT_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = INPUT_ROOT / f".ui-upload-{uuid.uuid4().hex}.part"
        try:
            remaining = length
            with temporary.open("wb") as handle:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Upload ended before the declared content length.")
                    handle.write(chunk)
                    remaining -= len(chunk)
            from src.heyaa.media_sources import validate_media_file
            validate_media_file(temporary, slot)
            name = f"ui_{slot}_{uuid.uuid4().hex[:10]}{suffix}"
            target = INPUT_ROOT / name
            os.replace(temporary, target)
            self._json(201, {"ok": True, "file": {"name": name, "path": f"input/{name}", "slot": slot}})
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


def serve(host: str = HOST, port: int = PORT) -> None:
    if host != "127.0.0.1":
        raise ValueError("Heyaa Studio must bind to 127.0.0.1 only.")
    server = ThreadingHTTPServer((host, port), StudioHandler)
    server.daemon_threads = True
    print(f"Heyaa Studio running locally: http://{host}:{port}", flush=True)
    print("Press Ctrl+C to stop the Studio server. Render jobs continue in the terminal process.", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping Heyaa Studio server.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
