"""Resolve and validate local or YouTube-linked media before rendering."""
from __future__ import annotations
import argparse, json, math, shutil, subprocess, sys
from pathlib import Path
from urllib.parse import urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}
VIDEO_FORMAT = "bv*+ba/b"

class MediaSourceError(RuntimeError):
    """Raised when a media URL cannot be safely resolved or validated."""

def validate_youtube_url(url: str, label: str = "media") -> str:
    """Accept a single HTTPS YouTube video URL, not arbitrary URLs or playlists."""
    if not isinstance(url, str) or not url.strip():
        raise MediaSourceError(f"{label} URL is empty.")
    value = url.strip()
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise MediaSourceError(f"{label} URL is malformed.") from exc
    if parsed.scheme != "https" or host not in YOUTUBE_HOSTS:
        raise MediaSourceError(f"{label} must be an HTTPS YouTube URL (youtube.com or youtu.be).")
    if parsed.username or parsed.password:
        raise MediaSourceError(f"{label} URL must not contain embedded credentials.")
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

def _ffprobe(path: Path) -> dict:
    executable = shutil.which("ffprobe")
    if not executable:
        raise MediaSourceError("ffprobe is required. Install FFmpeg and ensure ffprobe is on PATH.")
    try:
        result = subprocess.run([executable, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], check=True, capture_output=True, text=True)
        info = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
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

def download_youtube(url: str, target_path: str | Path, kind: str) -> Path:
    """Download one YouTube video or extract its audio to a controlled input filename."""
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
                "yt-dlp is required for YouTube links. Install it with: "
                "python3 -m pip install --user -U yt-dlp"
            ) from exc
        command = [sys.executable, "-m", "yt_dlp"]
    command += ["--ignore-config", "--no-playlist", "--no-warnings", "--no-progress", "--quiet", "--force-overwrites", "-o", str(target.parent / f"{target.stem}.%(ext)s"), "--print", "after_move:filepath"]
    if kind == "music":
        command += ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"]
    else:
        command += ["-f", VIDEO_FORMAT, "--merge-output-format", "mp4", "--remux-video", "mp4"]
    command.append(url)
    print(f"[sources] Downloading YouTube {kind}...")
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
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

def parse_media_source_args(argv=None):
    parser = argparse.ArgumentParser(description="Render a Heyaa Phonk montage from local files or YouTube video links.")
    parser.add_argument("--video-url", help="YouTube video URL used as the source footage.")
    parser.add_argument("--music-url", help="YouTube video URL used as the Phonk soundtrack.")
    parser.add_argument("--reference-url", help="Optional YouTube video URL used for pacing reference.")
    return parser.parse_args(argv)

def prepare_media_sources(video_url, music_url, reference_url, video_path, music_path, reference_path):
    """Download supplied URLs, then validate all required media before rendering."""
    if video_url: video_url = validate_youtube_url(video_url, "video")
    if music_url: music_url = validate_youtube_url(music_url, "music")
    if reference_url: reference_url = validate_youtube_url(reference_url, "reference")
    resolved_video, resolved_music, resolved_reference = Path(video_path), Path(music_path), Path(reference_path)
    if video_url: resolved_video = download_youtube(video_url, resolved_video, "video")
    if music_url: resolved_music = download_youtube(music_url, resolved_music, "music")
    if reference_url: resolved_reference = download_youtube(reference_url, resolved_reference, "reference")
    validate_media_file(resolved_video, "video")
    validate_media_file(resolved_music, "music")
    if resolved_reference.is_file(): validate_media_file(resolved_reference, "reference")
    return str(resolved_video), str(resolved_music), str(resolved_reference)
