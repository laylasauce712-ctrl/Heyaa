"""Pure cloud-boundary validation shared by the API and unit tests."""
from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse

from src.heyaa.media_sources import (
    MediaSourceError,
    TIKTOK_HOSTS,
    YOUTUBE_HOSTS,
    validate_tiktok_url,
    validate_youtube_url,
)

MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
MAX_MUSIC_BYTES = 512 * 1024 * 1024

SLOT_EXTENSIONS = {
    "video": {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".m4v": "video/x-m4v",
    },
    "reference": {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".m4v": "video/x-m4v",
    },
    "music": {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
    },
}


class CloudInputError(ValueError):
    """A user-supplied cloud upload or media reference violates the API contract."""


def validate_upload_metadata(slot: str, filename: str, content_type: str,
                             size_bytes: int) -> tuple[str, int]:
    if slot not in SLOT_EXTENSIONS:
        raise CloudInputError("Unsupported upload slot.")
    if not isinstance(filename, str) or not filename or len(filename) > 180:
        raise CloudInputError("Filename must contain 1 to 180 characters.")
    normalized = filename.replace("\\", "/")
    safe_name = PurePosixPath(normalized).name
    if safe_name != normalized or safe_name in {"", ".", ".."}:
        raise CloudInputError("Filename must not contain a path.")
    suffix = PurePosixPath(safe_name).suffix.lower()
    expected_type = SLOT_EXTENSIONS[slot].get(suffix)
    if not expected_type:
        raise CloudInputError(f"Unsupported {slot} file extension.")
    actual_type = content_type.split(";", 1)[0].strip().lower() if isinstance(content_type, str) else ""
    if actual_type != expected_type:
        raise CloudInputError("Content-Type does not match the selected file extension.")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes <= 0:
        raise CloudInputError("File size must be a positive integer.")
    limit = MAX_MUSIC_BYTES if slot == "music" else MAX_VIDEO_BYTES
    if size_bytes > limit:
        raise CloudInputError(f"File exceeds the {limit // (1024 * 1024)} MiB {slot} limit.")
    return suffix, limit


def object_key_belongs_to_owner(object_key: str, owner_key: str) -> bool:
    if not isinstance(object_key, str) or not object_key:
        return False
    prefix = f"uploads/{owner_key}/"
    parts = PurePosixPath(object_key).parts
    return object_key.startswith(prefix) and ".." not in parts and len(parts) == 3


def validate_platform_url(url: str, slot: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise CloudInputError(f"{slot} URL must be a public HTTPS YouTube or TikTok link.")
    host = (parsed.hostname or "").lower()
    try:
        if host in YOUTUBE_HOSTS:
            return validate_youtube_url(url, slot)
        if host in TIKTOK_HOSTS:
            return validate_tiktok_url(url, slot)
    except MediaSourceError as exc:
        raise CloudInputError(str(exc)) from exc
    raise CloudInputError(
        f"{slot} URL host is not allowed. Upload a file or use a supported YouTube/TikTok post URL."
    )
