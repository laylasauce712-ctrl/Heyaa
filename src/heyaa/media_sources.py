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
# Bound source formats to 1080p landscape or 1080x1920 portrait. This avoids
# downloading enormous 1440p/4K originals when the output is 1080x1920.
SOURCE_VIDEO_FORMAT = (
    "bv*[height<=1080][width<=1920]+ba/b[height<=1080][width<=1920]"
    "/bv*[height<=1920][width<=1080]+ba/b[height<=1920][width<=1080]"
)
# Pacing references only need usable cut timing, so cap them at 720p / 720x1280.
REFERENCE_VIDEO_FORMAT = (
    "bv*[height<=720][width<=1280]+ba/b[height<=720][width<=1280]"
    "/bv*[height<=1280][width<=720]+ba/b[height<=1280][width<=720]"
)
VIDEO_DOWNLOAD_TIMEOUT_SECONDS = 2700
REFERENCE_DOWNLOAD_TIMEOUT_SECONDS = 900
MUSIC_DOWNLOAD_TIMEOUT_SECONDS = 900
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
    """Download a YouTube video/audio with visible progress and a hard timeout."""
    url = validate_youtube_url(url, kind)
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    path_report = target.parent / f".{target.stem}.{kind}.yt-dlp-path.txt"
    path_report.unlink(missing_ok=True)

    executable = shutil.which("yt-dlp")
    if executable:
        command = [executable]
    else:
        try:
            import yt_dlp  # noqa: F401
        except ImportError as exc:
            raise MediaSourceError(
                "yt-dlp is required for YouTube links. Install it with: python3 -m pip install -U \"yt-dlp[default]\""
            ) from exc
        command = [sys.executable, "-m", "yt_dlp"]
    command += [
        "--ignore-config", "--no-playlist", "--newline", "--progress", "--progress-delta", "1",
        "--force-ipv4", "--socket-timeout", "20", "--retries", "2", "--fragment-retries", "2",
        "--force-overwrites", "-o", str(target.parent / f"{target.stem}.%(ext)s"),
        "--print-to-file", "after_move:filepath", str(path_report),
    ]
    if kind == "music":
        timeout_seconds = MUSIC_DOWNLOAD_TIMEOUT_SECONDS
        command += ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"]
    elif kind == "reference":
        timeout_seconds = REFERENCE_DOWNLOAD_TIMEOUT_SECONDS
        command += ["-f", REFERENCE_VIDEO_FORMAT, "--merge-output-format", "mp4", "--remux-video", "mp4"]
    else:
        timeout_seconds = VIDEO_DOWNLOAD_TIMEOUT_SECONDS
        command += ["-f", SOURCE_VIDEO_FORMAT, "--merge-output-format", "mp4", "--remux-video", "mp4"]
    command.append(url)
    print(
        f"[sources] Downloading YouTube {kind}; live progress enabled "
        f"(timeout: {timeout_seconds}s; max format: "
        f"{'audio-only' if kind == 'music' else '720p' if kind == 'reference' else '1080p'})...",
        flush=True,
    )
    try:
        # Inherit stdout/stderr so progress and extractor errors stream immediately
        # to the terminal (and to a caller's tee logfile) instead of being hidden
        # in a captured buffer until the subprocess exits.
        result = subprocess.run(command, check=False, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise MediaSourceError(
            f"YouTube {kind} download timed out after {timeout_seconds}s. "
            "Read the live yt-dlp output above; if network/CDN access failed, use a permitted local file "
            "or a direct HTTPS media URL instead."
        ) from exc
    except OSError as exc:
        raise MediaSourceError(f"Could not start yt-dlp: {exc}") from exc

    try:
        if result.returncode != 0:
            raise MediaSourceError(
                f"YouTube {kind} download failed (yt-dlp exit code {result.returncode}). "
                "The exact network/extractor error is printed above."
            )
        if not path_report.is_file():
            raise MediaSourceError(
                f"yt-dlp exited successfully but did not report the downloaded {kind} path."
            )
        printed_paths = [line.strip() for line in path_report.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not printed_paths:
            raise MediaSourceError(f"yt-dlp wrote an empty output-path report for {kind}.")
        downloaded = Path(printed_paths[-1]).resolve()
        if downloaded.parent != target.parent.resolve():
            raise MediaSourceError("yt-dlp reported a path outside the project input directory.")
        if not downloaded.is_file() or downloaded.stat().st_size <= 0:
            raise MediaSourceError(f"yt-dlp reported a missing or empty file: {downloaded}")
        return downloaded
    finally:
        path_report.unlink(missing_ok=True)

def download_media_source(url: str, target_path: str | Path, kind: str) -> Path:
    """Route YouTube pages to yt-dlp and direct HTTPS media links to a bounded downloader."""
    _, host, value = _parsed_https_url(url, kind)
    if host in YOUTUBE_HOSTS:
        return download_youtube(value, target_path, kind)
    return download_direct_https(value, target_path, kind)


def parse_clip_count_options(value: str) -> tuple[int, ...]:
    """Parse explicit clip-count alternatives for comparison renders."""
    try:
        raw_values = [part.strip() for part in value.split(",")]
        if not raw_values or any(not part for part in raw_values):
            raise ValueError
        values = tuple(int(part) for part in raw_values)
    except (AttributeError, TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("Use comma-separated integers such as 8,12,16.") from exc
    if len(values) > 5:
        raise argparse.ArgumentTypeError("At most five clip-count alternatives are supported.")
    if len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("Clip-count alternatives must be distinct.")
    if any(count < 6 or count > 40 for count in values):
        raise argparse.ArgumentTypeError("Every clip count must be between 6 and 40.")
    return values


def parse_media_source_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Render a Heyaa Phonk montage from local files, direct HTTPS media links, or YouTube video links."
    )
    parser.add_argument("--video-url", help="HTTPS video URL (YouTube page or direct media URL) used as source footage.")
    parser.add_argument("--music-url", help="HTTPS audio URL (YouTube page or direct media URL) used as the soundtrack.")
    parser.add_argument("--reference-url", help="HTTPS video URL (YouTube page or direct media URL) used as the visual timing reference.")
    parser.add_argument(
        "--variants", type=int, choices=(1, 2, 3, 4, 5), default=3,
        help="Render 3 comparison variants by default (1–5 supported)."
    )
    parser.add_argument(
        "--clip-count", type=int, default=None,
        help="Use this exact number of motion clips (must be within params.json min_clips/max_clips)."
    )
    parser.add_argument(
        "--clip-count-options", type=parse_clip_count_options, default=None,
        help="Render one candidate per exact clip count, e.g. --variants 3 --clip-count-options 8,12,16."
    )
    parser.add_argument(
        "--same-source-progression", action="store_true", default=False,
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--variant-index", type=int, choices=(1, 2, 3, 4, 5), default=None,
        help=argparse.SUPPRESS
    )
    return parser.parse_args(argv)


def extract_reference_audio(reference_path: str | Path, music_path: str | Path) -> Path:
    """Extract and normalize the reference soundtrack as a high-quality MP3 for the renderer."""
    reference = Path(reference_path)
    target = Path(music_path)
    info = _ffprobe(reference)
    streams = info.get("streams", [])
    if not any(isinstance(stream, dict) and stream.get("codec_type") == "audio" for stream in streams):
        raise MediaSourceError(
            "The reference video has no audio track to use as music. Supply --music-url or a local input/phonk.mp3."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.reference-audio{target.suffix or '.mp3'}")
    temporary.unlink(missing_ok=True)
    try:
        command = [
            shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(reference), "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "44100",
            "-c:a", "libmp3lame", "-q:a", "0", str(temporary),
        ]
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=600)
        if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
            detail = (result.stderr or "").strip()[-1000:]
            raise MediaSourceError(f"Could not extract the reference soundtrack with FFmpeg. {detail}")
        validate_media_file(temporary, "music")
        temporary.replace(target)
        print(f"[sources] Using the reference video's own soundtrack: {target}", flush=True)
        return target
    except subprocess.TimeoutExpired as exc:
        raise MediaSourceError("Extracting audio from the reference video timed out.") from exc
    except OSError as exc:
        raise MediaSourceError(f"Could not extract reference audio: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


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
    if reference_url:
        resolved_reference = download_media_source(reference_url, resolved_reference, "reference")
    if music_url:
        resolved_music = download_media_source(music_url, resolved_music, "music")
    elif reference_url:
        # When a URL reference is supplied without a separate music URL, use its soundtrack.
        # Explicit --music-url always takes precedence.
        resolved_music = extract_reference_audio(resolved_reference, resolved_music)
    validate_media_file(resolved_video, "video")
    validate_media_file(resolved_music, "music")
    if resolved_reference.is_file():
        validate_media_file(resolved_reference, "reference")
    return str(resolved_video), str(resolved_music), str(resolved_reference)
