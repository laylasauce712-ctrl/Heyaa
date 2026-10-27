import json
import math
import os
import re
import shutil
import statistics
import struct
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

try:
    from src.heyaa.media_sources import parse_media_source_args, prepare_media_sources
except ModuleNotFoundError:
    from heyaa.media_sources import parse_media_source_args, prepare_media_sources

try:
    from src.heyaa.edl.validate import validate_edl
except ModuleNotFoundError:
    from heyaa.edl.validate import validate_edl

try:
    from src.heyaa.agents import run_agent_team, export_storage_agent
    from src.heyaa.subject_tracking import detect_person_track, subject_observation_near
except ModuleNotFoundError:
    from heyaa.agents import run_agent_team, export_storage_agent
    from heyaa.subject_tracking import detect_person_track, subject_observation_near

VIDEO = "input/test_video.mp4"
MUSIC = "input/phonk.mp3"
REFERENCE = "input/reference.mp4"
OUTDIR = "output"
WORK = "output/work"
FINAL = "output/final_phonk_20s.mp4"
VARIANT_INDEX = None
REFERENCE_CUT_TIMESTAMPS_USED = False
VARIANT_SOURCE_POWERS = {1: 1.0, 2: 1.16, 3: 0.84, 4: 1.08, 5: 0.92}
VARIANT_LABELS = {
    1: "Reference-timed / balanced source progression",
    2: "Reference-timed / early-source emphasis",
    3: "Reference-timed / late-source emphasis",
    4: "Reference-timed / gently early-weighted progression",
    5: "Reference-timed / gently late-weighted progression",
}
SKULL_ASSET = str(Path(__file__).parent / "heyaa" / "assets" / "skull_freeze.svg")

DURATION = None
FPS = None
SPEED = None
FREEZE = None
EDIT_DURATION = None
WIDTH, HEIGHT = None, None
CRF = None
PRESET = None
BEAT_SYNC = None
BEAT_FLASH = None
BASS_BOOST = None
REFERENCE_PACING = None
MIRROR_ENABLED = None
LAYOUT_MODE = "fill"
MIN_CLIPS = None
MAX_CLIPS = None
MIN_SOURCE_GAP_SECONDS = 0.05
MUSIC_LOOP = None
CODEC = None
CONFIG = None
DROP_FREEZE_DURATION = 0.25
DROP_BEAT_TIME = None
DROP_BEAT_STRENGTH = None
SUBJECT_OBSERVATIONS = []
AI_UPSCALE_ENABLED = False
AI_UPSCALE_MODEL = "realesrgan-x4plus"
AI_UPSCALE_SCALE = 2
AI_UPSCALE_BINARY = "tools/realesrgan/realesrgan-ncnn-vulkan"
AI_UPSCALE_MODEL_DIR = "tools/realesrgan/models"
AI_UPSCALER_EXECUTABLE = None
AI_UPSCALER_MODEL_DIR = None
AI_UPSCALE_MODELS = {
    "realesrgan-x4plus", "realesrgan-x4plus-anime",
    "realesrnet-x4plus", "realesr-animevideov3",
}


def reset_progress_log():
    """Start a fresh durable JSONL event trace for this render."""
    path = Path(OUTDIR) / "progress.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    except OSError as exc:
        print(f"[progress] Could not initialize {path}: {exc}", flush=True)


def progress_event(stage, status, summary, details=None, *, echo=True):
    """Persist a truthful stage/agent event and optionally stream it to the terminal."""
    event = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stage": str(stage),
        "status": str(status),
        "summary": str(summary),
        "details": details if details is not None else {},
    }
    if echo:
        print(f"[progress:{event['stage']}] {event['status']}: {event['summary']}", flush=True)
    path = Path(OUTDIR) / "progress.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        if echo:
            print(f"[progress] Could not append {path}: {exc}", flush=True)
    return event


def load_settings():
    """Load and strictly validate params.json; unsupported values fail fast."""
    global DURATION, FPS, WIDTH, HEIGHT, CRF, PRESET, SPEED, FREEZE, EDIT_DURATION
    global BEAT_SYNC, BEAT_FLASH, BASS_BOOST, REFERENCE_PACING, MIRROR_ENABLED, LAYOUT_MODE
    global MIN_CLIPS, MAX_CLIPS, MUSIC_LOOP, CODEC, CONFIG, DROP_FREEZE_DURATION, MIN_SOURCE_GAP_SECONDS
    global AI_UPSCALE_ENABLED, AI_UPSCALE_MODEL, AI_UPSCALE_SCALE
    global AI_UPSCALE_BINARY, AI_UPSCALE_MODEL_DIR
    path = "params.json"
    if not os.path.isfile(path):
        raise FileNotFoundError("params.json is required; renderer defaults are disabled.")
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    video, audio, edit = config["video_settings"], config["audio_settings"], config["edit_settings"]
    if config.get("style") != "phonk_montagem":
        raise ValueError("Only style='phonk_montagem' is implemented by this renderer.")
    resolution = str(video["resolution"]).lower().split("x")
    if len(resolution) != 2:
        raise ValueError("video_settings.resolution must be WIDTHxHEIGHT")
    WIDTH, HEIGHT = int(resolution[0]), int(resolution[1])
    if (WIDTH, HEIGHT) != (1080, 1920):
        raise ValueError("This renderer currently requires 1080x1920 output.")
    FPS = video["fps"]
    if isinstance(FPS, bool) or not isinstance(FPS, int) or not 24 <= FPS <= 60:
        raise ValueError("video_settings.fps must be an integer from 24 to 60.")
    CRF = video["crf"]
    if isinstance(CRF, bool) or not isinstance(CRF, int) or not 16 <= CRF <= 26:
        raise ValueError("video_settings.crf must be an integer from 16 to 26.")
    AI_UPSCALE_ENABLED = video.get("ai_upscale_enabled", False)
    if not isinstance(AI_UPSCALE_ENABLED, bool):
        raise ValueError("video_settings.ai_upscale_enabled must be an explicit boolean.")
    AI_UPSCALE_MODEL = video.get("ai_upscale_model", "realesrgan-x4plus")
    if AI_UPSCALE_MODEL not in AI_UPSCALE_MODELS:
        raise ValueError("video_settings.ai_upscale_model is not a supported Real-ESRGAN ncnn-vulkan model.")
    AI_UPSCALE_SCALE = video.get("ai_upscale_scale", 2)
    if isinstance(AI_UPSCALE_SCALE, bool) or not isinstance(AI_UPSCALE_SCALE, int) or AI_UPSCALE_SCALE not in (2, 3, 4):
        raise ValueError("video_settings.ai_upscale_scale must be 2, 3 or 4.")
    AI_UPSCALE_BINARY = video.get("ai_upscale_binary", "tools/realesrgan/realesrgan-ncnn-vulkan")
    if not isinstance(AI_UPSCALE_BINARY, str) or not AI_UPSCALE_BINARY.strip():
        raise ValueError("video_settings.ai_upscale_binary must be a non-empty executable name or path.")
    AI_UPSCALE_MODEL_DIR = video.get("ai_upscale_model_dir", "tools/realesrgan/models")
    if not isinstance(AI_UPSCALE_MODEL_DIR, str):
        raise ValueError("video_settings.ai_upscale_model_dir must be a path string (empty means auto-detect).")
    CODEC = str(video["codec"])
    if CODEC != "libx264":
        raise ValueError("Only video_settings.codec='libx264' is implemented.")
    PRESET = str(video["preset"])
    if PRESET not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"}:
        raise ValueError("Unsupported x264 preset.")
    duration_value = edit["duration_seconds"]
    if (isinstance(duration_value, bool) or not isinstance(duration_value, (int, float)) or
            not math.isfinite(float(duration_value))):
        raise ValueError("edit_settings.duration_seconds must be a finite number.")
    DURATION = float(duration_value)
    if not 8.0 <= DURATION <= 60.0:
        raise ValueError("edit_settings.duration_seconds must be between 8 and 60.")
    freeze_value = edit["freeze_duration"]
    if (isinstance(freeze_value, bool) or not isinstance(freeze_value, (int, float)) or
            not math.isfinite(float(freeze_value))):
        raise ValueError("edit_settings.freeze_duration must be a finite number.")
    FREEZE = float(freeze_value)
    if not 1.7 <= FREEZE <= 3.0 or FREEZE >= DURATION:
        raise ValueError("freeze_duration must be 1.7–3.0 seconds and shorter than duration.")
    drop_freeze_value = edit.get("drop_freeze_duration", 0.25)
    if (isinstance(drop_freeze_value, bool) or not isinstance(drop_freeze_value, (int, float)) or
            not math.isfinite(float(drop_freeze_value)) or not 0.1 <= float(drop_freeze_value) <= 0.6):
        raise ValueError("edit_settings.drop_freeze_duration must be between 0.1 and 0.6 seconds.")
    DROP_FREEZE_DURATION = float(drop_freeze_value)
    speed_value = edit["speed"]
    if (isinstance(speed_value, bool) or not isinstance(speed_value, (int, float)) or
            not math.isfinite(float(speed_value))):
        raise ValueError("edit_settings.speed must be a finite number.")
    SPEED = float(speed_value)
    if not 1.0 <= SPEED <= 1.35:
        raise ValueError("edit_settings.speed must be between 1.0x and 1.35x.")
    minimum_value, maximum_value = edit["min_clips"], edit["max_clips"]
    if (isinstance(minimum_value, bool) or not isinstance(minimum_value, int) or
            isinstance(maximum_value, bool) or not isinstance(maximum_value, int)):
        raise ValueError("min_clips and max_clips must be integers.")
    MIN_CLIPS, MAX_CLIPS = minimum_value, maximum_value
    if not 6 <= MIN_CLIPS <= 12 or not MIN_CLIPS <= MAX_CLIPS <= 18:
        raise ValueError("Clip bounds must satisfy 6 <= min_clips <= 12 and min_clips <= max_clips <= 18.")
    source_gap_value = edit.get("source_min_gap_seconds", 0.05)
    if (isinstance(source_gap_value, bool) or not isinstance(source_gap_value, (int, float)) or
            not math.isfinite(float(source_gap_value)) or not 0.0 <= float(source_gap_value) <= 1.0):
        raise ValueError("edit_settings.source_min_gap_seconds must be between 0 and 1 second.")
    MIN_SOURCE_GAP_SECONDS = float(source_gap_value)
    for key in ("reference_pacing", "mirror_enabled"):
        if not isinstance(edit.get(key), bool):
            raise ValueError(f"edit_settings.{key} must be an explicit boolean.")
    layout_mode = edit.get("layout_mode")
    if layout_mode is None:
        legacy_smart_crop = edit.get("smart_crop")
        layout_mode = ("fill" if legacy_smart_crop else "blur_fit") if isinstance(legacy_smart_crop, bool) else "fill"
    if layout_mode not in {"fill", "blur_fit"}:
        raise ValueError("edit_settings.layout_mode must be either 'fill' or 'blur_fit'.")
    for key in ("beat_sync", "beat_flash", "bass_boost", "music_loop"):
        if not isinstance(audio.get(key), bool):
            raise ValueError(f"audio_settings.{key} must be an explicit boolean.")
    BEAT_SYNC, BEAT_FLASH = audio["beat_sync"], audio["beat_flash"]
    BASS_BOOST, MUSIC_LOOP = audio["bass_boost"], audio["music_loop"]
    REFERENCE_PACING = edit["reference_pacing"]
    MIRROR_ENABLED = edit["mirror_enabled"]
    LAYOUT_MODE = layout_mode
    if edit.get("edl_mode") != "on":
        raise ValueError("edit_settings.edl_mode must be 'on' for the integrated EDL renderer.")
    total_frames, freeze_frames = round(DURATION * FPS), round(FREEZE * FPS)
    if freeze_frames <= 0 or freeze_frames >= total_frames:
        raise ValueError("freeze_duration must occupy at least one frame and less than the full timeline.")
    FREEZE = freeze_frames / FPS
    DURATION = total_frames / FPS
    EDIT_DURATION = (total_frames - freeze_frames) / FPS
    CONFIG = config
    print(f"[settings] {WIDTH}x{HEIGHT}@{FPS} | {DURATION:.3f}s | speed={SPEED:.2f}x | final_freeze={FREEZE:.3f}s (minimum 1.7s) | drop_freeze={DROP_FREEZE_DURATION:.3f}s | mirror={MIRROR_ENABLED} | layout_mode={LAYOUT_MODE} | ai_upscale={AI_UPSCALE_ENABLED} ({AI_UPSCALE_MODEL} x{AI_UPSCALE_SCALE}) | music_loop={MUSIC_LOOP} | source_min_gap={MIN_SOURCE_GAP_SECONDS:.3f}s | EDL=on")
    return config


def resolve_ai_upscaler():
    """Resolve the optional external Real-ESRGAN ncnn-vulkan executable and model directory."""
    global AI_UPSCALER_EXECUTABLE, AI_UPSCALER_MODEL_DIR
    if not AI_UPSCALE_ENABLED:
        AI_UPSCALER_EXECUTABLE = None
        AI_UPSCALER_MODEL_DIR = None
        return None
    configured = AI_UPSCALE_BINARY.strip()
    resolved = shutil.which(configured)
    candidate = Path(configured).expanduser()
    if resolved is None and candidate.is_file():
        resolved = str(candidate.resolve())
    if resolved is None:
        raise FileNotFoundError(
            "AI upscaling is enabled, but Real-ESRGAN was not found. Run "
            "bash scripts/install_realesrgan_linux.sh or set video_settings.ai_upscale_binary "
            "to the installed executable. No silent Lanczos fallback is used when AI upscaling is required."
        )
    executable = Path(resolved).resolve()
    model_dir_value = AI_UPSCALE_MODEL_DIR.strip()
    if model_dir_value:
        model_dir = Path(model_dir_value).expanduser()
        if not model_dir.is_absolute():
            model_dir = Path.cwd() / model_dir
        if not model_dir.is_dir():
            raise FileNotFoundError(f"Real-ESRGAN model directory does not exist: {model_dir}")
    else:
        candidates = [executable.parent / "models", Path.cwd() / "models"]
        model_dir = next((item.resolve() for item in candidates if item.is_dir()), None)
        if model_dir is None:
            raise FileNotFoundError(
                "AI upscaling is enabled but the Real-ESRGAN models folder was not found. "
                "Set video_settings.ai_upscale_model_dir to the folder containing the model files."
            )
    model_file_stem = (
        f"{AI_UPSCALE_MODEL}-x{AI_UPSCALE_SCALE}"
        if AI_UPSCALE_MODEL == "realesr-animevideov3"
        else AI_UPSCALE_MODEL
    )
    missing_model_files = [
        str(model_dir / f"{model_file_stem}{suffix}")
        for suffix in (".param", ".bin")
        if not (model_dir / f"{model_file_stem}{suffix}").is_file()
    ]
    if missing_model_files:
        raise FileNotFoundError(
            "Real-ESRGAN model files are missing: " + ", ".join(missing_model_files)
            + ". Re-run bash scripts/install_realesrgan_linux.sh or correct ai_upscale_model_dir."
        )
    AI_UPSCALER_EXECUTABLE = str(executable)
    AI_UPSCALER_MODEL_DIR = str(model_dir.resolve())
    print(f"[upscale] Real-ESRGAN ready: {AI_UPSCALER_EXECUTABLE}; models={AI_UPSCALER_MODEL_DIR}; model={AI_UPSCALE_MODEL}; scale={AI_UPSCALE_SCALE}x")
    return AI_UPSCALER_EXECUTABLE


def build_ai_upscale_command(executable, input_dir, output_dir, model, scale, model_dir):
    """Build a Real-ESRGAN directory-to-directory image batch command."""
    return [
        str(executable), "-i", str(input_dir), "-o", str(output_dir),
        "-n", str(model), "-s", str(scale), "-m", str(model_dir), "-f", "png",
    ]


def prepare_ai_upscaled_frames(clip_index, source_start_seconds, source_duration_seconds, source_frame_count):
    """Extract one clip to lossless frames, restore detail with Real-ESRGAN, then return its frame sequence."""
    if not AI_UPSCALE_ENABLED or not AI_UPSCALER_EXECUTABLE or not AI_UPSCALER_MODEL_DIR:
        raise RuntimeError("AI-upscaled frame preparation was requested without a resolved Real-ESRGAN executable.")
    root = Path(WORK) / f"ai_upscale_clip_{clip_index:02d}"
    if root.exists():
        shutil.rmtree(root)
    input_dir = root / "input"
    output_dir = root / "upscaled"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    input_pattern = input_dir / "frame_%08d.png"
    output_pattern = output_dir / "frame_%08d.png"

    extract = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{source_start_seconds:.6f}",
        "-t", f"{source_duration_seconds + 1.0 / FPS:.6f}",
        "-i", VIDEO, "-vf", f"fps={FPS}", "-frames:v", str(source_frame_count),
        "-start_number", "1", str(input_pattern),
    ]
    result = subprocess.run(extract, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Could not extract frames for AI upscaling: {result.stderr[-2000:]}")
    expected_names = [f"frame_{frame:08d}.png" for frame in range(1, source_frame_count + 1)]
    missing_input = [name for name in expected_names if not (input_dir / name).is_file()]
    if missing_input:
        raise RuntimeError(
            f"AI upscale extraction produced {source_frame_count - len(missing_input)}/{source_frame_count} frames; "
            f"first missing: {missing_input[0]}"
        )

    upscale = build_ai_upscale_command(
        AI_UPSCALER_EXECUTABLE, input_dir, output_dir,
        AI_UPSCALE_MODEL, AI_UPSCALE_SCALE, AI_UPSCALER_MODEL_DIR,
    )
    result = subprocess.run(upscale, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Real-ESRGAN failed for clip {clip_index}: {result.stderr[-2000:]}")
    missing_output = [
        name for name in expected_names
        if not (output_dir / name).is_file() or (output_dir / name).stat().st_size <= 0
    ]
    if missing_output:
        raise RuntimeError(
            f"Real-ESRGAN returned only {source_frame_count - len(missing_output)}/{source_frame_count} usable frames; "
            f"first missing: {missing_output[0]}"
        )
    print(
        f"  [upscale] AI-restored {source_frame_count} source frames with "
        f"{AI_UPSCALE_MODEL} at {AI_UPSCALE_SCALE}x; detail is model-generated, not verified source truth."
    )
    return output_pattern, root


def run(cmd, capture=False, binary=False):
    return subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else None,
        text=not binary,
    )


def probe(path):
    result = run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", path
    ], capture=True)
    return json.loads(result.stdout)


def duration_of(path):
    return float(probe(path)["format"]["duration"])


def detect_scenes(path, duration, scan_duration=None):
    """Use FFmpeg scene-change scores as an inexpensive cut detector."""
    print(f"[analyze] Scene changes: {Path(path).name}")
    cmd = ["ffmpeg", "-hide_banner"]
    if scan_duration is not None:
        cmd += ["-t", f"{max(0.1, float(scan_duration)):.3f}"]
    cmd += ["-i", path,
        "-vf", "select='gt(scene,0.22)',showinfo",
        "-an", "-f", "null", "-"
    ]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=False
    )
    times = []
    for line in result.stderr.splitlines():
        match = re.search(r"pts_time:([0-9.]+)", line)
        if match:
            value = float(match.group(1))
            if 0.15 < value < duration - 0.15:
                times.append(value)
    return sorted(set(times))


def _estimate_period_frames(envelope, min_lag=15, max_lag=60):
    """Estimate a plausible beat period from onset-envelope autocorrelation."""
    if len(envelope) < min_lag * 3:
        return None
    mean = sum(envelope) / len(envelope)
    centered = [value - mean for value in envelope]
    best_lag, best_score = None, 0.0
    upper = min(max_lag, len(centered) // 3)
    for lag in range(min_lag, upper + 1):
        left = centered[lag:]
        right = centered[:-lag]
        numerator = sum(x * y for x, y in zip(left, right))
        left_energy = sum(x * x for x in left)
        right_energy = sum(y * y for y in right)
        denominator = math.sqrt(left_energy * right_energy)
        score = numerator / denominator if denominator > 1e-12 else 0.0
        if score > best_score:
            best_lag, best_score = lag, score
    return best_lag if best_score >= 0.12 else None


def extend_looped_beats(beats, music_duration, limit, loop_enabled):
    """Map measured beat candidates into repeated music cycles when the soundtrack loops."""
    if not beats:
        return []
    try:
        duration = float(music_duration)
        end = float(limit)
    except (TypeError, ValueError):
        return sorted(set(float(beat) for beat in beats))
    if not math.isfinite(duration) or not math.isfinite(end) or duration <= 0 or end <= 0:
        return sorted(set(float(beat) for beat in beats))
    original = [float(beat) for beat in beats if 0.0 <= float(beat) < end]
    if not loop_enabled or duration >= end:
        return sorted(set(original))
    # A source-file analysis only represents one music cycle. Ignore any
    # out-of-cycle timestamps before generating the repeated loop candidates.
    original = [beat for beat in original if beat < duration]
    expanded = []
    for cycle in range(math.ceil(end / duration)):
        offset = cycle * duration
        for beat in original:
            timestamp = beat + offset
            if timestamp < end:
                expanded.append(round(timestamp, 6))
    return sorted(set(expanded))


def detect_music_beats(path, limit):
    """Estimate beat candidates and retain the strongest onset as a drop proxy.

    This remains a lightweight heuristic, not a semantic drop/downbeat detector.
    """
    global DROP_BEAT_TIME, DROP_BEAT_STRENGTH
    DROP_BEAT_TIME, DROP_BEAT_STRENGTH = None, None
    print("[analyze] Phonk beat/bass transients and tempo periodicity...")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
        "-vn", "-ac", "1", "-ar", "8000", "-af", "lowpass=f=160",
        "-f", "f32le", "pipe:1"
    ]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    raw = result.stdout
    if result.returncode != 0 or len(raw) < 8000:
        print("[warn] Beat analysis unavailable; using an even edit rhythm.")
        return []

    samples_per_window = 160  # 20 ms at 8 kHz
    energies = []
    bucket = []
    for (sample,) in struct.iter_unpack("<f", raw[:len(raw) // 4 * 4]):
        bucket.append(sample * sample)
        if len(bucket) == samples_per_window:
            energies.append(math.sqrt(sum(bucket) / len(bucket)))
            bucket = []
    if bucket:
        energies.append(math.sqrt(sum(bucket) / len(bucket)))
    if len(energies) < 8:
        return []

    # Positive local energy changes approximate onset strength without NumPy.
    novelty = [0.0] * len(energies)
    for i in range(2, len(energies)):
        local_floor = sorted(energies[max(0, i - 5):i])[len(energies[max(0, i - 5):i]) // 2]
        novelty[i] = max(0.0, energies[i] - local_floor)

    period_frames = _estimate_period_frames(novelty)
    if period_frames:
        bpm = 60.0 / (period_frames * 0.02)
        min_spacing = max(0.24, period_frames * 0.02 * 0.52)
        print(f"[analyze] Bass-onset periodicity suggests about {bpm:.0f} BPM (heuristic).")
    else:
        min_spacing = 0.24
        print("[warn] No stable tempo periodicity; using onset-only candidates.")

    ordered = sorted(novelty)
    median_novelty = ordered[len(ordered) // 2]
    peak_novelty = max(novelty)
    threshold = median_novelty + (peak_novelty - median_novelty) * 0.24
    candidates = []
    for i in range(2, len(novelty) - 2):
        value = novelty[i]
        if value <= 0 or value < threshold:
            continue
        if value >= max(novelty[i - 2:i]) and value >= max(novelty[i + 1:i + 3]):
            timestamp = i * 0.02
            if 0.08 <= timestamp < min(limit, len(energies) * 0.02):
                candidates.append((value, timestamp))

    # Keep the strongest onset per tempo-aware interval; reject near-duplicate peaks.
    chosen = []
    for value, timestamp in sorted(candidates, reverse=True):
        if all(abs(timestamp - existing) >= min_spacing for existing in chosen):
            chosen.append(timestamp)
    beats = sorted(t for t in chosen if t < limit)
    if len(beats) < 3:
        print("[warn] Few clear bass onsets found; edit timing will use fallback beats.")
        return []
    if candidates:
        strongest_value, strongest_time = max(candidates, key=lambda pair: pair[0])
        DROP_BEAT_TIME = float(strongest_time)
        spread = max(1e-12, peak_novelty - median_novelty)
        DROP_BEAT_STRENGTH = max(0.0, min(1.0, (strongest_value - median_novelty) / spread))
        print(
            f"[analyze] Strongest bass-onset proxy at {DROP_BEAT_TIME:.2f}s "
            f"(relative onset strength={DROP_BEAT_STRENGTH:.2f}; not a semantic drop detector)."
        )
    print(f"[analyze] Detected {len(beats)} likely beat/onset candidates in the edit window.")
    return beats

def reference_pacing_profile(reference_path):
    """Measure reference shot durations so planning can reuse its pacing pattern."""
    if not os.path.isfile(reference_path):
        print("[warn] reference.mp4 missing; using the default Phonk pacing.")
        return None
    try:
        ref_duration = duration_of(reference_path)
        cuts = detect_scenes(reference_path, ref_duration)
        boundaries = [0.0] + [cut for cut in cuts if 0.0 < cut < ref_duration] + [ref_duration]
        boundaries = sorted(set(boundaries))
        gaps = [
            round(b - a, 4) for a, b in zip(boundaries, boundaries[1:])
            if 0.25 <= b - a <= 4.0
        ]
        if len(gaps) < 2:
            print("[warn] Reference has too few usable shot intervals; using default pacing.")
            return None
        interval = float(statistics.median(gaps))
        profile = {
            "duration_seconds": round(ref_duration, 4),
            "scene_cut_count": len(cuts),
            "median_cut_interval_seconds": round(interval, 4),
            "shot_intervals_seconds": gaps,
            "cut_timestamps_seconds": [round(cut, 4) for cut in cuts],
            "method": "ffmpeg-scene-cut-timestamps",
            "semantic_reference_understanding": False,
        }
        print(
            f"[analyze] Reference pacing profile: {len(gaps)} usable shot intervals; "
            f"median {interval:.2f}s. The measured rhythm will guide individual cut lengths."
        )
        return profile
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"[warn] Could not analyze reference.mp4: {exc}")
        return None


def reference_cut_interval(reference_path):
    """Compatibility helper returning only the measured median reference interval."""
    profile = reference_pacing_profile(reference_path)
    return profile.get("median_cut_interval_seconds") if profile else None


def choose_clip_count(reference_interval, requested_count=None):
    """Choose the measured-reference count unless the user requests an allowed exact count."""
    if requested_count is not None:
        if isinstance(requested_count, bool) or not isinstance(requested_count, int):
            raise ValueError("clip_count must be an integer.")
        if not MIN_CLIPS <= requested_count <= MAX_CLIPS:
            raise ValueError(
                f"Requested clip_count={requested_count} is outside params.json bounds "
                f"{MIN_CLIPS}–{MAX_CLIPS}."
            )
        return requested_count
    # Bound the workload for mobile rendering while letting the reference affect pacing.
    if reference_interval is None:
        return MIN_CLIPS
    return max(MIN_CLIPS, min(MAX_CLIPS, round(EDIT_DURATION / max(0.75, min(2.4, reference_interval)))))


def choose_drop_beat(music_duration, available_edit_duration, loop_enabled):
    """Choose a repeated strongest bass-onset proxy near the first major edit section."""
    if not BEAT_SYNC or DROP_BEAT_TIME is None:
        return None
    try:
        duration = float(music_duration)
        limit = float(available_edit_duration)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(limit) or limit <= 0:
        return None
    candidates = []
    if loop_enabled and duration < limit:
        for cycle in range(math.ceil(limit / duration)):
            value = DROP_BEAT_TIME + cycle * duration
            if 0.7 <= value <= limit - DROP_FREEZE_DURATION - 0.75:
                candidates.append(value)
    elif 0.7 <= DROP_BEAT_TIME <= limit - DROP_FREEZE_DURATION - 0.75:
        candidates.append(DROP_BEAT_TIME)
    if not candidates:
        return None
    target = limit * 0.38
    return min(candidates, key=lambda value: abs(value - target))


def insert_drop_boundary(boundaries, desired_time, min_gap=0.75):
    """Use the drop time as a cut boundary while preserving the planned clip count."""
    if desired_time is None or len(boundaries) < 3:
        return boundaries, None
    limit = boundaries[-1]
    if not 0.7 <= desired_time <= limit - 0.7:
        return boundaries, None
    original_count = len(boundaries)
    candidates = sorted(range(1, len(boundaries) - 1),
                        key=lambda index: abs(boundaries[index] - desired_time))
    for index in candidates:
        if (desired_time - boundaries[index - 1] >= min_gap and
                boundaries[index + 1] - desired_time >= min_gap):
            updated = list(boundaries)
            updated[index] = desired_time
            updated.sort()
            return updated, desired_time
    # If the strongest onset would create a very short adjacent shot, keep pacing
    # stable and freeze at the nearest already-validated cut instead.
    nearest = min(boundaries[1:-1], key=lambda value: abs(value - desired_time))
    return list(boundaries), nearest


def choose_context_window(source_duration, scene_cuts, target_duration):
    """Prefer a coherent temporal window over sampling across an entire long recording.

    This is a scene-cut-density proxy only; it does not identify a person or
    understand the semantics of a 20-minute scene.
    """
    if not math.isfinite(float(source_duration)) or source_duration <= 0:
        return {"start_seconds": 0.0, "end_seconds": 0.0, "scene_cuts": 0, "method": "unavailable"}
    window = min(float(source_duration), max(8.0, float(target_duration) * 2.0))
    max_start = max(0.0, float(source_duration) - window)
    candidates = {0.0, max_start}
    for cut in scene_cuts:
        candidates.add(max(0.0, min(max_start, float(cut) - window / 2.0)))
    target_cut_count = max(2, round(window / 2.5))
    best_start = 0.0
    best_key = None
    best_count = 0
    for start in sorted(candidates):
        end = start + window
        count = sum(1 for cut in scene_cuts if start <= cut < end)
        # Prefer a moderately active sequence; penalize both empty windows and
        # unusually frantic cut density instead of blindly maximizing cut count.
        score = -abs(count - target_cut_count) - max(0, count - target_cut_count * 1.8) * 0.5
        key = (score, count, -start)
        if best_key is None or key > best_key:
            best_key, best_start, best_count = key, start, count
    end = min(float(source_duration), best_start + window)
    print(
        f"[context] Selected source window {best_start:.2f}s–{end:.2f}s "
        f"({best_count} scene cuts; temporal continuity proxy only)."
    )
    print("[context] Same-person tracking/semantic action understanding is not available in this build.")
    return {"start_seconds": round(best_start, 3), "end_seconds": round(end, 3),
            "scene_cuts": best_count, "window_seconds": round(end - best_start, 3),
            "target_cut_count": target_cut_count, "method": "moderate-scene-cut-density-window",
            "same_person_tracking": False}


def _reference_boundaries(clip_count, total_duration, profile):
    """Prefer measured reference cut timestamps, with a bounded interval-resampling fallback."""
    global REFERENCE_CUT_TIMESTAMPS_USED
    REFERENCE_CUT_TIMESTAMPS_USED = False
    intervals = profile.get("shot_intervals_seconds") if isinstance(profile, dict) else None
    if not isinstance(intervals, list) or len(intervals) < 2 or clip_count < 1:
        return [total_duration * index / clip_count for index in range(clip_count + 1)]

    # When there are enough measured cuts, preserve their timestamp pattern after
    # scaling the reference's active timeline to the requested edit duration.
    # The candidate is accepted only if every resulting shot remains render-safe.
    cuts = profile.get("cut_timestamps_seconds") if isinstance(profile, dict) else None
    reference_duration = profile.get("duration_seconds") if isinstance(profile, dict) else None
    if (isinstance(cuts, list) and isinstance(reference_duration, (int, float))
            and not isinstance(reference_duration, bool) and math.isfinite(float(reference_duration))
            and float(reference_duration) > 0):
        valid_cuts = sorted({
            float(value) for value in cuts
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and 0.25 < float(value) < float(reference_duration) - 0.25
        })
        required = clip_count - 1
        if required > 0 and len(valid_cuts) >= required:
            selected_indices = [
                round(index * (len(valid_cuts) - 1) / max(1, required - 1))
                for index in range(required)
            ]
            selected_cuts = [valid_cuts[index] * total_duration / float(reference_duration)
                             for index in selected_indices]
            exactish = [0.0] + selected_cuts + [total_duration]
            shot_lengths = [b - a for a, b in zip(exactish, exactish[1:])]
            if (len(exactish) == clip_count + 1 and
                    all(0.75 <= length <= 3.3 for length in shot_lengths) and
                    all(b > a for a, b in zip(exactish, exactish[1:]))):
                REFERENCE_CUT_TIMESTAMPS_USED = True
                print("[edit] Using the reference's measured cut timestamps, scaled to the requested edit duration.")
                return exactish
    valid = [float(value) for value in intervals
             if isinstance(value, (int, float)) and not isinstance(value, bool)
             and math.isfinite(float(value)) and float(value) > 0]
    if len(valid) < 2:
        return [total_duration * index / clip_count for index in range(clip_count + 1)]
    minimum, maximum = 0.75, 3.3
    if (clip_count * minimum > total_duration + 1e-8 or
            clip_count * maximum < total_duration - 1e-8):
        print("[warn] Reference pacing cannot fit the requested duration inside the supported shot-length range; using even pacing.")
        return [total_duration * index / clip_count for index in range(clip_count + 1)]

    # Resample the reference rhythm, then solve for one scale factor whose
    # clamped interval lengths add up exactly to the requested duration.
    # Bisection avoids the old simultaneous clamp/rebalance edge case, which
    # could lose the reference pattern and force all shots to an even duration.
    weights = [
        max(1e-6, valid[round(index * (len(valid) - 1) / max(1, clip_count - 1))])
        for index in range(clip_count)
    ]
    low, high = 0.0, maximum / min(weights)
    for _ in range(80):
        scale = (low + high) / 2.0
        trial = [min(maximum, max(minimum, scale * weight)) for weight in weights]
        if sum(trial) < total_duration:
            low = scale
        else:
            high = scale
    scale = (low + high) / 2.0
    lengths = [min(maximum, max(minimum, scale * weight)) for weight in weights]

    # Remove the tiny floating-point remainder without crossing shot bounds.
    remainder = total_duration - sum(lengths)
    for index in sorted(
        range(clip_count),
        key=lambda i: (maximum - lengths[i]) if remainder > 0 else (lengths[i] - minimum),
        reverse=True,
    ):
        if abs(remainder) <= 1e-8:
            break
        capacity = (maximum - lengths[index]) if remainder > 0 else (lengths[index] - minimum)
        change = math.copysign(min(abs(remainder), max(0.0, capacity)), remainder)
        lengths[index] += change
        remainder -= change
    if abs(total_duration - sum(lengths)) > 1e-5:
        print("[warn] Could not satisfy the reference pacing constraints; using even pacing.")
        return [total_duration * index / clip_count for index in range(clip_count + 1)]
    boundaries = [0.0]
    for value in lengths:
        boundaries.append(boundaries[-1] + value)
    boundaries[-1] = total_duration
    return boundaries


def make_boundaries(clip_count, beats, reference_profile=None):
    """Keep reference-derived shot lengths and accept only beat snaps that stay render-safe."""
    reference_boundaries = _reference_boundaries(clip_count, EDIT_DURATION, reference_profile)
    boundaries = list(reference_boundaries)
    if beats:
        for index in range(1, clip_count):
            target = boundaries[index]
            snap_window = 0.16 if reference_profile and reference_profile.get("cut_timestamps_seconds") else 0.42
            nearby = [beat for beat in beats if abs(beat - target) <= snap_window]
            if not nearby:
                continue
            candidate = min(nearby, key=lambda beat: abs(beat - target))
            previous, following = boundaries[index - 1], boundaries[index + 1]
            previous_gap, next_gap = candidate - previous, following - candidate
            if 0.75 <= previous_gap <= 3.3 and 0.75 <= next_gap <= 3.3:
                boundaries[index] = candidate
    lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
    if min(lengths) < 0.75 - 1e-8 or max(lengths) > 3.3 + 1e-8:
        print("[warn] Beat snapping would break safe shot lengths; reverting to reference-derived boundaries.")
        boundaries = list(reference_boundaries)
        lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
    if min(lengths) < 0.75 - 1e-8 or max(lengths) > 3.3 + 1e-8:
        print("[warn] Reference-derived boundaries are outside the safe range; using even pacing.")
        boundaries = [EDIT_DURATION * index / clip_count for index in range(clip_count + 1)]
        lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
    if reference_profile:
        variation = max(lengths) - min(lengths)
        print("[edit] Reference-derived shot lengths: " + ", ".join(f"{x:.2f}" for x in lengths) + " seconds")
        print(f"[edit] Reference pacing retained: range={min(lengths):.2f}–{max(lengths):.2f}s; variation={variation:.2f}s.")
    else:
        print("[edit] Segment lengths: " + ", ".join(f"{x:.2f}" for x in lengths) + " seconds")
    return boundaries


def choose_source_center(target, scenes, source_duration):
    if source_duration <= 0.1:
        return 0.0
    target = max(0.0, min(target, source_duration))
    window = max(0.6, source_duration / 14.0)
    nearby = [time for time in scenes if abs(time - target) <= window]
    center = min(nearby, key=lambda time: abs(time - target)) if nearby else target
    return max(0.0, min(center, max(0.0, source_duration - 0.2)))


def enforce_source_progression(candidate_start_f, source_dur_f, previous_source_end_f,
                               minimum_gap_f, maximum_source_start_f):
    """Move a candidate forward when needed so source footage is never reused."""
    for name, value, minimum in (
        ("candidate_start_f", candidate_start_f, 0),
        ("source_dur_f", source_dur_f, 1),
        ("minimum_gap_f", minimum_gap_f, 0),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}.")
    if isinstance(maximum_source_start_f, bool) or not isinstance(maximum_source_start_f, int):
        raise ValueError("maximum_source_start_f must be an integer.")
    if previous_source_end_f is not None and (
        isinstance(previous_source_end_f, bool) or not isinstance(previous_source_end_f, int) or previous_source_end_f < 0
    ):
        raise ValueError("previous_source_end_f must be None or a non-negative integer.")
    if maximum_source_start_f < 0:
        raise RuntimeError("A planned clip is longer than the available source video.")
    earliest_allowed = 0 if previous_source_end_f is None else previous_source_end_f + minimum_gap_f
    selected = max(candidate_start_f, earliest_allowed)
    if selected > maximum_source_start_f:
        raise RuntimeError(
            "Not enough unused source footage remains to keep clips non-overlapping; "
            "reduce clip count/duration or use a longer source video."
        )
    return selected


def make_clip(index, item, source_duration):
    """Render exactly the source range and output frame count declared by one EDL clip."""
    start = item["source_start_f"] / FPS
    input_duration = item["source_dur_f"] / FPS
    output_frames = item["dur_f"]
    if input_duration <= 0 or output_frames <= 0:
        raise ValueError("EDL clip source/output duration must be positive.")
    start = max(0.0, min(start, max(0.0, source_duration - input_duration)))
    path = f"{WORK}/clip_{index:02d}.mp4"
    mirror = ",hflip" if MIRROR_ENABLED else ""
    clip_center_seconds = start + input_duration / 2.0
    subject_observation = subject_observation_near(
        SUBJECT_OBSERVATIONS, clip_center_seconds,
        max_distance_seconds=max(1.0, input_duration / 2.0)
    )
    crop_filter = "crop=1080:1920,"
    if subject_observation is not None and LAYOUT_MODE == "fill":
        subject_x = float(subject_observation["center_x"])
        subject_y = float(subject_observation["center_y"])
        crop_filter = (
            "crop=1080:1920:"
            f"x='max(0,min(iw-ow,{subject_x:.5f}*iw-ow/2))':"
            f"y='max(0,min(ih-oh,{subject_y:.5f}*ih-oh/2))',"
        )
        print(
            f"  [framing] Subject-track crop applied near source {clip_center_seconds:.2f}s "
            f"(center={subject_x:.2f},{subject_y:.2f}; appearance proxy, not identity recognition)."
        )

    # If optional OpenCV tracking found no stable person-shaped track, this remains
    # the deterministic centered 9:16 crop fallback.
    if LAYOUT_MODE == "fill":
        vf = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
            f"{crop_filter}"
            f"{'hflip,' if MIRROR_ENABLED else ''}"
            "eq=contrast=1.16:saturation=1.30:gamma=1.02,"
            "unsharp=5:5:0.72:3:3:0.0,setsar=1,"
            f"fps={FPS},setpts=PTS/{SPEED},fps={FPS},trim=end_frame={output_frames},setpts=PTS-STARTPTS[v]"
        )
    else:
        vf = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
            "crop=1080:1920,boxblur=20:2,eq=brightness=-0.08:saturation=0.78[back];"
            "[fg]scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos"
            f"{mirror},"
            "eq=contrast=1.16:saturation=1.30:gamma=1.02,"
            "unsharp=5:5:0.72:3:3:0.0[front];"
            "[back][front]overlay=(W-w)/2:(H-h)/2,setsar=1,"
            f"fps={FPS},setpts=PTS/{SPEED},fps={FPS},trim=end_frame={output_frames},setpts=PTS-STARTPTS[v]"
        )

    # AI mode upscales the selected source frames losslessly before the normal
    # composition crop. Standard mode keeps the existing direct FFmpeg path.
    ai_root = None
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if AI_UPSCALE_ENABLED:
        pattern, ai_root = prepare_ai_upscaled_frames(
            index, start, input_duration, item["source_dur_f"]
        )
        cmd += [
            "-framerate", str(FPS), "-start_number", "1",
            "-i", str(pattern),
        ]
    else:
        if source_duration < input_duration + start:
            cmd += ["-stream_loop", "-1"]
        cmd += [
            "-ss", f"{start:.6f}", "-t", f"{input_duration:.6f}", "-i", VIDEO,
        ]
    cmd += [
        "-filter_complex", vf, "-map", "[v]", "-an",
        "-c:v", CODEC, "-preset", PRESET, "-crf", str(CRF),
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-frames:v", str(output_frames),
        "-threads", "2", path
    ]
    run(cmd)
    if ai_root is not None:
        shutil.rmtree(ai_root)
    return path

def make_freeze_clip(index, item, previous_clip):
    """Hold the actual last decoded frame of the preceding shot for a drop impact."""
    if not previous_clip or not os.path.isfile(previous_clip):
        raise RuntimeError("A drop-impact freeze needs a preceding rendered shot.")
    previous_info = probe(previous_clip)
    previous_video = next((stream for stream in previous_info.get("streams", [])
                           if stream.get("codec_type") == "video"), {})
    frame_count = int(previous_video.get("nb_frames") or 0)
    if frame_count <= 0:
        try:
            frame_count = int(round(float(previous_info["format"]["duration"]) * FPS))
        except (KeyError, TypeError, ValueError):
            frame_count = 0
    if frame_count <= 0:
        raise RuntimeError("Could not determine the preceding shot's frame count for drop freeze.")
    still_path = f"{WORK}/drop_freeze_{index:02d}.png"
    output_path = f"{WORK}/drop_freeze_{index:02d}.mp4"
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", previous_clip,
        "-vf", f"select='eq(n,{frame_count - 1})'", "-vsync", "0", "-frames:v", "1", still_path
    ])
    duration_frames = int(item["dur_f"])
    freeze_filter = (
        "scale=1188:2112:flags=lanczos,"
        "crop=1080:1920:x='(iw-ow)/2+5*sin(t*90)':y='(ih-oh)/2+5*cos(t*73)',"
        "eq=contrast=1.38:saturation=0,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=white@0.55:t=fill:enable='lt(t,0.05)',"
        f"fps={FPS},trim=end_frame={duration_frames},setpts=PTS-STARTPTS"
    )
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", str(FPS), "-i", still_path,
        "-vf", freeze_filter, "-an", "-frames:v", str(duration_frames),
        "-c:v", CODEC, "-preset", PRESET, "-crf", str(CRF),
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-threads", "2", output_path
    ])
    return output_path


def build_pre_render_review(edl, beat_count, drop_beat_time, drop_freeze_duration,
                              reference_profile, context, subject_analysis):
    """Build an evidence-linked pre-render planning review, not an LLM conversation."""
    clips = [item for item in edl.get("video", []) if item.get("type") == "clip"]
    drop_freezes = [item for item in edl.get("video", [])
                    if item.get("type") == "freeze" and item.get("effect") == "drop-impact-freeze"]
    final_freezes = [item for item in edl.get("video", [])
                     if item.get("type") == "freeze" and item.get("effect") == "phonk-freeze"]
    internal_freeze_seconds = sum(item["dur_f"] for item in drop_freezes) / FPS
    final_freeze_seconds = final_freezes[-1]["dur_f"] / FPS if final_freezes else 0.0
    tracking_detected = isinstance(subject_analysis, dict) and subject_analysis.get("detected") is True
    intervals = reference_profile.get("shot_intervals_seconds", []) if isinstance(reference_profile, dict) else []
    median_interval = reference_profile.get("median_cut_interval_seconds") if isinstance(reference_profile, dict) else None
    return [
        {
            "turn": 1, "speaker": "Beat Sync Agent", "to": "Planner",
            "message": (
                f"Found {beat_count} bass/onset candidates. "
                + (f"The strongest-onset proxy is {drop_beat_time:.2f}s and a {internal_freeze_seconds:.3f}s internal hold is planned."
                   if drop_freezes else "No internal drop hold was planned because no eligible drop proxy/boundary was available.")
                + " The strongest onset is a proxy, not a verified musical drop."
            ),
            "evidence": {"candidate_count": beat_count, "drop_beat_time_seconds": drop_beat_time,
                        "drop_freeze_duration_seconds": internal_freeze_seconds}
        },
        {
            "turn": 2, "speaker": "Reference Analyst", "to": "Planner",
            "message": (
                f"Measured reference median={median_interval}s and shot intervals={intervals[:8]}. "
                + ("The Planner is resampling this measured interval pattern into the new timeline."
                   if intervals else "No usable reference profile was measured; use default/bass-aware pacing.")
                + " This is timing analysis only, not semantic reference understanding."
            ),
            "evidence": {"median_cut_interval_seconds": median_interval,
                        "shot_intervals_seconds": intervals, "used_for_planning": bool(intervals)}
        },
        {
            "turn": 3, "speaker": "Framing Agent", "to": "Planner",
            "message": (
                f"Selected source context {context.get('start_seconds')}–{context.get('end_seconds')}s. "
                + (f"OpenCV found a recurring appearance track across {subject_analysis.get('track_span_seconds')}s; "
                   + ("nearby detections will guide source timing and fill-layout crop centers."
                      if LAYOUT_MODE == "fill" else
                      "nearby detections guide source timing only; blur-fit framing preserves the full source frame.")
                   if tracking_detected else
                   "No stable person track was available; source selection uses cut-density context and centered crop.")
                + " This does not verify identity or story role."
            ),
            "evidence": {"context_window": context, "subject_tracking": subject_analysis}
        },
        {
            "turn": 4, "speaker": "Planner", "to": "Director",
            "message": (
                f"Validated EDL: {len(clips)} motion clips, {len(drop_freezes)} internal drop holds, "
                f"final freeze={final_freeze_seconds:.3f}s, total frames={edl.get('total_frames')}. "
                "Frame continuity and settings are checked. Final export authorization remains pending render QA."
            ),
            "evidence": {"motion_clip_count": len(clips), "drop_freeze_count": len(drop_freezes),
                        "drop_freeze_duration_seconds": internal_freeze_seconds,
                        "final_freeze_duration_seconds": final_freeze_seconds,
                        "total_frames": edl.get("total_frames"), "decision": "pending_render_qa"}
        },
    ]


def print_pre_render_review(review):
    print("[agent conference: pre-render] Evidence-linked planning review (rule-based, not independent LLM chat):", flush=True)
    for turn in review:
        print(f"[preflight {turn['turn']}] {turn['speaker']} -> {turn['to']}: {turn['message']}", flush=True)
        progress_event(
            "pre_render_agent_review", "completed", turn["message"],
            {"turn": turn["turn"], "speaker": turn["speaker"], "to": turn["to"],
             "evidence": turn.get("evidence", {})},
            echo=False,
        )


def make_flash_filter(beats):
    # Brief white impacts on selected bass hits; keep the filter graph bounded.
    if not BEAT_FLASH:
        return ""
    filters = []
    for beat in beats[:32]:
        if 0.05 < beat < EDIT_DURATION - 0.05:
            start = max(0.0, beat)
            end = start + 0.035
            filters.append(
                "drawbox=x=0:y=0:w=iw:h=ih:color=white@0.30:t=fill:"
                f"enable='between(t,{start:.3f},{end:.3f})'"
            )
    return ",".join(filters)


def verify_output(path):
    """Verify the encoded file, exact decoded frame count, frame rate, audio and full-file decodability."""
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise RuntimeError("Rendered output file is missing or empty.")
    result = run([
        "ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format",
        "-of", "json", path
    ], capture=True)
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise RuntimeError("Final file has no video stream.")
    if audio is None:
        raise RuntimeError("Final file has no audio stream.")
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    if (width, height) != (WIDTH, HEIGHT):
        raise RuntimeError(f"Wrong output resolution: {width}x{height}")
    try:
        rate = Fraction(video.get("avg_frame_rate", "0/1"))
    except (ValueError, ZeroDivisionError):
        rate = Fraction(0, 1)
    if abs(float(rate) - FPS) > 0.01:
        raise RuntimeError(f"Wrong output FPS: {rate}, expected {FPS}.")
    frame_count = int(video.get("nb_read_frames") or video.get("nb_frames") or 0)
    expected_frames = round(DURATION * FPS)
    if frame_count != expected_frames:
        raise RuntimeError(f"Output has {frame_count} decoded frames, expected exactly {expected_frames}.")
    actual_duration = float(info["format"]["duration"])
    if abs(actual_duration - DURATION) > (1.0 / FPS + 0.005):
        raise RuntimeError(f"Output duration is {actual_duration:.3f}s, expected {DURATION:.3f}s.")
    # A successful probe is not enough: decode the complete streams to catch corrupt packets.
    run(["ffmpeg", "-hide_banner", "-v", "error", "-i", path, "-f", "null", "-"])
    details = {
        "width": width, "height": height, "fps": float(rate), "expected_fps": FPS, "expected_video_codec": ("h264" if CODEC == "libx264" else CODEC),
        "frame_count": frame_count, "expected_frame_count": expected_frames,
        "has_audio": True, "decode_ok": True, "file_exists": True,
        "duration_seconds": actual_duration, "expected_duration_seconds": DURATION,
        "video_codec": video.get("codec_name", "unknown"),
        "audio_codec": audio.get("codec_name", "unknown"), "file": path
    }
    return actual_duration, details["video_codec"], details["audio_codec"], details

def analyze_render_critique(path, duration):
    """Measure long black intervals and audio level. These are risk proxies, not aesthetics."""
    errors = []
    black_segments = []
    black_cmd = [
        "ffmpeg", "-hide_banner", "-i", path, "-vf",
        "blackdetect=d=0.35:pix_th=0.05", "-an", "-f", "null", "-"
    ]
    black_result = subprocess.run(black_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, check=False)
    black_log = (black_result.stderr or "") + "\n" + (black_result.stdout or "")
    if black_result.returncode != 0:
        errors.append("blackdetect_failed")
    else:
        pattern = re.compile(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)")
        for match in pattern.finditer(black_log):
            black_segments.append({
                "start_seconds": float(match.group(1)),
                "duration_seconds": float(match.group(3)),
            })

    volume_cmd = [
        "ffmpeg", "-hide_banner", "-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"
    ]
    volume_result = subprocess.run(volume_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, check=False)
    volume_log = (volume_result.stderr or "") + "\n" + (volume_result.stdout or "")
    if volume_result.returncode != 0:
        errors.append("volumedetect_failed")

    def read_db(label):
        match = re.search(label + r":\s*(-?inf|-?\d+(?:\.\d+)?)\s*dB", volume_log, re.IGNORECASE)
        if not match or match.group(1).lower() in ("-inf", "inf"):
            return None
        try:
            value = float(match.group(1))
            return value if math.isfinite(value) else None
        except ValueError:
            return None

    mean_db = read_db("mean_volume")
    peak_db = read_db("max_volume")
    audio_silent = bool(re.search(r"(?:mean_volume|max_volume):\s*-inf\s*dB", volume_log, re.IGNORECASE))
    return {
        "black_segments": black_segments, "duration_seconds": float(duration),
        "mean_volume_db": mean_db, "max_volume_db": peak_db,
        "audio_silent": audio_silent,
        "measurement_errors": errors,
        "blackdetect_threshold_seconds": 0.35,
        "blackdetect_pixel_threshold": 0.05,
        "method": "ffmpeg-blackdetect-and-volumedetect",
    }


def _run_variant_batch(args):
    """Render independent, reviewable variants without redownloading source media."""
    output_root = Path("output") / "variants"
    output_root.mkdir(parents=True, exist_ok=True)
    if args.clip_count_options is not None and args.clip_count is not None:
        progress_event("clip_count_options", "blocked",
                       "Use either one clip-count override or a list of clip-count alternatives, not both.")
        raise SystemExit("Use either --clip-count or --clip-count-options, not both.")
    if args.clip_count_options is not None:
        if len(args.clip_count_options) != args.variants:
            progress_event("clip_count_options", "blocked",
                           f"{len(args.clip_count_options)} clip counts supplied for {args.variants} variants.")
            raise SystemExit(
                "--clip-count-options must contain exactly one count per variant; "
                "for example use --variants 3 --clip-count-options 8,12,16."
            )
        try:
            settings = json.loads(Path("params.json").read_text(encoding="utf-8"))
            edit_settings = settings["edit_settings"]
            min_clips, max_clips = int(edit_settings["min_clips"]), int(edit_settings["max_clips"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            progress_event("clip_count_options", "blocked", f"Could not validate clip options against params.json: {exc}")
            raise SystemExit(f"Cannot validate clip-count alternatives against params.json: {exc}") from exc
        outside = [count for count in args.clip_count_options if not min_clips <= count <= max_clips]
        if outside:
            progress_event(
                "clip_count_options", "blocked",
                f"Clip counts {outside} are outside configured bounds {min_clips}–{max_clips}.",
                {"requested": list(args.clip_count_options), "min_clips": min_clips, "max_clips": max_clips},
            )
            raise SystemExit(
                f"Every --clip-count-options value must be within params.json bounds {min_clips}–{max_clips}; "
                f"invalid: {outside}."
            )
    progress_event(
        "variant_batch", "running",
        f"Preparing {args.variants} candidate render(s).",
        {"variants": args.variants, "clip_count_options": list(args.clip_count_options) if args.clip_count_options else None},
    )
    results = []
    for index in range(1, args.variants + 1):
        variant_dir = output_root / f"variant_{index:02d}"
        final_path = variant_dir / "final_phonk.mp4"
        report_path = variant_dir / "agent_report.json"
        before_final = final_path.stat().st_mtime if final_path.is_file() else None
        before_report = report_path.stat().st_mtime if report_path.is_file() else None
        started = time.time()
        command = [
            sys.executable, str(Path(__file__).resolve()),
            "--variants", "1", "--variant-index", str(index),
        ]
        # Download inputs once. Later variants reuse the validated local copies,
        # including audio extracted from the reference when no music URL was given.
        if index == 1:
            for flag, value in (
                ("--video-url", args.video_url),
                ("--music-url", args.music_url),
                ("--reference-url", args.reference_url),
            ):
                if value:
                    command.extend([flag, value])
        selected_clip_count = (
            args.clip_count_options[index - 1] if args.clip_count_options
            else args.clip_count
        )
        variant_label = VARIANT_LABELS.get(index, "Reference-timed source variation")
        if selected_clip_count is not None:
            if args.clip_count_options:
                variant_label = f"{selected_clip_count} clips | same source progression"
                command.append("--same-source-progression")
            else:
                variant_label = f"{selected_clip_count} clips | {variant_label}"
            command.extend(["--clip-count", str(selected_clip_count)])
        progress_event(
            "variant_start", "running", f"Rendering candidate {index}/{args.variants}: {variant_label}",
            {"index": index, "clip_count": selected_clip_count, "video_path": str(final_path)},
        )
        print()
        print(f"[variants] Rendering {index}/{args.variants}: {variant_label}", flush=True)
        completed = subprocess.run(command, check=False)
        report = {}
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                report = {}
        fresh_final = final_path.is_file() and (before_final is None or final_path.stat().st_mtime > before_final)
        fresh_report = report_path.is_file() and (before_report is None or report_path.stat().st_mtime > before_report)
        export_status = report.get("results", {}).get("export_storage", {}).get("status")
        status_ok = report.get("status") == "ready_for_human_review" and export_status == "ok"
        success = completed.returncode == 0 and fresh_final and fresh_report and status_ok
        results.append({
            "index": index,
            "label": variant_label,
            "clip_count": selected_clip_count if selected_clip_count is not None else report.get("clip_selection", {}).get("selected_clip_count"),
            "status": "ok" if success else "failed",
            "exit_code": completed.returncode,
            "video": str(final_path) if final_path.is_file() else None,
            "agent_report": str(report_path) if report_path.is_file() else None,
            "director_status": report.get("status"),
            "export_status": export_status,
        })
        progress_event(
            "variant_complete", "success" if success else "error",
            f"Candidate {index}/{args.variants}: {'approved for human review' if success else 'failed QA or render checks'}.",
            results[-1],
        )
        if index == 1 and not success:
            # If the first run could not prepare inputs, subsequent runs would only
            # repeat the same missing-input failure. Record them as unattempted.
            for remaining in range(2, args.variants + 1):
                results.append({
                    "index": remaining,
                    "label": VARIANT_LABELS.get(remaining, "Reference-timed source variation"),
                    "status": "not_run", "video": None, "agent_report": None,
                    "reason": "The first variant failed before producing a fresh, QA-approved output.",
                })
            break
    manifest = {
        "requested_variants": args.variants,
        "minimum_requested": 3,
        "same_reference_timing_and_soundtrack": True,
        "clip_count": args.clip_count,
        "clip_count_options": list(args.clip_count_options) if args.clip_count_options else None,
        "differences": (
            "Only motion clip count varies; balanced source-time progression, reference shot-length pacing, configured effects and soundtrack are held constant."
            if args.clip_count_options else
            f"All candidates use {args.clip_count} motion clips and vary source-time progression; effects, reference pacing and soundtrack remain shared."
            if args.clip_count is not None else
            "Only the progression through source timestamps varies; added effects, reference cut pacing and audio source remain shared."
        ),
        "variants": results,
    }
    manifest_path = output_root / "index.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"[variants] Comparison manifest: {manifest_path}", flush=True)
    progress_event("variant_batch", "completed" if all(item["status"] == "ok" for item in results) else "error",
                   f"Comparison manifest written to {manifest_path}.",
                   {"manifest_path": str(manifest_path), "variants": results})
    for result in results:
        print(f"[variants] {result['index']}: {result['status']} | {result.get('video') or result.get('reason', '')}", flush=True)
    if len(results) != args.variants or any(item["status"] != "ok" for item in results):
        raise SystemExit(1)


def main(argv=None):
    global VIDEO, MUSIC, REFERENCE, EDIT_DURATION, DURATION, FREEZE, SUBJECT_OBSERVATIONS
    global OUTDIR, WORK, FINAL, VARIANT_INDEX
    args = parse_media_source_args(argv)
    if args.clip_count_options is not None and args.clip_count is not None:
        raise SystemExit("Use either --clip-count or --clip-count-options, not both.")
    if args.clip_count_options is not None and args.variant_index is None and args.variants == 1:
        if len(args.clip_count_options) != 1:
            raise SystemExit("--variants 1 requires exactly one --clip-count-options value.")
        args.clip_count = args.clip_count_options[0]
    if args.variant_index is None and args.variants > 1:
        Path(OUTDIR).mkdir(parents=True, exist_ok=True)
        reset_progress_log()
        progress_event("run", "started", "Starting comparison render batch.")
        _run_variant_batch(args)
        return
    VARIANT_INDEX = args.variant_index
    if VARIANT_INDEX is not None:
        OUTDIR = str(Path("output") / "variants" / f"variant_{VARIANT_INDEX:02d}")
        WORK = str(Path(OUTDIR) / "work")
        FINAL = str(Path(OUTDIR) / "final_phonk.mp4")
    reset_progress_log()
    progress_event("run", "started", "Heyaa render pipeline started.",
                   {"variant_index": VARIANT_INDEX, "variants_requested": args.variants,
                    "clip_count_override": args.clip_count})
    progress_event("settings", "running", "Validating params.json.")
    load_settings()
    progress_event("settings", "completed", "Settings validated.",
                   {"resolution": f"{WIDTH}x{HEIGHT}", "fps": FPS,
                    "duration_seconds": DURATION, "freeze_seconds": FREEZE,
                    "min_clips": MIN_CLIPS, "max_clips": MAX_CLIPS})
    if args.clip_count is not None:
        progress_event("clip_count_override", "running",
                       f"Validating requested motion clip count {args.clip_count}.")
        choose_clip_count(None, args.clip_count)
        progress_event("clip_count_override", "completed",
                       f"Requested motion clip count {args.clip_count} is within configured bounds.")
    progress_event("ai_upscale_preflight", "running", "Checking configured Real-ESRGAN executable and model weights.")
    resolve_ai_upscaler()
    progress_event(
        "ai_upscale_preflight", "completed" if AI_UPSCALE_ENABLED else "skipped",
        (f"Real-ESRGAN ready ({AI_UPSCALE_MODEL} x{AI_UPSCALE_SCALE})."
         if AI_UPSCALE_ENABLED else "AI restoration disabled by settings."),
        {"enabled": AI_UPSCALE_ENABLED, "model": AI_UPSCALE_MODEL, "scale": AI_UPSCALE_SCALE},
    )
    progress_event("source_preparation", "running", "Preparing and validating source video, music, and optional reference.")
    VIDEO, MUSIC, REFERENCE = prepare_media_sources(
        video_url=args.video_url,
        music_url=args.music_url,
        reference_url=args.reference_url,
        video_path=VIDEO,
        music_path=MUSIC,
        reference_path=REFERENCE,
    )
    progress_event("source_preparation", "completed", "Required source files validated.",
                   {"video": VIDEO, "music": MUSIC,
                    "reference": REFERENCE if Path(REFERENCE).is_file() else None})
    EDIT_DURATION = DURATION - FREEZE
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    for path in (VIDEO, MUSIC):
        if not os.path.isfile(path):
            raise SystemExit(f"[ERROR] Missing required file: {path}")

    source_duration = duration_of(VIDEO)
    music_duration = duration_of(MUSIC)
    if source_duration < 0.8:
        raise SystemExit("[ERROR] Source video is too short to edit.")
    print(f"[source] Video {source_duration:.2f}s | Music {music_duration:.2f}s")
    print(f"[target] {WIDTH}x{HEIGHT}, {FPS} FPS, {DURATION:.1f}s, Phonk/Montagem")

    progress_event("media_analysis", "running", "Detecting source scene changes.")
    scenes = detect_scenes(VIDEO, source_duration)
    progress_event("media_analysis", "completed", f"Measured {len(scenes)} source scene-change candidate(s).",
                   {"scene_change_count": len(scenes), "source_duration_seconds": source_duration})
    available_edit_duration = DURATION - FREEZE
    progress_event("beat_analysis", "running", "Measuring bass-onset / beat candidates.")
    raw_beats = detect_music_beats(MUSIC, available_edit_duration) if BEAT_SYNC else []
    beats = extend_looped_beats(raw_beats, music_duration, available_edit_duration, MUSIC_LOOP)
    progress_event("beat_analysis", "completed" if BEAT_SYNC else "skipped",
                   f"Prepared {len(beats)} timing candidate(s).",
                   {"beat_sync_enabled": BEAT_SYNC, "candidate_count": len(beats),
                    "music_loop_enabled": MUSIC_LOOP})
    drop_beat_time = choose_drop_beat(music_duration, available_edit_duration, MUSIC_LOOP)
    total_frames, freeze_frames = round(DURATION * FPS), round(FREEZE * FPS)
    drop_freeze_frames = max(1, round(DROP_FREEZE_DURATION * FPS)) if drop_beat_time is not None else 0
    drop_freeze_duration = drop_freeze_frames / FPS
    EDIT_DURATION = (total_frames - freeze_frames - drop_freeze_frames) / FPS
    adjusted_beats = [
        round(beat if drop_beat_time is None or beat <= drop_beat_time else beat - drop_freeze_duration, 6)
        for beat in beats if beat < available_edit_duration
    ]
    progress_event("reference_analysis", "running" if REFERENCE_PACING else "skipped",
                   "Measuring reference shot pacing." if REFERENCE_PACING else "Reference pacing is disabled.")
    ref_profile = reference_pacing_profile(REFERENCE) if REFERENCE_PACING else None
    ref_interval = ref_profile.get("median_cut_interval_seconds") if ref_profile else None
    progress_event("reference_analysis", "completed" if ref_interval is not None else ("skipped" if not REFERENCE_PACING else "needs_review"),
                   "Reference pacing profile ready." if ref_interval is not None else "No usable measured reference interval; configured fallback will be used.",
                   {"median_cut_interval_seconds": ref_interval,
                    "reference_available": bool(ref_profile and ref_profile.get("available"))})
    clip_count = choose_clip_count(ref_interval, args.clip_count)
    clip_selection_mode = (
        "explicit_user_choice" if args.clip_count is not None
        else "reference_pacing" if ref_interval is not None
        else "configured_minimum_fallback"
    )
    progress_event("clip_planning", "completed",
                   f"Selected {clip_count} motion clips ({clip_selection_mode.replace('_', ' ')}).",
                   {"selected_clip_count": clip_count, "selection_mode": clip_selection_mode,
                    "requested_clip_count": args.clip_count, "min_clips": MIN_CLIPS,
                    "max_clips": MAX_CLIPS, "reference_median_cut_interval_seconds": ref_interval})
    boundaries_seconds = make_boundaries(clip_count, adjusted_beats, ref_profile)
    planned_drop_position = None
    if drop_beat_time is not None:
        boundaries_seconds, planned_drop_position = insert_drop_boundary(boundaries_seconds, drop_beat_time)
        print(
            f"[edit] Drop-impact freeze: strongest bass-onset proxy at {drop_beat_time:.2f}s; "
            f"freeze boundary={planned_drop_position:.2f}s for {drop_freeze_duration:.3f}s."
        )
    total_motion_frames = total_frames - freeze_frames - drop_freeze_frames
    frame_boundaries = [round(value * FPS) for value in boundaries_seconds]
    frame_boundaries[0], frame_boundaries[-1] = 0, total_motion_frames
    frame_boundaries = sorted(set(frame_boundaries))
    if len(frame_boundaries) != clip_count + 1:
        raise RuntimeError("Frame quantization changed the planned clip count; regenerate the edit plan.")
    if len(frame_boundaries) < 2 or frame_boundaries[0] != 0 or frame_boundaries[-1] != total_motion_frames:
        raise RuntimeError("Could not create contiguous integer-frame EDL boundaries.")
    drop_frame = round(planned_drop_position * FPS) if planned_drop_position is not None else None
    context = choose_context_window(source_duration, scenes, EDIT_DURATION)
    context_start, context_end = context["start_seconds"], context["end_seconds"]
    subject_analysis = detect_person_track(VIDEO, context_start, context_end)
    SUBJECT_OBSERVATIONS = subject_analysis.get("observations", []) if subject_analysis.get("detected") else []
    context["subject_tracking"] = {
        key: value for key, value in subject_analysis.items() if key != "observations"
    }
    if subject_analysis.get("detected"):
        print(
            f"[context] OpenCV found an appearance-consistent person track "
            f"({subject_analysis.get('track_span_seconds')}s span; "
            f"quality proxy={subject_analysis.get('track_quality_proxy')}). "
            "Per-shot source centers and 9:16 crops will follow nearby observations."
        )
    else:
        print(
            f"[context] Person tracking unavailable: {subject_analysis.get('reason', 'no stable track')}. "
            "Using scene-density context and centered-crop fallback."
        )
    context_duration = max(0.1, context_end - context_start)
    context_scenes = sorted(cut - context_start for cut in scenes if context_start <= cut <= context_end)
    edl_video = []
    output_cursor = 0
    source_gap_frames = round(MIN_SOURCE_GAP_SECONDS * FPS)
    previous_source_end_f = None
    for start_f, end_f in zip(frame_boundaries, frame_boundaries[1:]):
        dur_f = end_f - start_f
        if dur_f <= 0:
            raise RuntimeError("EDL contains a zero-length clip after frame quantization.")
        timeline_center = (start_f + dur_f / 2) / FPS
        progress = max(0.0, min(1.0, timeline_center / max(EDIT_DURATION, 1 / FPS)))
        source_power = 1.0 if args.same_source_progression else VARIANT_SOURCE_POWERS.get(VARIANT_INDEX, 1.0)
        # Keep the reference-derived output cut times identical across variants;
        # vary only which point in the same coherent source window each shot samples.
        local_target = (progress ** source_power) * context_duration
        local_center = choose_source_center(local_target, context_scenes, context_duration)
        source_center = context_start + local_center
        track_observation = subject_observation_near(
            SUBJECT_OBSERVATIONS, source_center,
            max_distance_seconds=max(1.5, dur_f / FPS)
        )
        if track_observation is not None:
            source_center = float(track_observation["time_seconds"])
        source_dur_f = max(1, round(dur_f * SPEED))
        source_start_seconds = max(0.0, min(
            source_center - (source_dur_f / FPS) / 2,
            max(0.0, source_duration - source_dur_f / FPS)
        ))
        candidate_source_start_f = round(source_start_seconds * FPS)
        max_source_start_f = round(source_duration * FPS) - source_dur_f
        source_start_f = enforce_source_progression(
            candidate_source_start_f, source_dur_f, previous_source_end_f,
            source_gap_frames, max_source_start_f,
        )
        if source_start_f != candidate_source_start_f:
            clip_number = sum(1 for x in edl_video if x["type"] == "clip") + 1
            print(
                f"[edit] Shifted source start for clip {clip_number} from frame "
                f"{candidate_source_start_f} to {source_start_f} to prevent source overlap.", flush=True
            )
        previous_source_end_f = source_start_f + source_dur_f
        edl_video.append({
            "type": "clip", "source": VIDEO,
            "source_start_f": source_start_f,
            "source_dur_f": source_dur_f,
            "start_f": output_cursor, "dur_f": dur_f, "speed": SPEED,
            "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
        })
        output_cursor += dur_f
        if drop_frame is not None and end_f == drop_frame:
            edl_video.append({
                "type": "freeze", "source": "timeline:last_frame",
                "source_frame_f": max(0, output_cursor - 1),
                "start_f": output_cursor, "dur_f": drop_freeze_frames,
                "effect": "drop-impact-freeze"
            })
            output_cursor += drop_freeze_frames
    edit_frames = total_frames - freeze_frames
    if output_cursor != edit_frames:
        raise RuntimeError(
            f"EDL motion and drop freeze end at frame {output_cursor}, expected final freeze at {edit_frames}."
        )
    edl_video.append({
        "type": "freeze", "source": "timeline:last_frame", "source_frame_f": max(0, edit_frames - 1),
        "start_f": edit_frames, "dur_f": freeze_frames, "effect": "phonk-freeze"
    })
    edl = {
        "version": 1, "fps_num": FPS, "fps_den": 1, "width": WIDTH, "height": HEIGHT,
        "total_frames": total_frames, "video": edl_video,
        "audio": [{"source": MUSIC, "source_start_f": 0, "start_f": 0, "dur_f": total_frames,
                   "gain_db": 0.0, "fade_out_f": min(total_frames, round(0.8 * FPS))}]
    }
    validate_edl(edl, min_source_gap_f=source_gap_frames)
    # Fail before expensive clip rendering if the contract contains features the
    # current FFmpeg renderer explicitly does not implement.
    freeze_items = [item for item in edl["video"] if item["type"] == "freeze"]
    if (edl["video"][-1]["type"] != "freeze" or len(freeze_items) not in (1, 2) or
            freeze_items[-1].get("effect") != "phonk-freeze" or
            any(item.get("effect") != "drop-impact-freeze" for item in freeze_items[:-1])):
        raise RuntimeError("EDL must end with one Phonk final freeze and may include one drop-impact freeze.")
    if len(edl["audio"]) != 1:
        raise RuntimeError("Current FFmpeg renderer supports exactly one EDL audio segment.")
    if edl["audio"][0]["start_f"] != 0 or edl["audio"][0]["dur_f"] != edl["total_frames"]:
        raise RuntimeError("Current renderer requires audio to span the full EDL timeline.")
    for index, item in enumerate(edl["video"]):
        if item["type"] == "clip":
            crop = item["crop"]
            if any(abs(float(crop[key]) - value) > 1e-6 for key, value in
                   (("x", 0.0), ("y", 0.0), ("w", 1.0), ("h", 1.0))):
                raise RuntimeError(f"EDL video[{index}] requests a crop rectangle not implemented by the current renderer.")
    # From this point on, read final segment boundaries back from the validated EDL,
    # rather than independently re-deriving the timeline for the FFmpeg stage.
    total_frames = edl["total_frames"]
    freeze_item = edl["video"][-1]
    if freeze_item["type"] != "freeze":
        raise RuntimeError("The final EDL video item must be the explicit freeze segment.")
    edit_frames, freeze_frames = freeze_item["start_f"], freeze_item["dur_f"]
    if edit_frames + freeze_frames != total_frames:
        raise RuntimeError("EDL freeze segment does not end at total_frames.")
    FREEZE = freeze_frames / FPS
    EDIT_DURATION = edit_frames / FPS
    DURATION = total_frames / FPS
    with open(os.path.join(OUTDIR, "edit_decision_list.json"), "w", encoding="utf-8") as handle:
        json.dump(edl, handle, ensure_ascii=False, indent=2)
    actual_motion_clip_count = len([item for item in edl_video if item["type"] == "clip"])
    print(f"[edl] Validated {actual_motion_clip_count} clips + "
          f"{len([item for item in edl_video if item['type'] == 'freeze'])} freeze segments; "
          f"{total_frames} frames, no gaps.")
    progress_event("edl_validation", "completed",
                   f"EDL validated: {actual_motion_clip_count} motion clips and {total_frames} frames, no gaps.",
                   {"motion_clip_count": actual_motion_clip_count, "total_frames": total_frames,
                    "clip_selection_mode": clip_selection_mode})
    pre_render_review = build_pre_render_review(
        edl, len(beats), drop_beat_time, drop_freeze_duration, ref_profile, context, subject_analysis
    )
    with open(os.path.join(OUTDIR, "pre_render_review.json"), "w", encoding="utf-8") as handle:
        json.dump(pre_render_review, handle, ensure_ascii=False, indent=2)
    print_pre_render_review(pre_render_review)

    print("[render 1/4] Building clips and the drop-impact freeze from the validated EDL...")
    clips = []
    previous_clip = None
    clip_number = 0
    clip_total = sum(1 for x in edl_video if x["type"] == "clip")
    for index, item in enumerate(edl_video[:-1]):
        if item["type"] == "clip":
            clip_number += 1
            length = item["dur_f"] / FPS
            center = item["source_start_f"] / FPS + (item["source_dur_f"] / FPS) / 2
            progress_event("render_clip", "running", f"Rendering motion clip {clip_number}/{clip_total}.",
                           {"clip_number": clip_number, "clip_total": clip_total,
                            "source_center_seconds": round(center, 4),
                            "output_duration_seconds": round(length, 4)})
            print(f"  EDL clip {clip_number}/{clip_total}: source {center:.2f}s, output {length:.3f}s")
            clip_path = make_clip(index, item, source_duration)
            progress_event("render_clip", "completed", f"Motion clip {clip_number}/{clip_total} rendered.",
                           {"clip_number": clip_number, "clip_total": clip_total,
                            "output_duration_seconds": round(length, 4)})
        else:
            progress_event("drop_impact_freeze", "running",
                           f"Rendering the {item['dur_f'] / FPS:.3f}s drop-impact hold.")
            print(f"  [impact] Holding the preceding shot for {item['dur_f'] / FPS:.3f}s in black-and-white with a brief shake.")
            if previous_clip is None:
                raise RuntimeError("Drop-impact freeze appeared before the first rendered shot.")
            clip_path = make_freeze_clip(index, item, previous_clip)
            progress_event("drop_impact_freeze", "completed", "Drop-impact hold rendered.")
        clips.append(clip_path)
        previous_clip = clip_path

    progress_event("clip_render", "completed", f"Rendered {clip_total} motion clips.")
    print("[render 2/4] Joining clips and the impact hold...")
    progress_event("timeline_assembly", "running", "Joining all rendered clips and the drop-impact hold.")
    concat_file = f"{WORK}/concat.txt"
    with open(concat_file, "w", encoding="utf-8") as handle:
        for clip in clips:
            absolute = os.path.abspath(clip).replace("'", "'\\''")
            handle.write(f"file '{absolute}'\n")
    joined = f"{WORK}/joined.mp4"
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-c", "copy", joined
    ])
    progress_event("timeline_assembly", "completed", "Rendered clips joined without re-encoding.")

    print("[render 3/4] Adding bass-hit flashes, cinematic skull freeze, and Phonk audio...")
    progress_event("final_render", "running", "Applying configured flashes, skull freeze, audio processing and final encoding.")
    final_video = f"{WORK}/final_render.mp4"
    flash_filter = make_flash_filter(beats)
    # Pad first, then split: the impact branch reads the cloned tail frames.
    # Only the freeze branch is enlarged/shaken, so normal footage stays stable.
    base_chain = (
        f"tpad=stop_mode=clone:stop={freeze_frames},"
        f"eq=contrast=1.32:saturation=0:enable='gte(t,{EDIT_DURATION:.6f})'"
    )
    if flash_filter:
        base_chain += "," + flash_filter
    base_chain += (
        f",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.78:t=fill:"
        f"enable='between(t,{EDIT_DURATION - 0.10:.3f},{EDIT_DURATION - 0.055:.3f})'"
    )
    impact_chain = (
        f"trim=start_frame={edit_frames}:end_frame={total_frames},"
        "setpts=PTS-STARTPTS,"
        f"fps={FPS},"
        "scale=1188:2112:flags=lanczos,"
        "crop=1080:1920:"
        "x='(iw-ow)/2+18*sin(t*70)':"
        "y='(ih-oh)/2+18*cos(t*57)',"
        "eq=contrast=1.48:saturation=0:brightness=0.015,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=white@0.55:t=fill:"
        "enable='lt(t,0.055)',"
        f"setpts=PTS+{EDIT_DURATION:.6f}/TB"
    )
    filter_graph = (
        f"[0:v]{base_chain},split[base][impact_src];"
        "[base]setsar=1[baseout];"
        f"[impact_src]{impact_chain}[impact_raw];"
        "[2:v]scale=420:-1[skull];"
        f"[impact_raw][skull]overlay=(W-w)/2:(H-h)/2:enable='gte(t,{EDIT_DURATION:.5f})'[impact];"
        f"[baseout][impact]overlay=0:0:enable='gte(t,{EDIT_DURATION:.5f})',"
        f"trim=end_frame={total_frames},setsar=1[outv]"
    )
    edl_audio = edl["audio"][0]
    audio_source = edl_audio["source"]
    audio_start_seconds = edl_audio["source_start_f"] / FPS
    fade_out_seconds = edl_audio.get("fade_out_f", 0) / FPS
    fade_in_seconds = edl_audio.get("fade_in_f", 0) / FPS
    gain_db = float(edl_audio.get("gain_db", 0.0))
    audio_filters = []
    if abs(gain_db) > 1e-9:
        audio_filters.append(f"volume={gain_db:.4f}dB")
    if BASS_BOOST:
        audio_filters.append("bass=g=3:f=90:w=0.5")
    if fade_in_seconds > 0:
        audio_filters.append(f"afade=t=in:st=0:d={fade_in_seconds:.6f}")
    audio_filters.extend([f"apad=whole_dur={DURATION:.6f}", f"atrim=duration={DURATION:.6f}"])
    if fade_out_seconds > 0:
        fade_start = max(0.0, DURATION - fade_out_seconds)
        audio_filters.append(f"afade=t=out:st={fade_start:.6f}:d={fade_out_seconds:.6f}")
    # Keep a final ceiling even when bass boost is disabled; audio transients
    # otherwise can leave the exported encode at/near 0 dBFS.
    audio_filters.append("alimiter=limit=0.90:level=0")
    audio_filter = ",".join(audio_filters)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", joined]
    if MUSIC_LOOP:
        cmd += ["-stream_loop", "-1"]
    if audio_start_seconds > 0:
        cmd += ["-ss", f"{audio_start_seconds:.6f}"]
    cmd += ["-i", audio_source, "-loop", "1", "-framerate", str(FPS), "-i", SKULL_ASSET,
            "-filter_complex", filter_graph, "-map", "[outv]", "-map", "1:a:0",
            "-af", audio_filter, "-t", f"{DURATION:.6f}", "-frames:v", str(total_frames),
            "-c:v", CODEC, "-preset", PRESET, "-crf", str(CRF),
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-threads", "2", final_video]
    run(cmd)
    progress_event("final_render", "completed", "FFmpeg final encode finished.")

    print("[render 4/4] Verifying the rendered file...")
    progress_event("render_inspection", "running", "Inspector is verifying video streams, exact frame count, duration and full decode.")
    actual, video_codec, audio_codec, render_report = verify_output(final_video)
    progress_event("render_inspection", "completed", "Inspector file-integrity checks finished.",
                   {"width": render_report.get("width"), "height": render_report.get("height"),
                    "fps": render_report.get("fps"), "frame_count": render_report.get("frame_count"),
                    "duration_seconds": render_report.get("duration_seconds")})
    source_streams = probe(VIDEO).get("streams", [])
    source_video = next((stream for stream in source_streams if stream.get("codec_type") == "video"), {})
    media_analysis = {
        "source_duration_seconds": source_duration,
        "source_width": int(source_video.get("width", 0)),
        "source_height": int(source_video.get("height", 0)),
        "scene_cut_count": len(scenes),
        "music_duration_seconds": music_duration,
        "context_window": context,
        "context_caveat": "Temporal scene-cut-density proxy only; no semantic person identification in this build.",
    }
    beat_analysis = {
        "enabled": BEAT_SYNC,
        "candidate_count": len(beats),
        "source_candidate_count": len(raw_beats),
        "loop_expanded": len(beats) > len(raw_beats),
        "fallback": "even_pacing" if BEAT_SYNC and len(beats) < 3 else None,
        "method": "bass-lowpass-rms-novelty-autocorrelation-heuristic" if BEAT_SYNC else "disabled",
        "drop_beat_time_seconds": drop_beat_time,
        "drop_beat_strength_proxy": DROP_BEAT_STRENGTH if drop_beat_time is not None else None,
        "drop_freeze_frames": drop_freeze_frames,
        "drop_freeze_duration_seconds": drop_freeze_duration,
    }
    reference_analysis = {
        "enabled": REFERENCE_PACING,
        "available": os.path.isfile(REFERENCE) and ref_interval is not None,
        "median_cut_interval_seconds": ref_interval,
        "source": REFERENCE if os.path.isfile(REFERENCE) else None,
        "shot_intervals_seconds": ref_profile.get("shot_intervals_seconds", []) if ref_profile else [],
        "cut_timestamps_seconds": ref_profile.get("cut_timestamps_seconds", []) if ref_profile else [],
        "used_absolute_cut_timestamps": REFERENCE_CUT_TIMESTAMPS_USED,
        "scene_cut_count": ref_profile.get("scene_cut_count") if ref_profile else None,
        "used_for_planning": bool(ref_profile),
        "method": ref_profile.get("method") if ref_profile else None,
        "semantic_reference_understanding": False,
    }
    hook_window = min(2.0, actual)
    final_scenes = detect_scenes(final_video, actual, scan_duration=hook_window)
    opening_cut_count = sum(1 for time in final_scenes if 0.0 < time <= hook_window)
    expected_opening_cuts = max(1.0, hook_window)
    opening_activity_proxy = max(
        0.0,
        min(1.0, 1.0 - abs(float(opening_cut_count) - expected_opening_cuts) /
            max(2.0, expected_opening_cuts * 1.5))
    )
    hook_analysis = {
        "window_seconds": hook_window,
        "opening_scene_change_count": opening_cut_count,
        "opening_activity_proxy": round(opening_activity_proxy, 4),
        "measurement": "ffmpeg_scene_change",
        "semantic_hook_assessed": False,
    }
    cut_times = [
        item["start_f"] / FPS for item in edl_video[:-1]
        if item["type"] == "clip" and item["start_f"] > 0
    ]
    niche_metrics = {}
    if cut_times and beats:
        tolerance = 0.12
        alignment = [max(0.0, 1.0 - min(abs(cut - beat) for beat in beats) / tolerance)
                     for cut in cut_times]
        niche_metrics["beat_alignment"] = round(sum(alignment) / len(alignment), 4)
    source_width = int(source_video.get("width", 0))
    source_height = int(source_video.get("height", 0))
    if source_width > 0 and source_height > 0:
        niche_metrics["visual_clarity"] = round(max(
            0.0, min(1.0, source_width / WIDTH, source_height / HEIGHT)
        ), 4)
    niche_metrics["hook_strength"] = round(opening_activity_proxy, 4)
    context_window_seconds = max(0.1, float(context.get("window_seconds", 0.1)))
    niche_metrics["motion_energy"] = round(max(
        0.0, min(1.0, float(context.get("scene_cuts", 0)) / max(1.0, context_window_seconds / 2.0))
    ), 4)
    if DROP_BEAT_STRENGTH is not None and drop_beat_time is not None:
        niche_metrics["drop_impact"] = round(float(DROP_BEAT_STRENGTH), 4)
    niche_metrics["metric_methods"] = {
        "beat_alignment": "EDL cut distance from bass-onset candidates within 120ms",
        "visual_clarity": "source pixel support ratio versus 1080x1920 output (not a sharpness/subject-visibility model)",
        "hook_strength": "opening scene-change cadence proxy only; no semantic hook understanding",
        "motion_energy": "scene cuts per two seconds inside selected temporal context window",
        "drop_impact": "relative strongest bass-onset novelty proxy; not a true musical drop classifier",
    }
    render_critique = analyze_render_critique(final_video, actual)

    progress_event("render_critique", "completed", "Render Critic has measured black intervals and output audio levels.",
                   {"black_segment_count": len(render_critique.get("black_segments", [])),
                    "mean_volume_db": render_critique.get("mean_volume_db"),
                    "max_volume_db": render_critique.get("max_volume_db")})

    def print_agent_event(event):
        # Stream each structured agent result to the terminal and durable JSONL trace.
        print(f"[agent:{event['agent']}] {event['status']}: {event['summary']}", flush=True)
        progress_event(
            f"agent:{event['agent']}", event["status"], event["summary"],
            {"agent_event": event}, echo=False,
        )

    agent_report = run_agent_team({
        "settings": CONFIG, "edl": edl,
        "media_analysis": media_analysis, "beat_analysis": beat_analysis,
        "reference_analysis": reference_analysis, "hook_analysis": hook_analysis,
        "render_critique": render_critique, "niche_metrics": niche_metrics,
        "niche_tags": ["phonk", "montagem", "vertical", "freeze"],
        "render_report": render_report,
    }, emit=print_agent_event, emit_progress=print_agent_event)
    agent_report["pre_render_review"] = pre_render_review
    agent_report["clip_selection"] = {
        "selected_clip_count": actual_motion_clip_count,
        "requested_clip_count": args.clip_count,
        "selection_mode": clip_selection_mode,
        "min_clips": MIN_CLIPS,
        "max_clips": MAX_CLIPS,
        "reference_median_cut_interval_seconds": ref_interval,
        "comparison_clip_count_options": list(args.clip_count_options) if args.clip_count_options else None,
    }
    agent_report["progress_log"] = str(Path(OUTDIR) / "progress.jsonl")
    if VARIANT_INDEX is not None:
        agent_report["variant"] = {
            "index": VARIANT_INDEX,
            "label": VARIANT_LABELS.get(VARIANT_INDEX, "Reference-timed source variation"),
            "source_time_curve_power": VARIANT_SOURCE_POWERS.get(VARIANT_INDEX, 1.0),
            "shared_reference_timing": True,
            "shared_soundtrack": MUSIC,
            "note": "Variation changes source-time emphasis only; it does not add extra overlays or effects beyond the configured edit.",
        }
    print("[agent conference] Evidence-linked post-render review (not independent LLM chat):", flush=True)
    for turn in agent_report.get("agent_dialogue", []):
        print(f"[conference {turn['turn']}] {turn['speaker']} -> {turn['to']}: {turn['message']}")
    report_path = os.path.join(OUTDIR, "agent_report.json")
    progress_event("director_decision", "blocked" if agent_report["status"] == "blocked" else "ready_for_human_review",
                   agent_report.get("summary", "Director decision recorded."),
                   {"blockers": agent_report.get("results", {}).get("director", {}).get("evidence", {}).get("blockers", []),
                    "human_review_required": True})
    if agent_report["status"] == "blocked":
        storage_result = export_storage_agent(final_video, FINAL, technical_qa_passed=False)
        storage_entry = {
            "agent": storage_result.agent, "status": storage_result.status,
            "score": storage_result.score, "confidence": storage_result.confidence,
            "findings": list(storage_result.findings),
            "recommendations": list(storage_result.recommendations),
            "evidence": storage_result.evidence,
        }
        agent_report["results"]["export_storage"] = storage_entry
        agent_report["events"].append({
            "agent": "export_storage", "stage": "export_promotion",
            "status": storage_result.status, "summary": storage_result.findings[0],
            "data": {"score": storage_result.score, "confidence": storage_result.confidence,
                     "findings": list(storage_result.findings),
                     "recommendations": list(storage_result.recommendations),
                     "evidence": storage_result.evidence},
        })
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(agent_report, handle, ensure_ascii=False, indent=2)
        raise RuntimeError("Technical QA blocked export; previous final file was preserved. See output/agent_report.json.")
    # Export Storage performs the actual atomic promotion after the Director decision.
    export_result_obj = export_storage_agent(
        final_video, FINAL,
        technical_qa_passed=(agent_report["results"]["director"]["status"] == "ready_for_human_review"),
    )
    export_result = {
        "agent": export_result_obj.agent, "status": export_result_obj.status,
        "score": export_result_obj.score, "confidence": export_result_obj.confidence,
        "findings": list(export_result_obj.findings),
        "recommendations": list(export_result_obj.recommendations),
        "evidence": export_result_obj.evidence,
    }
    agent_report["results"]["export_storage"] = export_result
    progress_event("export_storage", export_result["status"],
                   export_result["findings"][0],
                   {"final_path": FINAL, "technical_qa_passed": export_result_obj.status == "ok"})
    export_event = {
        "agent": "export_storage", "stage": "export_promotion", "status": export_result["status"],
        "summary": export_result["findings"][0],
        "data": {"score": export_result["score"], "confidence": export_result["confidence"],
                 "findings": export_result["findings"],
                 "recommendations": export_result["recommendations"], "evidence": export_result["evidence"]},
    }
    agent_report["events"].append(export_event)
    if export_result_obj.status != "ok":
        agent_report["status"] = "blocked"
        agent_report["summary"] = "Export Storage blocked promotion; the existing final video was preserved."
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(agent_report, handle, ensure_ascii=False, indent=2)
        raise RuntimeError("Export Storage could not promote the verified render; see output/agent_report.json.")
    render_report["file"] = FINAL
    agent_report["render_report"]["file"] = FINAL
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(agent_report, handle, ensure_ascii=False, indent=2)
    print(f"[OK] Final video: {FINAL}")
    print(f"[OK] Duration: {actual:.3f}s | Resolution: {WIDTH}x{HEIGHT} | FPS: {FPS} | frames: {render_report['frame_count']}")
    print(f"[OK] Video codec: {video_codec} | Audio codec: {audio_codec}")
    agent_report["enhancement"] = {
        "ai_upscale_requested": AI_UPSCALE_ENABLED,
        "ai_upscale_applied": AI_UPSCALE_ENABLED,
        "method": f"Real-ESRGAN {AI_UPSCALE_MODEL} x{AI_UPSCALE_SCALE}" if AI_UPSCALE_ENABLED else "Lanczos/FFmpeg scaling",
        "synthetic_detail_warning": (
            "AI restoration may synthesize plausible texture; generated details are not verified source truth."
            if AI_UPSCALE_ENABLED else
            "AI restoration was disabled; only standard FFmpeg scaling/sharpening was applied."
        ),
    }
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(agent_report, handle, ensure_ascii=False, indent=2)
    print(f"[agents] Status: {agent_report['status']} | report: {report_path}")
    print(f"[agents] Niche result: {agent_report['results']['niche_analyst']['status']} (no unsupported virality score)")
    print("[NOTE] Reference mode learns rough cut pacing; it does not copy copyrighted frames/effects.")
    if AI_UPSCALE_ENABLED:
        print(f"[NOTE] Real-ESRGAN AI restoration applied ({AI_UPSCALE_MODEL}, {AI_UPSCALE_SCALE}x). Its generated texture is plausible enhancement, not verified original detail.")
    else:
        print("[NOTE] AI upscaling is OFF. Install Real-ESRGAN and set video_settings.ai_upscale_enabled=true to synthesize plausible detail; FFmpeg scaling alone cannot recover lost source detail.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError, RuntimeError) as exc:
        progress_event("fatal_error", "error", str(exc))
        print(f"[ERROR] {exc}")
        print("Check FFmpeg/FFprobe availability, AI-upscaler/model paths, input files, and available storage.")
        sys.exit(1)
