"""Resolve and validate local, direct-HTTPS, or YouTube-linked media before rendering."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}
VIDEO_FORMAT = "bv*+ba/b"
DOWNLOAD_TIMEOUT_SECONDS = 180
DIRECT_CONNECT_TIMEOUT_SECONDS = 25
MAX_DIRECT_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024


class MediaSourceError(RuntimeError):
    """Raised when a media URL cannot be safely resolved or validated."""


def _parsed_https_url(url: str, label: str = "media"):
    if not isinstance(url, str) or not url.strip():
        raise MediaSourceError(f"{label} URL is empty.")
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise MediaSourceError(f"{label} URL is malformed.") from exc
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise MediaSourceError(f"{label} URL must be HTTPS and must not contain embedded credentials.")
    return parsed, host, url.strip()


def validate_youtube_url(url: str, label: str = "media") -> str:
    """Accept a single HTTPS YouTube video URL, not arbitrary URLs or playlists."""
    parsed, host, value = _parsed_https_url(url, label)
    if host not in YOUTUBE_HOSTS:
        raise MediaSourceError(f"{label} is not a recognized YouTube URL.")
    path = parsed.path.strip("/")
    valid = False
    if host in {"youtu.be", "www.youtu.be"}:
        valid = bool(path)
    elif path == "watch":
        valid = any(part.startswith("v=") and len(part) > 2 for part in parsed.query.split("&"))
    elif path.startswith(("shorts/", "live/", "embed/")):
        valid = len(path.split("/")) == 2 and bool(path.split("/")[1])
    if not valid:
        raise MediaSourceError(f"{label} must link to one YouTube video (watch, shorts, live, embed, or youtu.be).")
    return value


def validate_media_url(url: str, label: str = "media") -> str:
    """Accept a YouTube video page or a direct HTTPS media URL."""
    parsed, host, value = _parsed_https_url(url, label)
    if host in YOUTUBE_HOSTS:
        return validate_youtube_url(value, label)
    if not parsed.path or parsed.path == "/":
        raise MediaSourceError(f"{label} direct URL must point to a media resource.")
    return value


def _ffprobe(path: Path) -> dict:
    executable = shutil.which("ffprobe")
    if not executable:
        raise MediaSourceError("ffprobe is required. Install FFmpeg and ensure ffprobe is on PATH.")
    try:
        result = subprocess.run(
            [executable, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        info = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise MediaSourceError(f"Could not inspect media file {path}: {exc}") from exc
    if not isinstance(info, dict):
        raise MediaSourceError(f"ffprobe returned invalid metadata for {path}.")
    return info


def validate_media_file(path_value: str | Path, kind: str) -> Path:
    """Require a non-empty media file with the expected stream and a positive duration."""
    path = Path(path_value)
    if not path.is_file() or path.stat().st_size <= 0:
        raise MediaSourceError(f"Required {kind} file is missing or empty: {path}")
    info = _ffprobe(path)
    streams = info.get("streams", [])
    if not isinstance(streams, list):
        raise MediaSourceError(f"ffprobe returned invalid streams for {path}.")
    stream_types = {stream.get("codec_type") for stream in streams if isinstance(stream, dict)}
    if kind in {"video", "reference"} and "video" not in stream_types:
        raise MediaSourceError(f"{kind.capitalize()} file has no video stream: {path}")
    if kind == "music" and "audio" not in stream_types:
        raise MediaSourceError(f"Music file has no audio stream: {path}")
    try:
        duration = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError, AttributeError):
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        raise MediaSourceError(f"{kind.capitalize()} file has no valid positive duration: {path}")
    print(f"[sources] Validated {kind}: {path} ({duration:.2f}s; streams={','.join(sorted(stream_types))})")
    return path


def download_direct_https(url: str, target_path: str | Path, kind: str) -> Path:
    """Download a direct HTTPS resource with bounded size and explicit network timeouts."""
    parsed, host, value = _parsed_https_url(url, kind)
    if host in YOUTUBE_HOSTS:
        raise MediaSourceError("YouTube pages must be handled by the YouTube downloader.")
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    request = Request(value, headers={"User-Agent": "HeyaaMediaSource/1.0", "Accept": "video/*,audio/*,application/octet-stream;q=0.9"})
    print(f"[sources] Downloading direct HTTPS {kind} from {host} (max 2 GiB)...", flush=True)
    total = 0
    try:
        with urlopen(request, timeout=DIRECT_CONNECT_TIMEOUT_SECONDS) as response, temporary.open("wb") as output:
            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and not any(token in content_type for token in ("video/", "audio/", "application/octet-stream", "application/mp4", "application/x-mpegurl")):
                raise MediaSourceError(f"Direct {kind} URL returned a non-media content type: {content_type}.")
            length_header = response.headers.get("Content-Length")
            if length_header:
                try:
                    if int(length_header) > MAX_DIRECT_DOWNLOAD_BYTES:
                        raise MediaSourceError("Direct media file exceeds the 2 GiB download limit.")
                except ValueError:
                    pass
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DIRECT_DOWNLOAD_BYTES:
                    raise MediaSourceError("Direct media file exceeded the 2 GiB download limit.")
                output.write(chunk)
        if total <= 0:
            raise MediaSourceError(f"Direct {kind} download returned an empty file.")
        temporary.replace(target)
        return target
    except MediaSourceError:
        temporary.unlink(missing_ok=True)
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        raise MediaSourceError(f"Direct {kind} download failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def download_youtube(url: str, target_path: str | Path, kind: str) -> Path:
    """Download a YouTube video/audio with a hard timeout so runs cannot hang forever."""
    url = validate_youtube_url(url, kind)
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    executable = shutil.which("yt-dlp")
    if executable:
        command = [executable]
    else:
        try:
            import yt_dlp  # noqa: F401
        except ImportError as exc:
            raise MediaSourceError(
                "yt-dlp is required for YouTube links. Install it with: python3 -m pip install -U yt-dlp"
            ) from exc
        command = [sys.executable, "-m", "yt_dlp"]
    command += [
        "--ignore-config", "--no-playlist", "--no-warnings", "--no-progress", "--quiet",
        "--socket-timeout", "20", "--retries", "2", "--fragment-retries", "2",
        "--force-overwrites", "-o", str(target.parent / f"{target.stem}.%(ext)s"),
        "--print", "after_move:filepath",
    ]
    if kind == "music":
        command += ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"]
    else:
        command += ["-f", VIDEO_FORMAT, "--merge-output-format", "mp4", "--remux-video", "mp4"]
    command.append(url)
    print(f"[sources] Downloading YouTube {kind} (timeout: {DOWNLOAD_TIMEOUT_SECONDS}s)...", flush=True)
    try:
        result = subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaSourceError(
            f"YouTube {kind} download timed out after {DOWNLOAD_TIMEOUT_SECONDS}s. "
            "The source may be blocked or the connection may be stalled; use a direct HTTPS media URL or a local file."
        ) from exc
    except OSError as exc:
        raise MediaSourceError(f"Could not start yt-dlp: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "yt-dlp returned a non-zero exit code").strip()
        raise MediaSourceError(f"Could not download YouTube {kind}: {detail[-1400:]}")
    printed_paths = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if not printed_paths:
        raise MediaSourceError(f"yt-dlp finished without reporting the downloaded {kind} path.")
    downloaded = Path(printed_paths[-1]).resolve()
    if downloaded.parent != target.parent.resolve():
        raise MediaSourceError("yt-dlp reported a path outside the project input directory.")
    if not downloaded.is_file() or downloaded.stat().st_size <= 0:
        raise MediaSourceError(f"yt-dlp reported a missing or empty file: {downloaded}")
    return downloaded


def download_media_source(url: str, target_path: str | Path, kind: str) -> Path:
    """Route YouTube pages to yt-dlp and direct HTTPS media links to a bounded downloader."""
    _, host, value = _parsed_https_url(url, kind)
    if host in YOUTUBE_HOSTS:
        return download_youtube(value, target_path, kind)
    return download_direct_https(value, target_path, kind)


def parse_media_source_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Render a Heyaa Phonk montage from local files, direct HTTPS media links, or YouTube video links."
    )
    parser.add_argument("--video-url", help="HTTPS video URL (YouTube page or direct media URL) used as source footage.")
    parser.add_argument("--music-url", help="HTTPS audio URL (YouTube page or direct media URL) used as the soundtrack.")
    parser.add_argument("--reference-url", help="Optional HTTPS video URL (YouTube page or direct media URL) used for pacing reference.")
    return parser.parse_args(argv)


def prepare_media_sources(video_url, music_url, reference_url, video_path, music_path, reference_path):
    """Download supplied URLs, then validate all required media before rendering."""
    if video_url:
        video_url = validate_media_url(video_url, "video")
    if music_url:
        music_url = validate_media_url(music_url, "music")
    if reference_url:
        reference_url = validate_media_url(reference_url, "reference")
    resolved_video, resolved_music, resolved_reference = Path(video_path), Path(music_path), Path(reference_path)
    if video_url:
        resolved_video = download_media_source(video_url, resolved_video, "video")
    if music_url:
        resolved_music = download_media_source(music_url, resolved_music, "music")
    if reference_url:
        resolved_reference = download_media_source(reference_url, resolved_reference, "reference")
    validate_media_file(resolved_video, "video")
    validate_media_file(resolved_music, "music")
    if resolved_reference.is_file():
        validate_media_file(resolved_reference, "reference")
    return str(resolved_video), str(resolved_music), str(resolved_reference)
