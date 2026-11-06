"""Low-cost FFmpeg visual diagnostics for sampled export frames.

These measurements flag likely blur, very dark output and unintended long
still frames. They do not judge aesthetics, subject identity or composition.
"""
from __future__ import annotations

import math
import re
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return float(ordered[index])


def analyze_visual_quality(
    media_path: str,
    duration_seconds: float,
    *,
    final_freeze_seconds: float = 2.0,
    sample_fps: float = 5.0,
    max_width: int = 320,
) -> dict:
    """Sample a finished video and return conservative visual-risk indicators."""
    result = {
        "status": "unavailable",
        "method": "ffmpeg-sampled-blur-signalstats-freezedetect",
        "sample_fps": sample_fps,
        "sample_count": 0,
        "blur_p50": None,
        "blur_p90": None,
        "dark_sample_ratio": None,
        "unintended_freeze_intervals": [],
        "warnings": [],
        "measurement_errors": [],
        "aesthetic_quality_assessed": False,
        "face_or_identity_assessed": False,
    }
    if not isinstance(media_path, str) or not media_path.strip():
        result["measurement_errors"].append("media_path_invalid")
        return result
    try:
        duration = float(duration_seconds)
        final_freeze = float(final_freeze_seconds)
        rate = float(sample_fps)
        width = int(max_width)
    except (TypeError, ValueError):
        result["measurement_errors"].append("settings_invalid")
        return result
    if (
        not math.isfinite(duration) or duration <= 0
        or not math.isfinite(final_freeze) or not 0 <= final_freeze < duration
        or not math.isfinite(rate) or not 1 <= rate <= 12
        or width < 96
    ):
        result["measurement_errors"].append("settings_out_of_range")
        return result
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        result["measurement_errors"].append("ffmpeg_unavailable")
        return result

    try:
        filters = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True, text=True, check=False, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        result["measurement_errors"].append("ffmpeg_filter_probe_failed")
        return result
    if filters.returncode != 0:
        result["measurement_errors"].append("ffmpeg_filter_probe_failed")
        return result
    filter_names = set(re.findall(r"\b([a-z][a-z0-9_]*)\s{2,}", filters.stdout))
    available = {
        name for name in ("metadata", "signalstats", "blurdetect", "freezedetect")
        if name in filter_names
    }
    if "metadata" not in available or not ({"signalstats", "blurdetect", "freezedetect"} & available):
        result["measurement_errors"].append("visual_metadata_filters_unavailable")
        return result

    metadata_handle = tempfile.NamedTemporaryFile(prefix="heyaa-visual-", suffix=".txt", delete=False)
    metadata_path = Path(metadata_handle.name)
    metadata_handle.close()
    try:
        chain = [f"fps={rate:g}", f"scale={width}:-2:flags=fast_bilinear"]
        if "blurdetect" in available:
            chain.append("blurdetect")
        if "signalstats" in available:
            chain.append("signalstats")
        if "freezedetect" in available:
            chain.append("freezedetect=n=-60dB:d=0.75")
        chain.append(f"metadata=mode=print:file={metadata_path}")
        command = [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "info",
            "-i", media_path, "-vf", ",".join(chain),
            "-an", "-sn", "-dn", "-f", "null", "-",
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=180,
            )
        except subprocess.TimeoutExpired:
            result["measurement_errors"].append("visual_sample_timeout")
            return result
        except OSError as exc:
            result["measurement_errors"].append(f"visual_sample_failed:{type(exc).__name__}")
            return result
        if completed.returncode != 0:
            result["measurement_errors"].append("visual_sample_ffmpeg_failed")
            return result

        text = metadata_path.read_text(encoding="utf-8", errors="replace") if metadata_path.is_file() else ""
        blur_values = []
        luma_values = []
        freeze_intervals = []
        current_timestamp = 0.0
        frame_pattern = re.compile(r"^frame:\s*\d+\s+pts:\s*\S+\s+pts_time:([0-9.+-]+)", re.MULTILINE)
        for line in text.splitlines():
            frame_match = frame_pattern.search(line)
            if frame_match:
                try:
                    current_timestamp = float(frame_match.group(1))
                except ValueError:
                    current_timestamp = 0.0
            if "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            try:
                value = float(raw_value.strip())
            except ValueError:
                continue
            if not math.isfinite(value):
                continue
            if key.endswith("lavfi.blur"):
                blur_values.append(value)
            elif key.endswith("lavfi.signalstats.YAVG"):
                luma_values.append(value)
            elif key.endswith("lavfi.freezedetect.freeze_duration") and value >= 0.75:
                freeze_intervals.append({
                    "start_seconds": round(max(0.0, current_timestamp - value), 3),
                    "duration_seconds": round(value, 3),
                })

        if not blur_values and not luma_values and not freeze_intervals:
            result["measurement_errors"].append("visual_samples_contained_no_supported_metrics")
            return result
        result["sample_count"] = max(len(blur_values), len(luma_values))
        if blur_values:
            result["blur_p50"] = round(statistics.median(blur_values), 3)
            result["blur_p90"] = round(float(_percentile(blur_values, 0.90)), 3)
        if luma_values:
            dark_ratio = sum(value < 35.0 for value in luma_values) / len(luma_values)
            result["dark_sample_ratio"] = round(dark_ratio, 4)

        intentional_start = duration - final_freeze - 0.20
        for interval in freeze_intervals:
            if interval["start_seconds"] < intentional_start:
                result["unintended_freeze_intervals"].append(interval)

        if result["blur_p90"] is not None and result["blur_p90"] >= 12.0:
            result["warnings"].append("Many sampled frames show elevated blur; check source sharpness and motion blur.")
        if result["dark_sample_ratio"] is not None and result["dark_sample_ratio"] >= 0.65:
            result["warnings"].append("Most sampled frames are very dark; check visibility on a phone display.")
        if result["unintended_freeze_intervals"]:
            result["warnings"].append("A long still-frame interval was detected before the intentional final freeze.")
        result["status"] = "needs_review" if result["warnings"] else "ok"
        result["available_filters"] = sorted(available)
        return result
    finally:
        try:
            metadata_path.unlink(missing_ok=True)
        except OSError:
            pass
