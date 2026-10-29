import json
import hashlib
import math
import os
import re
import shutil
import signal
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
PREVIEW_MODE = False
RUN_DIR = None
MIN_CLIPS = None
MAX_CLIPS = None
MIN_SHOT_SECONDS = 0.75
MIN_SOURCE_GAP_SECONDS = 0.05
SOURCE_CHAPTER_SECONDS = 90.0
SUBJECT_LOCK_ENABLED = True
ENDING_SKULL_ENABLED = False
ENDING_SKULL_SIZE_PX = 420
ENDING_SKULL_POSITION_X = 0.5
ENDING_SKULL_POSITION_Y = 0.5
ENDING_SKULL_POP_SECONDS = 0.18
ENDING_IMPACT_SFX_ENABLED = True
MUSIC_LOOP = None
CODEC = None
CONFIG = None
DROP_FREEZE_DURATION = 0.25
DROP_BEAT_TIME = None
DROP_BEAT_STRENGTH = None
BEAT_GRID_ANALYSIS = {
    "method": "not_run",
    "confidence": None,
    "period_seconds": None,
    "phase_seconds": None,
    "candidate_count": 0,
    "onset_candidate_count": 0,
}
SUBJECT_OBSERVATIONS = []
AI_UPSCALE_ENABLED = False
AI_UPSCALE_MODEL = "realesrgan-x4plus"
AI_UPSCALE_SCALE = 2
AI_UPSCALE_BINARY = "tools/realesrgan/realesrgan-ncnn-vulkan"
AI_UPSCALE_MODEL_DIR = "tools/realesrgan/models"
AI_UPSCALE_BATCH_TIMEOUT_SECONDS = 600
SOURCE_FPS = None
INTERMEDIATE_CRF = 10
ANALYSIS_CACHE_REPORT = []
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


def _settings_path():
    """Resolve the settings JSON path, with an explicit local-render override."""
    return os.environ.get("HEYAA_PARAMS_PATH") or "params.json"


def load_settings():
    """Load and strictly validate params.json; unsupported values fail fast."""
    global DURATION, FPS, WIDTH, HEIGHT, CRF, PRESET, SPEED, FREEZE, EDIT_DURATION
    global BEAT_SYNC, BEAT_FLASH, BASS_BOOST, REFERENCE_PACING, MIRROR_ENABLED, LAYOUT_MODE
    global MIN_CLIPS, MAX_CLIPS, MIN_SHOT_SECONDS, MUSIC_LOOP, CODEC, CONFIG, DROP_FREEZE_DURATION, MIN_SOURCE_GAP_SECONDS
    global SOURCE_CHAPTER_SECONDS, SUBJECT_LOCK_ENABLED
    global ENDING_SKULL_ENABLED, ENDING_SKULL_SIZE_PX, ENDING_SKULL_POSITION_X, ENDING_SKULL_POSITION_Y
    global ENDING_SKULL_POP_SECONDS, ENDING_IMPACT_SFX_ENABLED, PREVIEW_MODE
    global AI_UPSCALE_ENABLED, AI_UPSCALE_MODEL, AI_UPSCALE_SCALE
    global AI_UPSCALE_BINARY, AI_UPSCALE_MODEL_DIR, AI_UPSCALE_BATCH_TIMEOUT_SECONDS, INTERMEDIATE_CRF
    path = _settings_path()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Settings file {path!r} is required; renderer defaults are disabled.")
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    if PREVIEW_MODE:
        config["video_settings"]["resolution"] = "540x960"
        config["video_settings"]["fps"] = 30
        config["video_settings"]["ai_upscale_enabled"] = False
        config["video_settings"]["crf"] = 26
        config["video_settings"]["preset"] = "ultrafast"
        config["_preview_mode"] = True
    video, audio, edit = config["video_settings"], config["audio_settings"], config["edit_settings"]
    if config.get("style") != "phonk_montagem":
        raise ValueError("Only style='phonk_montagem' is implemented by this renderer.")
    resolution = str(video["resolution"]).lower().split("x")
    if len(resolution) != 2:
        raise ValueError("video_settings.resolution must be WIDTHxHEIGHT")
    WIDTH, HEIGHT = int(resolution[0]), int(resolution[1])
    if (WIDTH, HEIGHT) != (1080, 1920) and not (PREVIEW_MODE and (WIDTH, HEIGHT) == (540, 960)):
        raise ValueError("Output must be 1080x1920, or 540x960 when --preview is used.")
    FPS = video["fps"]
    if isinstance(FPS, bool) or not isinstance(FPS, int) or not 24 <= FPS <= 60:
        raise ValueError("video_settings.fps must be an integer from 24 to 60.")
    CRF = video["crf"]
    if isinstance(CRF, bool) or not isinstance(CRF, int) or not 16 <= CRF <= 26:
        raise ValueError("video_settings.crf must be an integer from 16 to 26.")
    INTERMEDIATE_CRF = video.get("intermediate_crf", 10)
    if isinstance(INTERMEDIATE_CRF, bool) or not isinstance(INTERMEDIATE_CRF, int) or not 0 <= INTERMEDIATE_CRF <= 18:
        raise ValueError("video_settings.intermediate_crf must be an integer from 0 to 18.")
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
    timeout_value = video.get("ai_upscale_batch_timeout_seconds", 600)
    if isinstance(timeout_value, bool) or not isinstance(timeout_value, int) or not 30 <= timeout_value <= 1800:
        raise ValueError("video_settings.ai_upscale_batch_timeout_seconds must be an integer from 30 to 1800.")
    AI_UPSCALE_BATCH_TIMEOUT_SECONDS = timeout_value
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
    if abs(FREEZE - 2.0) > 1e-9 or FREEZE >= DURATION:
        raise ValueError("edit_settings.freeze_duration must be exactly 2.0 seconds and shorter than the edit.")
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
    min_shot_value = edit.get("min_shot_seconds", 0.75)
    if (isinstance(min_shot_value, bool) or
            not isinstance(min_shot_value, (int, float)) or
            not math.isfinite(float(min_shot_value)) or
            not 0.3 <= float(min_shot_value) <= 3.0):
        raise ValueError("edit_settings.min_shot_seconds must be between 0.3 and 3.0 seconds.")
    MIN_SHOT_SECONDS = float(min_shot_value)
    MIN_CLIPS, MAX_CLIPS = minimum_value, maximum_value
    if not 6 <= MIN_CLIPS <= 12 or not MIN_CLIPS <= MAX_CLIPS <= 40:
        raise ValueError("Clip bounds must satisfy 6 <= min_clips <= 12 and min_clips <= max_clips <= 40.")
    source_gap_value = edit.get("source_min_gap_seconds", 0.05)
    if (isinstance(source_gap_value, bool) or not isinstance(source_gap_value, (int, float)) or
            not math.isfinite(float(source_gap_value)) or not 0.0 <= float(source_gap_value) <= 1.0):
        raise ValueError("edit_settings.source_min_gap_seconds must be between 0 and 1 second.")
    MIN_SOURCE_GAP_SECONDS = float(source_gap_value)
    chapter_seconds = edit.get("source_chapter_seconds", 90)
    if (isinstance(chapter_seconds, bool) or not isinstance(chapter_seconds, (int, float)) or
            not math.isfinite(float(chapter_seconds)) or not 60.0 <= float(chapter_seconds) <= 120.0):
        raise ValueError("edit_settings.source_chapter_seconds must be between 60 and 120 seconds.")
    SOURCE_CHAPTER_SECONDS = float(chapter_seconds)
    subject_lock_enabled = edit.get("subject_lock_enabled", True)
    if not isinstance(subject_lock_enabled, bool):
        raise ValueError("edit_settings.subject_lock_enabled must be an explicit boolean.")
    SUBJECT_LOCK_ENABLED = subject_lock_enabled
    skull_enabled = edit.get("ending_skull_enabled", False)
    if not isinstance(skull_enabled, bool):
        raise ValueError("edit_settings.ending_skull_enabled must be an explicit boolean.")
    ENDING_SKULL_ENABLED = skull_enabled
    skull_size = edit.get("skull_size_px", 420)
    if isinstance(skull_size, bool) or not isinstance(skull_size, int) or not 160 <= skull_size <= 960:
        raise ValueError("edit_settings.skull_size_px must be an integer from 160 to 960.")
    skull_x, skull_y = edit.get("skull_position_x", 0.5), edit.get("skull_position_y", 0.5)
    for key, value in (("skull_position_x", skull_x), ("skull_position_y", skull_y)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"edit_settings.{key} must be between 0 and 1.")
    skull_pop = edit.get("skull_pop_seconds", 0.18)
    if isinstance(skull_pop, bool) or not isinstance(skull_pop, (int, float)) or not math.isfinite(float(skull_pop)) or not 0.08 <= float(skull_pop) <= 0.6:
        raise ValueError("edit_settings.skull_pop_seconds must be between 0.08 and 0.6 seconds.")
    sfx_enabled = edit.get("impact_sfx_enabled", True)
    if not isinstance(sfx_enabled, bool):
        raise ValueError("edit_settings.impact_sfx_enabled must be an explicit boolean.")
    ENDING_SKULL_SIZE_PX = skull_size
    ENDING_SKULL_POSITION_X = float(skull_x)
    ENDING_SKULL_POSITION_Y = float(skull_y)
    ENDING_SKULL_POP_SECONDS = float(skull_pop)
    ENDING_IMPACT_SFX_ENABLED = sfx_enabled
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
    print(f"[settings] {WIDTH}x{HEIGHT}@{FPS} | {DURATION:.3f}s | speed={SPEED:.2f}x | min_shot={MIN_SHOT_SECONDS:.2f}s | final_freeze={FREEZE:.3f}s (minimum 1.7s) | drop_freeze={DROP_FREEZE_DURATION:.3f}s | mirror={MIRROR_ENABLED} | layout_mode={LAYOUT_MODE} | ai_upscale={AI_UPSCALE_ENABLED} ({AI_UPSCALE_MODEL} x{AI_UPSCALE_SCALE}) | music_loop={MUSIC_LOOP} | source_min_gap={MIN_SOURCE_GAP_SECONDS:.3f}s | EDL=on")
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


def build_ai_frame_extract_command(video, source_start_seconds, source_duration_seconds,
                                   source_frame_count, source_fps, output_pattern,
                                   pre_upscale_crop_filter=None):
    """Build lossless source-rate extraction; crop to 9:16 before restoration when requested."""
    rate = float(source_fps)
    if not math.isfinite(rate) or rate <= 0 or source_frame_count < 1:
        raise ValueError("Source frame rate and frame count must be positive.")
    filters = []
    if pre_upscale_crop_filter:
        filters.append(pre_upscale_crop_filter)
    filters.append(f"fps={rate:.6f}")
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{source_start_seconds:.6f}",
        "-t", f"{source_duration_seconds + 1.0 / rate:.6f}",
        "-i", str(video), "-vf", ",".join(filters),
        "-frames:v", str(source_frame_count),
        "-start_number", "1", str(output_pattern),
    ]


def get_source_frame_rate(video_path, fallback_fps=30):
    """Read the source video's nominal frame rate, with a validated fallback."""
    info = probe(video_path)
    for stream in info.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        for key in ("avg_frame_rate", "r_frame_rate"):
            try:
                rate = float(Fraction(str(stream.get(key))))
            except (ValueError, ZeroDivisionError, TypeError):
                continue
            if math.isfinite(rate) and 1.0 <= rate <= 240.0:
                return rate
    return float(fallback_fps)


def build_pre_upscale_crop_filter(dynamic_crop=None, center_x=0.5, center_y=0.5):
    """Generate a bounded source-resolution crop with the target 9:16 aspect ratio."""
    if dynamic_crop and isinstance(dynamic_crop, dict) and dynamic_crop.get("points"):
        x_path = _piecewise_linear_expression(dynamic_crop["points"], "x")
        y_path = _piecewise_linear_expression(dynamic_crop["points"], "y")
    else:
        x_path = f"{float(center_x):.6f}"
        y_path = f"{float(center_y):.6f}"
    return (
        "crop=w='if(gte(iw/ih,0.5625),ih*0.5625,iw)':"
        "h='if(gte(iw/ih,0.5625),ih,iw/0.5625)':"
        f"x='max(0,min(iw-ow,({x_path})*iw-ow/2))':"
        f"y='max(0,min(ih-oh,({y_path})*ih-oh/2))'"
    )


def prepare_ai_upscaled_frames(clip_index, source_start_seconds, source_duration_seconds,
                               source_frame_count, source_fps=None,
                               pre_upscale_crop_filter=None):
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

    rate = float(source_fps or SOURCE_FPS or FPS or 30.0)
    progress_event(
        "upscale_extract", "running",
        f"Extracting {source_frame_count} lossless source-rate frames for clip {clip_index + 1}.",
        {"clip_index": clip_index, "frame_count": source_frame_count, "source_fps": rate,
         "pre_upscale_crop": bool(pre_upscale_crop_filter)},
    )
    extract = build_ai_frame_extract_command(
        VIDEO, source_start_seconds, source_duration_seconds,
        source_frame_count, rate, input_pattern, pre_upscale_crop_filter,
    )
    result = subprocess.run(extract, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        progress_event("upscale_extract", "error", f"Frame extraction failed for clip {clip_index + 1}.",
                       {"clip_index": clip_index, "returncode": result.returncode})
        raise RuntimeError(f"Could not extract frames for AI upscaling: {result.stderr[-2000:]}")
    expected_names = [f"frame_{frame:08d}.png" for frame in range(1, source_frame_count + 1)]
    missing_input = [name for name in expected_names if not (input_dir / name).is_file()]
    if missing_input:
        progress_event("upscale_extract", "error", f"Frame extraction was incomplete for clip {clip_index + 1}.",
                       {"clip_index": clip_index, "expected_frames": source_frame_count,
                        "available_frames": source_frame_count - len(missing_input)})
        raise RuntimeError(
            f"AI upscale extraction produced {source_frame_count - len(missing_input)}/{source_frame_count} frames; "
            f"first missing: {missing_input[0]}"
        )
    progress_event("upscale_extract", "completed",
                   f"Extracted all {source_frame_count} lossless frames for clip {clip_index + 1}.",
                   {"clip_index": clip_index, "frame_count": source_frame_count})

    upscale = build_ai_upscale_command(
        AI_UPSCALER_EXECUTABLE, input_dir, output_dir,
        AI_UPSCALE_MODEL, AI_UPSCALE_SCALE, AI_UPSCALER_MODEL_DIR,
    )
    progress_event(
        "upscale_batch", "running",
        f"Real-ESRGAN is processing {source_frame_count} frames for clip {clip_index + 1}; this batch can take time.",
        {"clip_index": clip_index, "frame_count": source_frame_count,
         "model": AI_UPSCALE_MODEL, "scale": AI_UPSCALE_SCALE},
    )
    try:
        result = subprocess.run(upscale, check=False, capture_output=True, text=True,
                                timeout=AI_UPSCALE_BATCH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        timeout_seconds = AI_UPSCALE_BATCH_TIMEOUT_SECONDS
        progress_event("upscale_batch", "error",
                       f"Real-ESRGAN timed out for clip {clip_index + 1} after {timeout_seconds} seconds.",
                       {"clip_index": clip_index, "timeout_seconds": timeout_seconds})
        raise RuntimeError(
            f"Real-ESRGAN timed out after {timeout_seconds} seconds for clip {clip_index + 1}; "
            "check Vulkan/GPU availability, model files, and system load."
        ) from exc
    if result.returncode != 0:
        progress_event("upscale_batch", "error", f"Real-ESRGAN failed for clip {clip_index + 1}.",
                       {"clip_index": clip_index, "returncode": result.returncode})
        raise RuntimeError(f"Real-ESRGAN failed for clip {clip_index}: {result.stderr[-2000:]}")
    missing_output = [
        name for name in expected_names
        if not (output_dir / name).is_file() or (output_dir / name).stat().st_size <= 0
    ]
    if missing_output:
        progress_event("upscale_batch", "error", f"Real-ESRGAN returned incomplete output for clip {clip_index + 1}.",
                       {"clip_index": clip_index, "expected_frames": source_frame_count,
                        "usable_frames": source_frame_count - len(missing_output)})
        raise RuntimeError(
            f"Real-ESRGAN returned only {source_frame_count - len(missing_output)}/{source_frame_count} usable frames; "
            f"first missing: {missing_output[0]}"
        )
    progress_event("upscale_batch", "completed",
                   f"Real-ESRGAN completed all {source_frame_count} frames for clip {clip_index + 1}.",
                   {"clip_index": clip_index, "frame_count": source_frame_count,
                    "model": AI_UPSCALE_MODEL, "scale": AI_UPSCALE_SCALE})
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


def _analysis_file_sha256(path):
    """Hash the actual current file contents; do not trust mtime as content identity."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def cached_analysis(cache_kind, input_paths, parameters, compute, cache_dir="output/cache"):
    """Cache JSON analysis by full input content hashes and all relevant parameters."""
    paths = [Path(path) for path in input_paths]
    if any(not path.is_file() for path in paths):
        value = compute()
        ANALYSIS_CACHE_REPORT.append({"kind": cache_kind, "hit": False, "cacheable": False})
        return value, False
    fingerprints = [_analysis_file_sha256(path) for path in paths]
    identity = {"kind": str(cache_kind), "input_sha256": fingerprints, "parameters": parameters}
    identity_text = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    key = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()
    cache_path = Path(cache_dir) / f"{cache_kind}-{key}.json"
    try:
        saved = json.loads(cache_path.read_text(encoding="utf-8"))
        if saved.get("version") == 1 and saved.get("key") == key:
            ANALYSIS_CACHE_REPORT.append({
                "kind": cache_kind, "hit": True, "cacheable": True,
                "cache_key": key, "cache_file": str(cache_path),
            })
            return saved.get("value"), True
    except (OSError, ValueError, AttributeError):
        pass
    value = compute()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_name(cache_path.name + ".part")
    temporary.write_text(
        json.dumps({"version": 1, "key": key, "identity": identity, "value": value},
                   ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, cache_path)
    ANALYSIS_CACHE_REPORT.append({
        "kind": cache_kind, "hit": False, "cacheable": True,
        "cache_key": key, "cache_file": str(cache_path),
    })
    return value, False


def scene_detection_filter(threshold=0.22, width=320):
    """Scale down before FFmpeg calculates scene-change scores."""
    return f"scale={int(width)}:-2:flags=fast_bilinear,select='gt(scene,{float(threshold):.2f})',showinfo"


def detect_scenes(path, duration, scan_duration=None):
    """Use FFmpeg scene-change scores as an inexpensive cut detector."""
    print(f"[analyze] Scene changes: {Path(path).name}")
    cmd = ["ffmpeg", "-hide_banner"]
    if scan_duration is not None:
        cmd += ["-t", f"{max(0.1, float(scan_duration)):.3f}"]
    cmd += ["-i", path,
        "-vf", scene_detection_filter(0.22, 320),
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


def _build_beat_grid(envelope, period_frames, hop_seconds=0.02, limit=None):
    """Build a periodic grid from the strongest envelope phase for an estimated period.

    Returns None when the period/envelope is not usable. Confidence measures how
    concentrated positive onset energy is in the selected phase modulo the period;
    it is a timing-consistency proxy, not a guarantee of musical downbeats.
    """
    if (isinstance(period_frames, bool) or not isinstance(period_frames, int)
            or period_frames < 1 or len(envelope) < period_frames * 3
            or isinstance(hop_seconds, bool) or not isinstance(hop_seconds, (int, float))
            or not math.isfinite(float(hop_seconds)) or hop_seconds <= 0):
        return None
    values = [
        max(0.0, float(value)) if isinstance(value, (int, float))
        and not isinstance(value, bool) and math.isfinite(float(value)) else 0.0
        for value in envelope
    ]
    phase_scores = [
        sum(values[phase::period_frames]) for phase in range(period_frames)
    ]
    total_energy = sum(phase_scores)
    if total_energy <= 1e-12:
        return None
    phase = max(range(period_frames), key=lambda item: phase_scores[item])
    concentration = phase_scores[phase] / total_energy
    uniform_concentration = 1.0 / period_frames
    confidence = max(0.0, min(
        1.0,
        (concentration - uniform_concentration) / (1.0 - uniform_concentration),
    ))
    envelope_duration = len(values) * float(hop_seconds)
    effective_limit = envelope_duration if limit is None else min(envelope_duration, float(limit))
    if not math.isfinite(effective_limit) or effective_limit <= 0:
        return None
    period_seconds = period_frames * float(hop_seconds)
    beats = [
        round(frame * float(hop_seconds), 6)
        for frame in range(phase, len(values), period_frames)
        if 0.08 <= frame * float(hop_seconds) < effective_limit
    ]
    return {
        "beats": beats,
        "period_frames": period_frames,
        "period_seconds": period_seconds,
        "phase_frames": phase,
        "phase_seconds": phase * float(hop_seconds),
        "confidence": confidence,
    }


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

    # Preserve the onset-only path as a fallback when the estimated period or
    # phase concentration is too weak to justify a periodic grid.
    chosen = []
    for value, timestamp in sorted(candidates, reverse=True):
        if all(abs(timestamp - existing) >= min_spacing for existing in chosen):
            chosen.append(timestamp)
    onset_beats = sorted(t for t in chosen if t < limit)
    grid = _build_beat_grid(novelty, period_frames, hop_seconds=0.02, limit=limit) if period_frames else None
    use_grid = bool(
        grid and len(grid["beats"]) >= 3 and grid["confidence"] >= 0.15
    )
    if use_grid:
        beats = grid["beats"]
        BEAT_GRID_ANALYSIS.update({
            "method": "period_phase_grid",
            "confidence": round(grid["confidence"], 4),
            "period_seconds": round(grid["period_seconds"], 6),
            "phase_seconds": round(grid["phase_seconds"], 6),
            "candidate_count": len(beats),
            "onset_candidate_count": len(onset_beats),
        })
        print(
            f"[analyze] Beat grid: period={grid['period_seconds']:.3f}s, "
            f"phase={grid['phase_seconds']:.3f}s, confidence={grid['confidence']:.2f}."
        )
    else:
        beats = onset_beats
        BEAT_GRID_ANALYSIS.update({
            "method": "onset_peak_fallback" if period_frames else "onset_only_fallback",
            "confidence": round(grid["confidence"], 4) if grid else None,
            "period_seconds": round(grid["period_seconds"], 6) if grid else None,
            "phase_seconds": round(grid["phase_seconds"], 6) if grid else None,
            "candidate_count": len(beats),
            "onset_candidate_count": len(onset_beats),
        })
    if len(onset_beats) >= 3 and candidates:
        strongest_value, strongest_time = max(candidates, key=lambda pair: pair[0])
        DROP_BEAT_TIME = float(strongest_time)
        spread = max(1e-12, peak_novelty - median_novelty)
        DROP_BEAT_STRENGTH = max(0.0, min(1.0, (strongest_value - median_novelty) / spread))
        print(
            f"[analyze] Strongest bass-onset proxy at {DROP_BEAT_TIME:.2f}s "
            f"(relative onset strength={DROP_BEAT_STRENGTH:.2f}; not a semantic drop detector)."
        )
    if len(beats) < 3:
        BEAT_GRID_ANALYSIS["method"] = "even_pacing_fallback"
        print("[warn] Few clear bass onsets / grid points found; edit timing will use even pacing.")
        return []
    print(f"[analyze] Prepared {len(beats)} beat-grid/onset timing candidates in the edit window.")
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

def _has_usable_reference_profile(profile):
    """Return whether measured reference timing is available for the current render."""
    return bool(
        isinstance(profile, dict)
        and profile.get("median_cut_interval_seconds") is not None
        and profile.get("shot_intervals_seconds")
    )


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
    # Floor instead of round: rounding up can violate the configured minimum shot duration.
    cadence_target = max(MIN_SHOT_SECONDS, min(2.4, reference_interval))
    cadence_count = math.floor(EDIT_DURATION / cadence_target + 1e-9)
    return max(MIN_CLIPS, min(MAX_CLIPS, cadence_count))


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
            if 0.7 <= value <= limit - DROP_FREEZE_DURATION - MIN_SHOT_SECONDS:
                candidates.append(value)
    elif 0.7 <= DROP_BEAT_TIME <= limit - DROP_FREEZE_DURATION - MIN_SHOT_SECONDS:
        candidates.append(DROP_BEAT_TIME)
    if not candidates:
        return None
    target = limit * 0.38
    return min(candidates, key=lambda value: abs(value - target))


def insert_drop_boundary(boundaries, desired_time, min_gap=0.75, max_gap=3.3):
    """Snap a drop-impact hold to a cut without violating either adjacent shot-length bound."""
    if desired_time is None or len(boundaries) < 3:
        return boundaries, None
    if (not math.isfinite(float(min_gap)) or not math.isfinite(float(max_gap))
            or min_gap < 0 or max_gap < min_gap):
        raise ValueError("Drop-boundary shot-length bounds must satisfy 0 <= min_gap <= max_gap.")
    limit = boundaries[-1]
    if not 0.7 <= desired_time <= limit - 0.7:
        return boundaries, None
    candidates = sorted(range(1, len(boundaries) - 1),
                        key=lambda index: abs(boundaries[index] - desired_time))
    for index in candidates:
        previous_gap = desired_time - boundaries[index - 1]
        next_gap = boundaries[index + 1] - desired_time
        if min_gap <= previous_gap <= max_gap and min_gap <= next_gap <= max_gap:
            updated = list(boundaries)
            updated[index] = desired_time
            updated.sort()
            return updated, desired_time
    # If the exact beat would create a too-short or too-long adjacent shot, keep
    # the validated pacing and place the freeze on the nearest existing cut.
    nearest = min(boundaries[1:-1], key=lambda value: abs(value - desired_time))
    return list(boundaries), nearest


def choose_context_window(source_duration, scene_cuts, target_duration):
    """Choose a bounded framing/tracking context; this is not the source-search limit."""

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
    print("[context] Window scoring is only a temporal-continuity proxy; semantic action/identity understanding is not implied.")
    return {"start_seconds": round(best_start, 3), "end_seconds": round(end, 3),
            "scene_cuts": best_count, "window_seconds": round(end - best_start, 3),
            "target_cut_count": target_cut_count, "method": "moderate-scene-cut-density-window",
            "same_person_tracking": False}


def choose_source_selection_scope(source_duration, target_duration, context_start, context_end):
    """Use the full recording for long sources; retain the selected context for short sources.

    The full-source threshold avoids changing established behavior for short clips while
    letting a 12-minute input contribute candidate moments throughout its timeline.
    Selection is still a loudness/motion proxy, not semantic action recognition.
    """
    values = (source_duration, target_duration, context_start, context_end)
    if any(not isinstance(value, (int, float)) or isinstance(value, bool)
           or not math.isfinite(float(value)) for value in values):
        raise ValueError("Source-selection scope values must be finite numbers.")
    source_length, target_length = float(source_duration), float(target_duration)
    context_start, context_end = float(context_start), float(context_end)
    if source_length <= 0 or target_length <= 0 or context_start < 0 or context_end <= context_start:
        raise ValueError("Source-selection scope boundaries are invalid.")
    threshold = max(60.0, target_length * 3.0)
    if source_length >= threshold:
        return {
            "start_seconds": 0.0,
            "end_seconds": source_length,
            "method": "full_source_long_video",
            "threshold_seconds": round(threshold, 3),
        }
    return {
        "start_seconds": context_start,
        "end_seconds": min(source_length, context_end),
        "method": "context_window_short_video",
        "threshold_seconds": round(threshold, 3),
    }


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
                    all(MIN_SHOT_SECONDS <= length <= 3.3 for length in shot_lengths) and
                    all(b > a for a, b in zip(exactish, exactish[1:]))):
                REFERENCE_CUT_TIMESTAMPS_USED = True
                print("[edit] Using the reference's measured cut timestamps, scaled to the requested edit duration.")
                return exactish
    valid = [float(value) for value in intervals
             if isinstance(value, (int, float)) and not isinstance(value, bool)
             and math.isfinite(float(value)) and float(value) > 0]
    if len(valid) < 2:
        return [total_duration * index / clip_count for index in range(clip_count + 1)]
    minimum, maximum = MIN_SHOT_SECONDS, 3.3
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


def _reference_pacing_diagnostics(reference_profile, planned_lengths):
    """Compare the measured reference cadence with the intervals this render can actually fit."""
    if not isinstance(reference_profile, dict) or not planned_lengths:
        return None
    reference_median = reference_profile.get("median_cut_interval_seconds")
    if (isinstance(reference_median, bool) or not isinstance(reference_median, (int, float))
            or not math.isfinite(float(reference_median)) or reference_median <= 0):
        return None
    if any(not math.isfinite(float(length)) or float(length) <= 0 for length in planned_lengths):
        return None
    planned_median = float(statistics.median(planned_lengths))
    ratio = planned_median / float(reference_median)
    return {
        "reference_median_seconds": round(float(reference_median), 4),
        "planned_median_seconds": round(planned_median, 4),
        "cadence_stretch_ratio": round(ratio, 4),
        "planned_clip_count": len(planned_lengths),
    }


def make_boundaries(clip_count, beats, reference_profile=None):
    """Keep reference-derived shot lengths and accept only beat snaps that stay render-safe."""
    reference_boundaries = _reference_boundaries(clip_count, EDIT_DURATION, reference_profile)
    boundaries = list(reference_boundaries)
    if beats:
        for index in range(1, clip_count):
            target = boundaries[index]
            if BEAT_GRID_ANALYSIS.get("method") == "period_phase_grid":
                grid_period = BEAT_GRID_ANALYSIS.get("period_seconds")
                snap_window = min(0.42, max(0.16, float(grid_period or 0.0) / 2.0))
            else:
                snap_window = 0.16 if reference_profile and reference_profile.get("cut_timestamps_seconds") else 0.42
            nearby = [beat for beat in beats if abs(beat - target) <= snap_window]
            if not nearby:
                continue
            candidate = min(nearby, key=lambda beat: abs(beat - target))
            previous, following = boundaries[index - 1], boundaries[index + 1]
            previous_gap, next_gap = candidate - previous, following - candidate
            if MIN_SHOT_SECONDS <= previous_gap <= 3.3 and MIN_SHOT_SECONDS <= next_gap <= 3.3:
                boundaries[index] = candidate
    lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
    if min(lengths) < MIN_SHOT_SECONDS - 1e-8 or max(lengths) > 3.3 + 1e-8:
        print("[warn] Beat snapping would break safe shot lengths; reverting to reference-derived boundaries.")
        boundaries = list(reference_boundaries)
        lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
    if min(lengths) < MIN_SHOT_SECONDS - 1e-8 or max(lengths) > 3.3 + 1e-8:
        print("[warn] Reference-derived boundaries are outside the safe range; using even pacing.")
        boundaries = [EDIT_DURATION * index / clip_count for index in range(clip_count + 1)]
        lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
    if reference_profile:
        variation = max(lengths) - min(lengths)
        print("[edit] Reference-derived shot lengths: " + ", ".join(f"{x:.2f}" for x in lengths) + " seconds")
        diagnostics = _reference_pacing_diagnostics(reference_profile, lengths)
        if diagnostics:
            print(
                f"[edit] Reference cadence: source median={diagnostics['reference_median_seconds']:.2f}s; "
                f"planned median={diagnostics['planned_median_seconds']:.2f}s "
                f"({diagnostics['cadence_stretch_ratio']:.2f}x slower); "
                f"{diagnostics['planned_clip_count']} motion clips."
            )
            if diagnostics["cadence_stretch_ratio"] >= 1.75:
                message = (
                    "The requested motion-clip count forces slower cuts than the reference: "
                    f"reference median {diagnostics['reference_median_seconds']:.2f}s, "
                    f"planned median {diagnostics['planned_median_seconds']:.2f}s "
                    f"({diagnostics['cadence_stretch_ratio']:.2f}x slower). "
                    "Increase the clip count within configured limits to get closer to the reference cadence."
                )
                print("[warn] " + message, flush=True)
                progress_event("reference_pacing_fit", "needs_review", message, diagnostics)
        print(f"[edit] Planned range={min(lengths):.2f}–{max(lengths):.2f}s; variation={variation:.2f}s.")
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


def _source_has_audio(path):
    """Return whether ffprobe can identify a source audio stream."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def build_source_scene_segments(start_seconds, end_seconds, scene_cuts, max_segment_seconds=None):
    """Split scene intervals into chronological candidates, optionally bounding their duration."""
    start, end = float(start_seconds), float(end_seconds)
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError("Source context must have finite non-negative start and end > start.")
    if max_segment_seconds is not None:
        if (isinstance(max_segment_seconds, bool) or
                not isinstance(max_segment_seconds, (int, float)) or
                not math.isfinite(float(max_segment_seconds)) or float(max_segment_seconds) < 0.25):
            raise ValueError("max_segment_seconds must be None or a finite number >= 0.25.")
        max_segment_seconds = float(max_segment_seconds)
    cuts = sorted({
        float(value) for value in scene_cuts
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(float(value)) and start + 1e-6 < float(value) < end - 1e-6
    })
    positions = [start] + cuts + [end]
    segments = []
    for scene_start, scene_end in zip(positions, positions[1:]):
        scene_duration = scene_end - scene_start
        if scene_duration < 0.25:
            continue
        piece_count = (max(1, math.ceil(scene_duration / max_segment_seconds))
                       if max_segment_seconds is not None else 1)
        for piece in range(piece_count):
            left = scene_start + scene_duration * piece / piece_count
            right = scene_start + scene_duration * (piece + 1) / piece_count
            if right - left >= 0.25:
                segments.append({
                    "start_seconds": left, "end_seconds": right,
                    "audio_loudness_db": None, "motion_score": None,
                })
    return segments


def measure_source_scene_features(path, scene_segments):
    """Measure per-scene RMS loudness (astats) and low-resolution frame-difference motion."""
    measured = []
    for index, segment in enumerate(scene_segments):
        start = float(segment["start_seconds"])
        duration = float(segment["end_seconds"]) - start
        if duration <= 0:
            continue
        command = [
            "ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info",
            "-ss", f"{start:.6f}", "-t", f"{duration:.6f}", "-i", path,
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "fps=4,scale=160:-2:flags=fast_bilinear,tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
            "-af", "astats=metadata=1:reset=0",
            "-f", "null", "-",
        ]
        try:
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False,
            )
        except OSError as exc:
            raise RuntimeError(f"Could not measure source scene segment {index}: {exc}") from exc
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg scene-feature analysis failed for segment {index}: {output[-800:]}"
            )
        loudness = re.findall(
            r"RMS level dB:\s*(-?inf|-?(?:\d+(?:\.\d*)?|\.\d+))",
            output, re.IGNORECASE,
        )
        motion = re.findall(
            r"lavfi\.signalstats\.YAVG\s*=\s*([0-9]+(?:\.[0-9]+)?)",
            output,
        )
        if not loudness:
            raise RuntimeError(f"FFmpeg astats returned no RMS loudness for source scene segment {index}.")
        raw_rms = loudness[-1].lower()
        try:
            rms_db = float(raw_rms)
            if not math.isfinite(rms_db):
                rms_db = -120.0
        except ValueError:
            rms_db = -120.0
        motion_values = [float(value) for value in motion if math.isfinite(float(value))]
        measured.append({
            **segment,
            "audio_loudness_db": max(-120.0, min(0.0, rms_db)),
            "motion_score": statistics.fmean(motion_values) if motion_values else 0.0,
        })
    if not measured or not any(
        isinstance(item.get("audio_loudness_db"), (int, float))
        and math.isfinite(float(item["audio_loudness_db"]))
        for item in measured
    ):
        raise RuntimeError("No usable scene-level audio loudness measurements were produced.")
    return measured


def _percentile_ranks(values):
    """Normalize numeric values to [0, 1], assigning tied values their mid-rank."""
    count = len(values)
    if count <= 1:
        return [0.5] * count
    result = [0.0] * count
    order = sorted(range(count), key=lambda index: values[index])
    cursor = 0
    while cursor < count:
        end = cursor + 1
        while end < count and values[order[end]] == values[order[cursor]]:
            end += 1
        rank = ((cursor + end - 1) / 2.0) / (count - 1)
        for position in range(cursor, end):
            result[order[position]] = rank
        cursor = end
    return result


def rank_source_scene_segments(scene_segments):
    """Rank scene intervals by measured source loudness (60%) and motion (40%)."""
    if not scene_segments:
        return []
    prepared = [dict(segment) for segment in scene_segments]
    audio_values = []
    motion_values = []
    for segment in prepared:
        try:
            audio_value = float(segment.get("audio_loudness_db", -120.0))
        except (TypeError, ValueError):
            audio_value = -120.0
        try:
            motion_value = float(segment.get("motion_score", 0.0))
        except (TypeError, ValueError):
            motion_value = 0.0
        audio_values.append(audio_value if math.isfinite(audio_value) else -120.0)
        motion_values.append(motion_value if math.isfinite(motion_value) else 0.0)
    audio_ranks = _percentile_ranks(audio_values)
    motion_ranks = _percentile_ranks(motion_values)
    subject_values = []
    for segment in prepared:
        try:
            value = float(segment.get("subject_presence_score", 0.0))
        except (TypeError, ValueError):
            value = 0.0
        subject_values.append(max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0)
    subject_evidence_available = any(value > 0.0 for value in subject_values)
    for index, segment in enumerate(prepared):
        segment["audio_rank"] = round(audio_ranks[index], 4)
        segment["motion_rank"] = round(motion_ranks[index], 4)
        segment["subject_presence_score"] = round(subject_values[index], 4)
        if subject_evidence_available:
            score = 0.55 * subject_values[index] + 0.27 * audio_ranks[index] + 0.18 * motion_ranks[index]
            segment["selection_score_method"] = "appearance_track_soft_lock_plus_audio_motion"
        else:
            score = 0.6 * audio_ranks[index] + 0.4 * motion_ranks[index]
            segment["selection_score_method"] = "audio_motion_only"
        segment["selection_score"] = round(score, 4)
    return prepared


def choose_source_chapter(scene_segments, scope_start, scope_end, chapter_seconds=90.0,
                         subject_chapter_reports=None):
    """Choose one contiguous chapter from activity plus optional appearance-track evidence."""
    numeric = (scope_start, scope_end, chapter_seconds)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in numeric):
        raise ValueError("Source-chapter boundaries and duration must be finite numbers.")
    start, end, requested = map(float, numeric)
    if start < 0 or end <= start:
        raise ValueError("Source-chapter scope must have end > start and a non-negative start.")
    if not 60.0 <= requested <= 120.0:
        raise ValueError("chapter_seconds must be between 60 and 120 seconds.")
    if not scene_segments:
        raise RuntimeError("No measured source segments are available for chapter selection.")
    ranked = rank_source_scene_segments(scene_segments)
    span = end - start
    chapter_count = max(1, int(math.ceil(span / requested)))
    actual_length = span / chapter_count
    candidates = []
    for index in range(chapter_count):
        left = start + index * actual_length
        right = end if index == chapter_count - 1 else start + (index + 1) * actual_length
        weighted_scores, covered = [], 0.0
        for segment in ranked:
            overlap = min(right, float(segment["end_seconds"])) - max(left, float(segment["start_seconds"]))
            if overlap > 0:
                weighted_scores.append((float(segment["selection_score"]), overlap))
                covered += overlap
        if weighted_scores:
            total_weight = sum(weight for _, weight in weighted_scores)
            mean_score = sum(score * weight for score, weight in weighted_scores) / total_weight
            sorted_scores = sorted(score for score, _ in weighted_scores)
            q75 = sorted_scores[round((len(sorted_scores) - 1) * 0.75)]
            score = 0.8 * mean_score + 0.2 * q75
        else:
            mean_score = q75 = score = 0.0
        candidates.append({
            "index": index, "start_seconds": left, "end_seconds": right,
            "duration_seconds": right - left, "selection_score": score,
            "activity_selection_score": score,
            "mean_activity_score": mean_score, "upper_quartile_activity_score": q75,
            "coverage_ratio": min(1.0, covered / max(1e-9, right - left)),
            "track_scan_attempted": False, "subject_track_detected": False,
            "subject_track_score": 0.0, "subject_track_span_seconds": 0.0,
        })

    # The optional tracking pass examines only the highest-ranked activity chapters.
    # Unscanned chapters cannot win over measured track evidence.
    scan_reports = {}
    for report in subject_chapter_reports or []:
        if not isinstance(report, dict):
            continue
        index = report.get("chapter_index")
        if isinstance(index, int) and not isinstance(index, bool):
            scan_reports[index] = report
    stable_track_reports = [
        report for report in scan_reports.values()
        if report.get("detected") is True
        and isinstance(report.get("track_quality_proxy"), (int, float))
        and math.isfinite(float(report["track_quality_proxy"]))
        and float(report["track_quality_proxy"]) > 0.0
    ]
    selection_policy = "activity_only"
    if subject_chapter_reports:
        if stable_track_reports:
            selection_policy = "activity_plus_subject_track"
            for candidate in candidates:
                report = scan_reports.get(candidate["index"])
                candidate["track_scan_attempted"] = report is not None
                candidate["activity_selection_score"] = round(candidate["selection_score"], 4)
                if report is None:
                    candidate["selection_score"] = -1.0
                    continue
                detected = report.get("detected") is True
                try:
                    track_score = float(report.get("track_quality_proxy") or 0.0)
                    track_span = float(report.get("track_span_seconds") or 0.0)
                except (TypeError, ValueError):
                    track_score, track_span = 0.0, 0.0
                candidate["subject_track_detected"] = detected
                candidate["subject_track_score"] = max(0.0, min(1.0, track_score)) if math.isfinite(track_score) else 0.0
                candidate["subject_track_span_seconds"] = max(0.0, track_span) if math.isfinite(track_span) else 0.0
                candidate["selection_score"] = round(
                    0.35 * candidate["activity_selection_score"] + 0.65 * candidate["subject_track_score"], 4
                ) if detected else round(0.35 * candidate["activity_selection_score"], 4)
        else:
            selection_policy = "activity_only_no_stable_subject_track"
            for candidate in candidates:
                candidate["track_scan_attempted"] = candidate["index"] in scan_reports

    selected = max(candidates, key=lambda item: (item["selection_score"], item["coverage_ratio"], -item["index"]))
    left, right = selected["start_seconds"], selected["end_seconds"]
    selected_segments = []
    for segment in ranked:
        overlap_start = max(left, float(segment["start_seconds"]))
        overlap_end = min(right, float(segment["end_seconds"]))
        if overlap_end - overlap_start < 0.25:
            continue
        selected_segments.append({**segment, "start_seconds": overlap_start, "end_seconds": overlap_end})
    if not selected_segments:
        raise RuntimeError("The selected source chapter contains no usable measured segments.")
    activity_ranked = sorted(candidates, key=lambda item: (
        item.get("activity_selection_score", item["selection_score"]), -item["index"]
    ), reverse=True)
    candidate_summary = [{
        "index": item["index"],
        "start_seconds": round(item["start_seconds"], 3),
        "end_seconds": round(item["end_seconds"], 3),
        "duration_seconds": round(item["duration_seconds"], 3),
        "activity_selection_score": round(item.get("activity_selection_score", item["selection_score"]), 4),
        "selection_score": round(item["selection_score"], 4),
        "track_scan_attempted": item["track_scan_attempted"],
        "subject_track_detected": item["subject_track_detected"],
        "subject_track_score": round(item["subject_track_score"], 4),
        "subject_track_span_seconds": round(item["subject_track_span_seconds"], 3),
    } for item in activity_ranked]
    return {
        "applied": True, "method": "activity-ranked-contiguous-chapter",
        "start_seconds": round(left, 3), "end_seconds": round(right, 3),
        "duration_seconds": round(right - left, 3),
        "selection_score": round(selected["selection_score"], 4),
        "activity_selection_score": round(selected["activity_selection_score"], 4),
        "subject_track_score": round(selected["subject_track_score"], 4),
        "subject_track_detected": selected["subject_track_detected"],
        "subject_track_span_seconds": round(selected["subject_track_span_seconds"], 3),
        "selection_policy": selection_policy,
        "mean_activity_score": round(selected["mean_activity_score"], 4),
        "upper_quartile_activity_score": round(selected["upper_quartile_activity_score"], 4),
        "coverage_ratio": round(selected["coverage_ratio"], 4),
        "candidate_chapters": len(candidates), "selected_chapter_index": selected["index"],
        "candidate_chapters_ranked": candidate_summary,
        "subject_track_scan_count": len(scan_reports),
        "measured_segment_count": len(ranked), "selected_segment_count": len(selected_segments),
        "signals": ["source_audio_rms", "frame_difference_motion", "opencv_hog_appearance_track_proxy"]
                   if selection_policy == "activity_plus_subject_track"
                   else ["source_audio_rms", "frame_difference_motion"],
        "semantic_context_understanding": False,
    }, selected_segments


def measure_candidate_chapter_tracks(video_path, chapter_candidates, max_candidates=3):
    """Coarsely check top activity chapters for persistent person-shaped appearances."""
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or not 1 <= max_candidates <= 4:
        raise ValueError("max_candidates must be an integer from 1 to 4.")
    shortlist = list(chapter_candidates or [])[:max_candidates]
    reports = []
    if not shortlist:
        return reports
    progress_event(
        "chapter_character_scan", "running",
        f"Checking {len(shortlist)} high-activity chapters for persistent appearance tracks.",
        {"candidate_count": len(shortlist), "sample_interval_seconds": 2.0, "max_frame_side": 360},
    )
    for ordinal, candidate in enumerate(shortlist, start=1):
        try:
            track = detect_person_track(
                video_path, float(candidate["start_seconds"]), float(candidate["end_seconds"]),
                sample_interval_seconds=2.0, max_frame_side=360,
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            track = {
                "detected": False, "method": "chapter-track-scan-failed",
                "reason": str(exc), "track_quality_proxy": None, "track_span_seconds": None,
                "identity_semantics": False,
            }
        quality = track.get("track_quality_proxy")
        try:
            quality = float(quality) if quality is not None else 0.0
        except (TypeError, ValueError):
            quality = 0.0
        span = track.get("track_span_seconds")
        try:
            span = float(span) if span is not None else 0.0
        except (TypeError, ValueError):
            span = 0.0
        report = {
            "chapter_index": candidate["index"],
            "start_seconds": round(float(candidate["start_seconds"]), 3),
            "end_seconds": round(float(candidate["end_seconds"]), 3),
            "detected": bool(track.get("detected")) and math.isfinite(quality) and quality > 0.0,
            "method": track.get("method", "unavailable"),
            "track_quality_proxy": max(0.0, min(1.0, quality)) if math.isfinite(quality) else 0.0,
            "track_span_seconds": max(0.0, span) if math.isfinite(span) else 0.0,
            "observation_count": len(track.get("observations", [])),
            "reason": track.get("reason"),
            "identity_semantics": False,
        }
        reports.append(report)
        progress_event(
            "chapter_character_scan", "completed" if report["detected"] else "needs_review",
            f"Chapter {ordinal}/{len(shortlist)} appearance-track scan: "
            + (f"track span {report['track_span_seconds']:.2f}s, quality proxy {report['track_quality_proxy']:.2f}."
               if report["detected"] else "no stable appearance track was measured."),
            report,
        )
    return reports


def add_subject_presence_scores(scene_segments, observations, sample_interval_seconds=0.75):
    """Attach a soft within-chapter appearance-track overlap score to each measured segment."""
    if (isinstance(sample_interval_seconds, bool) or
            not isinstance(sample_interval_seconds, (int, float)) or
            not math.isfinite(float(sample_interval_seconds)) or sample_interval_seconds <= 0):
        raise ValueError("sample_interval_seconds must be a positive finite number.")
    timestamps = []
    for item in observations or []:
        if not isinstance(item, dict):
            continue
        timestamp = item.get("time_seconds")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and math.isfinite(float(timestamp)):
            timestamps.append(float(timestamp))
    result = []
    for segment in scene_segments:
        item = dict(segment)
        start, end = float(item["start_seconds"]), float(item["end_seconds"])
        duration = end - start
        if duration <= 0:
            raise ValueError("Subject scoring received a non-positive segment.")
        count = sum(1 for timestamp in timestamps if start <= timestamp < end)
        item["subject_observation_count"] = count
        item["subject_presence_score"] = round(min(1.0, count * float(sample_interval_seconds) / duration), 4)
        result.append(item)
    return result


def plan_ranked_disjoint_source_ranges(source_durations_frames, scene_segments, fps, minimum_gap_frames):
    """Assign consecutive output clips to ranked scene intervals without overlaps or source-order jumps.

    Scene intervals remain in source-time order because the EDL validator requires
    monotonically increasing source ranges. A small dynamic program chooses how many
    consecutive output clips each scene can host, maximizing loudness/motion score
    while preferring coverage across multiple scene intervals.
    """
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(float(fps)) or fps <= 0:
        raise ValueError("fps must be a positive finite number.")
    if (isinstance(minimum_gap_frames, bool) or not isinstance(minimum_gap_frames, int)
            or minimum_gap_frames < 0):
        raise ValueError("minimum_gap_frames must be a non-negative integer.")
    durations = []
    for value in source_durations_frames:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("Each source clip duration must be a positive integer frame count.")
        durations.append(value)
    if not durations:
        return []
    ranked = rank_source_scene_segments(scene_segments)
    if not ranked:
        raise RuntimeError("No measured source scene intervals are available.")

    usable = []
    for index, segment in enumerate(ranked):
        start_seconds, end_seconds = segment.get("start_seconds"), segment.get("end_seconds")
        if (not isinstance(start_seconds, (int, float)) or
                not isinstance(end_seconds, (int, float)) or
                not math.isfinite(float(start_seconds)) or
                not math.isfinite(float(end_seconds)) or end_seconds <= start_seconds):
            raise ValueError(f"Scene segment {index} has invalid boundaries.")
        start_frame = math.ceil(float(start_seconds) * fps - 1e-8)
        end_frame = math.floor(float(end_seconds) * fps + 1e-8)
        # Leave room around interior scene cuts, and the configured source gap
        # between clips within a scene, so the EDL contract needs no correction.
        if index > 0:
            start_frame += minimum_gap_frames
        if index < len(ranked) - 1:
            end_frame -= minimum_gap_frames
        usable.append({
            **segment, "scene_segment_index": index,
            "start_frame": start_frame, "end_frame": end_frame,
            "cursor": start_frame, "uses": 0,
        })

    clip_count = len(durations)
    scene_count = len(usable)
    prefix = [0]
    for duration in durations:
        prefix.append(prefix[-1] + duration)
    max_per_scene = max(1, math.ceil(clip_count / scene_count) + 1)
    negative = float("-inf")
    dp = [[negative] * (clip_count + 1) for _ in range(scene_count + 1)]
    back = [[None] * (clip_count + 1) for _ in range(scene_count + 1)]
    dp[0][0] = 0.0
    for scene_index, segment in enumerate(usable, start=1):
        capacity = segment["end_frame"] - segment["start_frame"]
        for assigned in range(clip_count + 1):
            if dp[scene_index - 1][assigned] > dp[scene_index][assigned]:
                dp[scene_index][assigned] = dp[scene_index - 1][assigned]
                back[scene_index][assigned] = (assigned, 0)
            upper_count = min(assigned, max_per_scene)
            for count in range(1, upper_count + 1):
                previous_assigned = assigned - count
                if dp[scene_index - 1][previous_assigned] == negative:
                    continue
                required = prefix[assigned] - prefix[previous_assigned] + minimum_gap_frames * (count - 1)
                if required > capacity:
                    continue
                value = dp[scene_index - 1][previous_assigned] + count * float(segment["selection_score"]) + 0.2
                if value > dp[scene_index][assigned] + 1e-12:
                    dp[scene_index][assigned] = value
                    back[scene_index][assigned] = (previous_assigned, count)
    if dp[scene_count][clip_count] == negative:
        raise RuntimeError(
            "Ranked scene intervals cannot fit every source clip without overlap; "
            "use fewer clips, a longer source/context, or the legacy selection fallback."
        )

    allocations = [0] * scene_count
    assigned = clip_count
    for scene_index in range(scene_count, 0, -1):
        parent = back[scene_index][assigned]
        if parent is None:
            raise RuntimeError("Could not reconstruct the ranked source-segment allocation.")
        previous_assigned, count = parent
        allocations[scene_index - 1] = count
        assigned = previous_assigned
    assignments = []
    for scene, count in zip(usable, allocations):
        cursor = scene["start_frame"]
        for _ in range(count):
            clip_index = len(assignments)
            duration = durations[clip_index]
            start_frame = cursor
            if start_frame + duration > scene["end_frame"]:
                raise RuntimeError("Ranked source-segment allocation crossed a scene boundary.")
            assignments.append({
                "source_start_f": start_frame,
                "source_dur_f": duration,
                "scene_segment_index": scene["scene_segment_index"],
                "selection_score": scene["selection_score"],
                "forced_shift_frames": 0,
            })
            cursor += duration + minimum_gap_frames
    if len(assignments) != clip_count:
        raise RuntimeError("Ranked source-segment allocation did not assign every clip.")
    for previous, current in zip(
        sorted(assignments, key=lambda item: item["source_start_f"]),
        sorted(assignments, key=lambda item: item["source_start_f"])[1:],
    ):
        if current["source_start_f"] < previous["source_start_f"] + previous["source_dur_f"] + minimum_gap_frames:
            raise RuntimeError("Ranked source-segment plan violates non-overlap/source-gap constraints.")
    return assignments


def plan_subject_locked_source_ranges(source_durations_frames, scene_segments, fps,
                                      minimum_gap_frames, minimum_presence_score=0.35):
    """Constrain clip allocation to intervals with repeated track evidence when it can fit."""
    if (isinstance(minimum_presence_score, bool) or not isinstance(minimum_presence_score, (int, float)) or
            not math.isfinite(float(minimum_presence_score)) or
            not 0.0 < float(minimum_presence_score) <= 1.0):
        raise ValueError("minimum_presence_score must be between 0 and 1.")
    durations = list(source_durations_frames)
    eligible = []
    for segment in scene_segments:
        try:
            presence = float(segment.get("subject_presence_score", 0.0))
        except (AttributeError, TypeError, ValueError):
            presence = 0.0
        if math.isfinite(presence) and presence >= float(minimum_presence_score):
            eligible.append(dict(segment))
    diagnostics = {
        "applied": False,
        "minimum_presence_score": float(minimum_presence_score),
        "eligible_segment_count": len(eligible),
        "required_source_frames": sum(durations) + int(minimum_gap_frames) * max(0, len(durations) - 1),
        "identity_semantics": False,
    }
    if not eligible:
        diagnostics["reason"] = "No measured scene interval met the minimum subject-presence threshold."
        return None, diagnostics
    capacity = 0
    for segment in eligible:
        start, end = float(segment["start_seconds"]), float(segment["end_seconds"])
        capacity += max(0, math.floor(end * float(fps) + 1e-8) - math.ceil(start * float(fps) - 1e-8))
    diagnostics["eligible_capacity_frames"] = capacity
    if capacity < diagnostics["required_source_frames"]:
        diagnostics["reason"] = "Tracked-subject intervals do not contain enough footage for all clips and gaps."
        return None, diagnostics
    try:
        assignments = plan_ranked_disjoint_source_ranges(durations, eligible, fps, minimum_gap_frames)
    except RuntimeError as exc:
        diagnostics["reason"] = str(exc)
        return None, diagnostics
    diagnostics.update({
        "applied": True, "reason": None, "assigned_clip_count": len(assignments),
        "method": "subject_presence_constrained_disjoint_ranges",
    })
    return assignments, diagnostics


def _interpolate_subject_center(observations, timestamp, max_distance_seconds):
    """Interpolate a normalized tracked centroid only across a short observed gap."""
    before = [item for item in observations if item["time_seconds"] <= timestamp]
    after = [item for item in observations if item["time_seconds"] >= timestamp]
    if before and after:
        left, right = before[-1], after[0]
        left_t, right_t = left["time_seconds"], right["time_seconds"]
        if right_t - left_t <= max(1e-6, 2.0 * max_distance_seconds):
            if abs(right_t - left_t) <= 1e-8:
                return left["center_x"], left["center_y"]
            fraction = (timestamp - left_t) / (right_t - left_t)
            return (
                left["center_x"] + fraction * (right["center_x"] - left["center_x"]),
                left["center_y"] + fraction * (right["center_y"] - left["center_y"]),
            )
    nearest = min(observations, key=lambda item: abs(item["time_seconds"] - timestamp))
    if abs(nearest["time_seconds"] - timestamp) <= max_distance_seconds:
        return nearest["center_x"], nearest["center_y"]
    return None


def _piecewise_linear_expression(points, key):
    """Create an FFmpeg expression for a normalized centroid path over clip-local t."""
    if not points:
        raise ValueError("At least one crop point is required.")
    expression = f"{float(points[-1][key]):.6f}"
    for left, right in reversed(list(zip(points, points[1:]))):
        delta_t = float(right["t"]) - float(left["t"])
        if delta_t <= 1e-8:
            continue
        start_value = float(left[key])
        delta_value = float(right[key]) - start_value
        interpolation = (
            f"({start_value:.6f}+({delta_value:.6f})*"
            f"(t-{float(left['t']):.6f})/{delta_t:.6f})"
        )
        expression = f"if(lt(t,{float(right['t']):.6f}),{interpolation},{expression})"
    return expression


def build_dynamic_crop_path(observations, source_start_seconds, source_duration_seconds,
                            max_distance_seconds=1.0, smoothing_tau_seconds=0.65):
    """Return a low-pass filtered, piecewise-linear subject-centroid crop trajectory.

    x/y remain normalized in [0, 1]. The returned FFmpeg crop expressions clamp
    the actual pixel crop against iw-ow and ih-oh, so the crop cannot leave the
    scaled source bounds. Returns None when a nearby, continuous track is unavailable.
    """
    numeric = (source_start_seconds, source_duration_seconds, max_distance_seconds, smoothing_tau_seconds)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
           for value in numeric):
        return None
    start = float(source_start_seconds)
    duration = float(source_duration_seconds)
    max_distance = float(max_distance_seconds)
    tau = float(smoothing_tau_seconds)
    if start < 0 or duration <= 0 or max_distance < 0 or tau <= 0:
        return None
    valid = []
    for item in observations or []:
        try:
            timestamp = float(item["time_seconds"])
            center_x = float(item["center_x"])
            center_y = float(item["center_y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (timestamp, center_x, center_y)):
            continue
        valid.append({
            "time_seconds": timestamp,
            "center_x": max(0.0, min(1.0, center_x)),
            "center_y": max(0.0, min(1.0, center_y)),
        })
    if not valid:
        return None
    valid.sort(key=lambda item: item["time_seconds"])
    deduped = {}
    for item in valid:
        deduped[item["time_seconds"]] = item
    valid = [deduped[key] for key in sorted(deduped)]
    end = start + duration
    start_center = _interpolate_subject_center(valid, start, max_distance)
    end_center = _interpolate_subject_center(valid, end, max_distance)
    if start_center is None or end_center is None:
        return None
    raw_points = [{"t": 0.0, "x": start_center[0], "y": start_center[1]}]
    for item in valid:
        if start + 1e-8 < item["time_seconds"] < end - 1e-8:
            raw_points.append({
                "t": item["time_seconds"] - start,
                "x": item["center_x"], "y": item["center_y"],
            })
    raw_points.append({"t": duration, "x": end_center[0], "y": end_center[1]})
    raw_points.sort(key=lambda item: item["t"])
    points = [dict(raw_points[0])]
    for raw_point in raw_points[1:]:
        delta_t = float(raw_point["t"]) - float(points[-1]["t"])
        if delta_t <= 1e-8:
            continue
        alpha = 1.0 - math.exp(-delta_t / tau)
        previous = points[-1]
        points.append({
            "t": float(raw_point["t"]),
            "x": max(0.0, min(1.0, previous["x"] + alpha * (raw_point["x"] - previous["x"]))),
            "y": max(0.0, min(1.0, previous["y"] + alpha * (raw_point["y"] - previous["y"]))),
        })
    x_path = _piecewise_linear_expression(points, "x")
    y_path = _piecewise_linear_expression(points, "y")
    return {
        "points": points,
        "x_expression": f"max(0,min(iw-ow,({x_path})*iw-ow/2))",
        "y_expression": f"max(0,min(ih-oh,({y_path})*ih-oh/2))",
        "method": "piecewise_linear_low_pass",
        "smoothing_tau_seconds": tau,
    }


def build_music_loop_graph(music_duration, target_duration, loop_enabled=True,
                           crossfade_seconds=0.10, start_offset_seconds=0.0):
    """Return an FFmpeg filter graph that joins repeated music copies with short crossfades."""
    values = (music_duration, target_duration, crossfade_seconds, start_offset_seconds)
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(float(value)) for value in values):
        raise ValueError("Music-loop timing values must be finite numbers.")
    duration = float(music_duration) - float(start_offset_seconds)
    target = float(target_duration)
    fade = float(crossfade_seconds)
    if duration <= 0 or target <= 0 or fade < 0:
        raise ValueError("Music duration/target must be positive and crossfade non-negative.")
    if not loop_enabled or duration >= target or fade == 0:
        return {
            "graph": "", "output_label": "1:a:0", "loop_count": 1,
            "source_duration_seconds": duration, "crossfade_seconds": 0.0,
        }
    # Short clips need a proportionally shorter overlap, otherwise acrossfade
    # could consume almost the entire cycle.
    fade = min(fade, duration / 3.0)
    if fade <= 0.005:
        return {
            "graph": "", "output_label": "1:a:0", "loop_count": 1,
            "source_duration_seconds": duration, "crossfade_seconds": 0.0,
        }
    cycle_step = duration - fade
    loop_count = max(2, math.ceil((target - fade) / cycle_step))
    labels = [f"hey_music_src_{index}" for index in range(loop_count)]
    parts = [f"[1:a:0]asplit={loop_count}" + "".join(f"[{label}]" for label in labels)]
    for index, label in enumerate(labels):
        parts.append(
            f"[{label}]atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[hey_music_{index}]"
        )
    current = "hey_music_0"
    for index in range(1, loop_count):
        output = f"hey_music_join_{index}"
        parts.append(
            f"[{current}][hey_music_{index}]acrossfade=d={fade:.6f}:c1=tri:c2=tri[{output}]"
        )
        current = output
    parts.append(f"[{current}]atrim=duration={target:.6f},asetpts=PTS-STARTPTS[looped_music]")
    return {
        "graph": ";".join(parts),
        "output_label": "looped_music",
        "loop_count": loop_count,
        "source_duration_seconds": round(duration, 6),
        "crossfade_seconds": round(fade, 6),
    }


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
    crop_filter = f"crop={WIDTH}:{HEIGHT},"
    dynamic_crop = None
    if LAYOUT_MODE == "fill" and SUBJECT_OBSERVATIONS:
        dynamic_crop = build_dynamic_crop_path(
            SUBJECT_OBSERVATIONS, start, input_duration,
            max_distance_seconds=max(1.0, input_duration / 2.0),
        )
    if dynamic_crop is not None:
        crop_filter = (
            f"crop={WIDTH}:{HEIGHT}:"
            f"x='{dynamic_crop['x_expression']}':"
            f"y='{dynamic_crop['y_expression']}',"
        )
        print(
            f"  [framing] Smoothed dynamic 9:16 crop for source {start:.2f}–"
            f"{start + input_duration:.2f}s using {len(dynamic_crop['points'])} path points."
        )
    elif subject_observation is not None and LAYOUT_MODE == "fill":
        # If the track cannot anchor both clip edges, preserve the previous
        # bounded constant-centroid crop rather than extrapolating wildly.
        subject_x = float(subject_observation["center_x"])
        subject_y = float(subject_observation["center_y"])
        crop_filter = (
            f"crop={WIDTH}:{HEIGHT}:"
            f"x='max(0,min(iw-ow,{subject_x:.5f}*iw-ow/2))':"
            f"y='max(0,min(ih-oh,{subject_y:.5f}*ih-oh/2))',"
        )
        print(
            f"  [framing] Constant subject-proxy crop fallback near source {clip_center_seconds:.2f}s "
            f"(center={subject_x:.2f},{subject_y:.2f}; not identity recognition)."
        )

    # If optional OpenCV tracking found no stable person-shaped track, this remains
    # the deterministic centered 9:16 crop fallback.
    if LAYOUT_MODE == "fill":
        vf = (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"{crop_filter}"
            f"{'hflip,' if MIRROR_ENABLED else ''}"
            "eq=contrast=1.16:saturation=1.30:gamma=1.02,"
            "unsharp=5:5:0.72:3:3:0.0,setsar=1,"
            f"fps={FPS},setpts=PTS/{SPEED},fps={FPS},tpad=stop_mode=clone:stop={output_frames},trim=end_frame={output_frames},setpts=PTS-STARTPTS[v]"
        )
    else:
        vf = (
            "[0:v]split=2[bg][fg];"
            f"[bg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={WIDTH}:{HEIGHT},boxblur=20:2,eq=brightness=-0.08:saturation=0.78[back];"
            f"[fg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos"
            f"{mirror},"
            "eq=contrast=1.16:saturation=1.30:gamma=1.02,"
            "unsharp=5:5:0.72:3:3:0.0[front];"
            "[back][front]overlay=(W-w)/2:(H-h)/2,setsar=1,"
            f"fps={FPS},setpts=PTS/{SPEED},fps={FPS},tpad=stop_mode=clone:stop={output_frames},trim=end_frame={output_frames},setpts=PTS-STARTPTS[v]"
        )

    # AI mode upscales the selected source frames losslessly before the normal
    # composition crop. Standard mode keeps the existing direct FFmpeg path.
    ai_root = None
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if AI_UPSCALE_ENABLED:
        source_rate = float(SOURCE_FPS or FPS or 30.0)
        source_frame_count = max(1, round(input_duration * source_rate))
        pre_crop = None
        if LAYOUT_MODE == "fill":
            center_x = float(subject_observation["center_x"]) if subject_observation else 0.5
            center_y = float(subject_observation["center_y"]) if subject_observation else 0.5
            pre_crop = build_pre_upscale_crop_filter(dynamic_crop, center_x, center_y)
        pattern, ai_root = prepare_ai_upscaled_frames(
            index, start, input_duration, source_frame_count,
            source_fps=source_rate, pre_upscale_crop_filter=pre_crop,
        )
        cmd += [
            "-framerate", f"{source_rate:.6f}", "-start_number", "1",
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
        "-c:v", CODEC, "-preset", PRESET, "-crf", str(INTERMEDIATE_CRF),
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
        f"scale={round(WIDTH * 1.1)}:{round(HEIGHT * 1.1)}:flags=lanczos,"
        f"crop={WIDTH}:{HEIGHT}:x='(iw-ow)/2+5*sin(t*90)':y='(ih-oh)/2+5*cos(t*73)',"
        "eq=contrast=1.38:saturation=0,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=white@0.55:t=fill:enable='lt(t,0.05)',"
        f"fps={FPS},trim=end_frame={duration_frames},setpts=PTS-STARTPTS"
    )
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", str(FPS), "-i", still_path,
        "-vf", freeze_filter, "-an", "-frames:v", str(duration_frames),
        "-c:v", CODEC, "-preset", PRESET, "-crf", str(INTERMEDIATE_CRF),
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
    """Measure black intervals, decoded sample level and encoded true peak; not aesthetics."""
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

    # Measure the already encoded AAC output; sample peak alone can miss inter-sample peaks.
    true_peak_cmd = [
        "ffmpeg", "-hide_banner", "-i", path, "-vn",
        "-af", "ebur128=peak=true", "-f", "null", "-",
    ]
    true_peak_result = subprocess.run(
        true_peak_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=False,
    )
    true_peak_log = (true_peak_result.stderr or "") + "\n" + (true_peak_result.stdout or "")
    if true_peak_result.returncode != 0:
        errors.append("true_peak_measurement_failed")
    match = re.search(
        r"True peak:\s*Peak:\s*(-?inf|-?\d+(?:\.\d+)?)\s*dBFS",
        true_peak_log, re.IGNORECASE | re.DOTALL,
    )
    true_peak_dbfs = None
    if match:
        raw_true_peak = match.group(1).lower()
        if raw_true_peak not in {"-inf", "inf"}:
            try:
                parsed_true_peak = float(raw_true_peak)
                if math.isfinite(parsed_true_peak):
                    true_peak_dbfs = parsed_true_peak
            except ValueError:
                true_peak_dbfs = None
    if true_peak_dbfs is None and not audio_silent and "true_peak_measurement_failed" not in errors:
        errors.append("true_peak_unparsed")
    return {
        "black_segments": black_segments, "duration_seconds": float(duration),
        "mean_volume_db": mean_db, "max_volume_db": peak_db,
        "true_peak_dbfs": true_peak_dbfs,
        "audio_silent": audio_silent,
        "measurement_errors": errors,
        "blackdetect_threshold_seconds": 0.35,
        "blackdetect_pixel_threshold": 0.05,
        "method": "ffmpeg-blackdetect-and-volumedetect",
    }



def _run_variant_process(command, variant_index):
    """Run one variant in its own process group so Ctrl-C stops the whole render tree."""
    popen_options = {}
    if os.name == "nt":
        popen_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_options["start_new_session"] = True

    child = subprocess.Popen(command, **popen_options)
    try:
        returncode = child.wait()
    except KeyboardInterrupt:
        progress_event(
            "variant_interrupt", "running",
            f"Interrupt received; stopping variant {variant_index} and its render subprocesses.",
            {"variant_index": variant_index, "pid": child.pid},
        )
        if child.poll() is None:
            if os.name == "nt":
                try:
                    child.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
                except (OSError, ValueError):
                    child.terminate()
            else:
                try:
                    os.killpg(child.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    child.terminate()
                else:
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        child.kill()
                    else:
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    child.wait()
        progress_event(
            "variant_interrupt", "cancelled",
            f"Variant {variant_index} was cancelled; no further variants will start.",
            {"variant_index": variant_index, "exit_code": 130},
        )
        raise SystemExit(130) from None
    return subprocess.CompletedProcess(command, returncode)


def _run_variant_batch(args):
    """Render independent, reviewable variants without redownloading source media."""
    output_root = Path(os.environ.get("HEYAA_RUN_DIR", "output")) / "variants"
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
        completed = _run_variant_process(command, index)
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


def _new_run_id():
    return time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1000000:06d}"


def cleanup_part_files(root_paths=("input", "output")):
    """Remove leftover FFmpeg/download .part files before a new top-level run."""
    removed = []
    for root_value in root_paths:
        root = Path(root_value)
        if not root.exists():
            continue
        for path in root.rglob("*.part"):
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
                    removed.append(str(path))
            except OSError:
                continue
    return removed


def publish_latest_run(run_dir, output_root="output"):
    """Atomically point output/latest at a completed run without clobbering a real directory."""
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    run_path = Path(run_dir)
    relative_target = Path(os.path.relpath(run_path, root))
    latest = root / "latest"
    temporary = root / "latest.part"
    if temporary.is_symlink() or temporary.is_file():
        temporary.unlink()
    elif temporary.exists():
        raise RuntimeError(f"Refusing to replace non-file latest staging path: {temporary}")
    if latest.exists() and not latest.is_symlink():
        if latest.is_dir():
            raise RuntimeError("output/latest exists as a real directory; move it aside before publishing a run.")
        latest.unlink()
    elif latest.is_symlink():
        latest.unlink()
    temporary.symlink_to(relative_target, target_is_directory=True)
    os.replace(temporary, latest)
    return str(latest)


def create_contact_sheet(video_path, output_path, duration_seconds):
    """Write 12 evenly sampled preview frames into a compact PNG contact sheet."""
    sample_rate = max(0.1, 12.0 / max(0.1, float(duration_seconds)))
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_path),
        "-vf", f"fps={sample_rate:.6f},scale=180:320:flags=fast_bilinear,tile=4x3:nb_frames=12",
        "-frames:v", "1", str(output_path),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0 or not Path(output_path).is_file():
        raise RuntimeError(f"Could not create contact sheet: {result.stderr[-1000:]}")
    return str(output_path)


def describe_subject_tracking_context(layout_mode, long_source_mode, analysis):
    """Describe tracking state without claiming future detections or disabled crops."""
    analysis = analysis if isinstance(analysis, dict) else {}
    if long_source_mode:
        return (
            "Long-source chapter search is active; appearance tracking will run inside "
            "the selected chapter before clip allocation."
        )

    if analysis.get("detected"):
        span = analysis.get("track_span_seconds")
        quality = analysis.get("track_quality_proxy")
        summary = (
            "OpenCV found an appearance-consistent person track "
            f"({span}s span; quality proxy={quality}). "
        )
        if layout_mode == "fill":
            return summary + "Per-shot source timing and smoothed 9:16 crops will use nearby appearance observations."
        return (
            summary
            + "Source timing may use nearby appearance observations; blur-fit framing preserves "
            "the full source frame over a blurred background."
        )

    reason = str(analysis.get("reason") or "no stable track was detected")
    if layout_mode == "fill":
        fallback = "Using scene-density context and a centered 9:16 crop fallback."
    else:
        fallback = "Using audio/motion scene context and blur-fit full-frame framing."
    return f"Person tracking unavailable: {reason}. {fallback}"


def run_doctor():
    """Check core render dependencies plus optional OpenCV, Vulkan and free disk space."""
    checks = {}
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    checks["ffmpeg"] = {"status": "ok" if ffmpeg else "fail", "path": ffmpeg}
    checks["ffprobe"] = {"status": "ok" if ffprobe else "fail", "path": ffprobe}
    svg_ok = False
    svg_error = None
    if ffmpeg and Path(SKULL_ASSET).is_file():
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", "color=c=black:s=32x56:r=1:d=1",
            "-loop", "1", "-framerate", "1", "-i", SKULL_ASSET,
            "-filter_complex", "[0:v][1:v]overlay=(W-w)/2:(H-h)/2",
            "-frames:v", "1", "-f", "null", "-",
        ]
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
        svg_ok = result.returncode == 0
        svg_error = None if svg_ok else result.stderr[-800:]
    checks["svg_overlay"] = {"status": "ok" if svg_ok else "fail", "error": svg_error}
    try:
        import cv2
        checks["opencv"] = {"status": "ok", "version": getattr(cv2, "__version__", "unknown")}
    except Exception as exc:
        checks["opencv"] = {"status": "warning", "detail": str(exc)}
    settings_path = _settings_path()
    ai_enabled = False
    binary = "tools/realesrgan/realesrgan-ncnn-vulkan"
    model_dir = "tools/realesrgan/models"
    try:
        settings = json.loads(Path(settings_path).read_text(encoding="utf-8"))
        video_settings = settings.get("video_settings", {})
        ai_enabled = video_settings.get("ai_upscale_enabled", False) is True
        binary = video_settings.get("ai_upscale_binary", binary)
        model_dir = video_settings.get("ai_upscale_model_dir", model_dir)
    except (OSError, ValueError, AttributeError):
        checks["settings"] = {"status": "warning", "detail": f"Could not inspect {settings_path}"}
    binary_path = Path(binary)
    if not binary_path.is_absolute():
        binary_path = Path.cwd() / binary_path
    models_path = Path(model_dir)
    if not models_path.is_absolute():
        models_path = Path.cwd() / models_path
    upscale_ok = binary_path.is_file() and models_path.is_dir()
    checks["vulkan_realesrgan"] = {
        "status": "ok" if upscale_ok else ("fail" if ai_enabled else "warning"),
        "enabled_in_settings": ai_enabled, "binary_exists": binary_path.is_file(),
        "models_directory_exists": models_path.is_dir(),
    }
    free_bytes = shutil.disk_usage(".").free
    checks["disk"] = {
        "status": "ok" if free_bytes >= 1024 ** 3 else ("warning" if free_bytes >= 256 * 1024 ** 2 else "fail"),
        "free_gib": round(free_bytes / (1024 ** 3), 2),
    }
    failed = any(checks[name]["status"] == "fail" for name in ("ffmpeg", "ffprobe", "svg_overlay", "disk"))
    if ai_enabled and not upscale_ok:
        failed = True
    result = {"status": "fail" if failed else "ok", "checks": checks}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def build_skull_overlay_graph(final_freeze_start):
    """Build the optional skull overlay without changing the final-freeze timeline."""
    if not ENDING_SKULL_ENABLED:
        return "", "[impact_raw]"
    skull_size_px = max(80, round(ENDING_SKULL_SIZE_PX * WIDTH / 1080))
    skull_pop_frames = max(1, round(ENDING_SKULL_POP_SECONDS * FPS))
    graph = (
        f"[2:v]scale=w='if(lt(n,{skull_pop_frames}),{skull_size_px}*(0.62+0.38*n/{skull_pop_frames}),{skull_size_px})':h=-1:eval=frame,setpts=PTS+{final_freeze_start:.6f}/TB[skull];"
        f"[impact_raw][skull]overlay=x='(W-w)*{ENDING_SKULL_POSITION_X:.5f}':y='(H-h)*{ENDING_SKULL_POSITION_Y:.5f}':enable='gte(t,{final_freeze_start:.5f})'[impact];"
    )
    return graph, "[impact]"


def main(argv=None):
    global VIDEO, MUSIC, REFERENCE, EDIT_DURATION, DURATION, FREEZE, SUBJECT_OBSERVATIONS, SOURCE_FPS
    global OUTDIR, WORK, FINAL, VARIANT_INDEX, PREVIEW_MODE, RUN_DIR
    args = parse_media_source_args(argv)
    ANALYSIS_CACHE_REPORT.clear()
    if args.command == "doctor":
        return run_doctor()
    PREVIEW_MODE = bool(args.preview)
    if PREVIEW_MODE:
        args.variants = 1
    if args.clip_count_options is not None and args.clip_count is not None:
        raise SystemExit("Use either --clip-count or --clip-count-options, not both.")
    if args.clip_count_options is not None and args.variant_index is None and args.variants == 1:
        if len(args.clip_count_options) != 1:
            raise SystemExit("--variants 1 requires exactly one --clip-count-options value.")
        args.clip_count = args.clip_count_options[0]
    if args.variant_index is None:
        removed_parts = cleanup_part_files()
        RUN_DIR = Path("output") / "runs" / _new_run_id()
        os.environ["HEYAA_RUN_DIR"] = str(RUN_DIR)
        if removed_parts:
            print(f"[cleanup] Removed {len(removed_parts)} leftover .part file(s).", flush=True)
    else:
        RUN_DIR = Path(os.environ.get("HEYAA_RUN_DIR", str(Path("output") / "runs" / _new_run_id())))
        os.environ["HEYAA_RUN_DIR"] = str(RUN_DIR)
    VARIANT_INDEX = args.variant_index
    if VARIANT_INDEX is None and args.variants > 1:
        OUTDIR = str(RUN_DIR)
        WORK = str(RUN_DIR / "work")
        FINAL = str(RUN_DIR / "final_phonk_20s.mp4")
        Path(OUTDIR).mkdir(parents=True, exist_ok=True)
        reset_progress_log()
        progress_event("run", "started", "Starting comparison render batch.")
        _run_variant_batch(args)
        sheet_source = next(iter(sorted((RUN_DIR / "variants").glob("variant_*/final_phonk.mp4"))), None)
        if sheet_source and sheet_source.is_file():
            try:
                create_contact_sheet(sheet_source, RUN_DIR / "contact_sheet.png", DURATION or 20)
            except Exception as exc:
                print(f"[warn] Contact sheet skipped: {exc}", flush=True)
        publish_latest_run(RUN_DIR)
        return 0
    if VARIANT_INDEX is not None:
        OUTDIR = str(RUN_DIR / "variants" / f"variant_{VARIANT_INDEX:02d}")
        WORK = str(Path(OUTDIR) / "work")
        FINAL = str(Path(OUTDIR) / "final_phonk.mp4")
    else:
        OUTDIR = str(RUN_DIR)
        WORK = str(RUN_DIR / "work")
        FINAL = str(RUN_DIR / ("preview.mp4" if PREVIEW_MODE else "final_phonk_20s.mp4"))
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
    SOURCE_FPS = get_source_frame_rate(VIDEO, fallback_fps=FPS)
    music_duration = duration_of(MUSIC)
    if source_duration < 0.8:
        raise SystemExit("[ERROR] Source video is too short to edit.")
    print(f"[source] Video {source_duration:.2f}s | Music {music_duration:.2f}s")
    print(f"[target] {WIDTH}x{HEIGHT}, {FPS} FPS, {DURATION:.1f}s, Phonk/Montagem")
    if music_duration < DURATION:
        if MUSIC_LOOP:
            message = (f"Soundtrack ({music_duration:.2f}s) is shorter than the edit "
                       f"({DURATION:.2f}s); seamlessness is improved with {0.10:.2f}s crossfades.")
        else:
            message = (f"Soundtrack ({music_duration:.2f}s) is shorter than the edit "
                       f"({DURATION:.2f}s); remaining timeline will be padded with silence.")
        print("[warn] " + message, flush=True)
        progress_event("music_length", "needs_review", message,
                       {"music_duration_seconds": music_duration, "edit_duration_seconds": DURATION,
                        "loop_enabled": MUSIC_LOOP, "crossfade_seconds": 0.10 if MUSIC_LOOP else None})

    progress_event("media_analysis", "running", "Detecting source scene changes.")
    scenes, scene_cache_hit = cached_analysis(
        "scene_changes", [VIDEO],
        {"source_duration": round(source_duration, 3), "threshold": 0.22, "analysis_scale_width": 320},
        lambda: detect_scenes(VIDEO, source_duration),
    )
    progress_event("media_analysis", "completed", f"Measured {len(scenes)} source scene-change candidate(s).",
                   {"scene_change_count": len(scenes), "source_duration_seconds": source_duration,
                    "analysis_cache_hit": scene_cache_hit})
    available_edit_duration = DURATION - FREEZE
    progress_event("beat_analysis", "running", "Measuring bass-onset / beat candidates.")
    if BEAT_SYNC:
        beat_bundle, beat_cache_hit = cached_analysis(
            "music_beats", [MUSIC],
            {"target_duration": round(available_edit_duration, 4), "fps": FPS,
             "enabled": BEAT_SYNC, "grid_method": "period_phase_v1"},
            lambda: {
                "beats": detect_music_beats(MUSIC, available_edit_duration),
                "grid": dict(BEAT_GRID_ANALYSIS),
            },
        )
        raw_beats = beat_bundle["beats"]
        BEAT_GRID_ANALYSIS.clear()
        BEAT_GRID_ANALYSIS.update(beat_bundle["grid"])
    else:
        raw_beats = []
        BEAT_GRID_ANALYSIS.update({
            "method": "disabled", "confidence": None, "period_seconds": None,
            "phase_seconds": None, "candidate_count": 0, "onset_candidate_count": 0,
        })
    beats = extend_looped_beats(raw_beats, music_duration, available_edit_duration, MUSIC_LOOP)
    progress_event("beat_analysis", "completed" if BEAT_SYNC else "skipped",
                   f"Prepared {len(beats)} timing candidate(s).",
                   {"beat_sync_enabled": BEAT_SYNC, "candidate_count": len(beats),
                    "music_loop_enabled": MUSIC_LOOP,
                    "grid_method": BEAT_GRID_ANALYSIS["method"],
                    "grid_confidence": BEAT_GRID_ANALYSIS["confidence"],
                    "grid_period_seconds": BEAT_GRID_ANALYSIS["period_seconds"],
                    "grid_phase_seconds": BEAT_GRID_ANALYSIS["phase_seconds"],
                    "analysis_cache_hit": beat_cache_hit if BEAT_SYNC else False})
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
    if REFERENCE_PACING:
        ref_profile, reference_cache_hit = cached_analysis(
            "reference_pacing", [REFERENCE],
            {"fps": FPS, "reference_pacing_enabled": REFERENCE_PACING},
            lambda: reference_pacing_profile(REFERENCE),
        )
    else:
        ref_profile, reference_cache_hit = None, False
    ref_interval = ref_profile.get("median_cut_interval_seconds") if ref_profile else None
    progress_event("reference_analysis", "completed" if ref_interval is not None else ("skipped" if not REFERENCE_PACING else "needs_review"),
                   "Reference pacing profile ready." if ref_interval is not None else "No usable measured reference interval; configured fallback will be used.",
                   {"median_cut_interval_seconds": ref_interval,
                    "reference_available": _has_usable_reference_profile(ref_profile),
                    "analysis_cache_hit": reference_cache_hit})
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
                    "max_clips": MAX_CLIPS, "min_shot_seconds": MIN_SHOT_SECONDS, "reference_median_cut_interval_seconds": ref_interval})
    boundaries_seconds = make_boundaries(clip_count, adjusted_beats, ref_profile)
    planned_drop_position = None
    if drop_beat_time is not None:
        boundaries_seconds, planned_drop_position = insert_drop_boundary(boundaries_seconds, drop_beat_time, min_gap=MIN_SHOT_SECONDS)
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
    source_scope = choose_source_selection_scope(
        source_duration, EDIT_DURATION, context_start, context_end
    )
    source_scope_start = source_scope["start_seconds"]
    source_scope_end = source_scope["end_seconds"]
    source_scope_duration = source_scope_end - source_scope_start
    source_scope_scenes = sorted(
        cut - source_scope_start for cut in scenes
        if source_scope_start <= cut <= source_scope_end
    )
    long_source_mode = source_scope["method"] == "full_source_long_video"
    if long_source_mode:
        subject_analysis = {
            "available": False, "detected": False, "method": "pending-source-chapter-selection",
            "reason": "Appearance tracking will run inside the selected contiguous source chapter.",
            "observations": [], "track_id": None, "track_quality_proxy": None,
            "identity_semantics": False,
        }
    elif SUBJECT_LOCK_ENABLED:
        subject_analysis = detect_person_track(VIDEO, context_start, context_end)
    else:
        subject_analysis = {
            "available": False, "detected": False, "method": "subject-lock-disabled",
            "reason": "Subject appearance lock is disabled in edit settings.",
            "observations": [], "track_id": None, "track_quality_proxy": None,
            "identity_semantics": False,
        }
    SUBJECT_OBSERVATIONS = subject_analysis.get("observations", []) if subject_analysis.get("detected") else []
    context["subject_tracking"] = {
        key: value for key, value in subject_analysis.items() if key != "observations"
    }
    context["preview_mode"] = PREVIEW_MODE
    context["dynamic_crop"] = {
        "configured_method": "piecewise_linear_low_pass" if LAYOUT_MODE == "fill" else "blur_fit_full_frame",
        "enabled_when_near_track_observations": bool(subject_analysis.get("detected") and LAYOUT_MODE == "fill"),
        "smoothing_tau_seconds": 0.65,
        "bounds_clamped_by_ffmpeg": True,
    }
    print(
        f"[context] {describe_subject_tracking_context(LAYOUT_MODE, long_source_mode, subject_analysis)}"
    )
    context_duration = max(0.1, context_end - context_start)
    context_scenes = sorted(cut - context_start for cut in scenes if context_start <= cut <= context_end)
    source_gap_frames = round(MIN_SOURCE_GAP_SECONDS * FPS)
    clip_source_durations = [
        max(1, round((end_f - start_f) * SPEED))
        for start_f, end_f in zip(frame_boundaries, frame_boundaries[1:])
    ]
    planned_source_ranges = None
    source_chapter_report = {
        "applied": False, "method": "pending_chapter_selection" if long_source_mode else "short_source_context",
        "start_seconds": round(source_scope_start, 3), "end_seconds": round(source_scope_end, 3),
        "duration_seconds": round(source_scope_duration, 3), "semantic_context_understanding": False,
    }
    character_lock_report = {
        "requested": SUBJECT_LOCK_ENABLED, "applied": False, "preference_applied": False,
        "detected": bool(subject_analysis.get("detected")),
        "method": "pending_source_chapter_selection" if long_source_mode else "short_source_framing_only",
        "track_quality_proxy": subject_analysis.get("track_quality_proxy"),
        "track_span_seconds": subject_analysis.get("track_span_seconds"),
        "identity_semantics": False,
    }
    context["source_chapter"] = dict(source_chapter_report)
    context["character_lock"] = dict(character_lock_report)
    source_selection_report = {
        "method": "legacy_snap_then_progression",
        "source_audio_available": False,
        "measured_scene_segment_count": 0,
        "unique_scene_segments_used": 0,
        "forced_progression_shift_count": 0,
        "fallback_reason": "source_has_no_audio_or_feature_measurement_unavailable",
    }
    progress_event(
        "source_selection_scope", "completed",
        f"Search scope is {source_scope_start:.2f}s–{source_scope_end:.2f}s "
        f"({source_scope_duration:.2f}s; {source_scope['method']}).",
        {"method": source_scope["method"], "start_seconds": source_scope_start,
         "end_seconds": source_scope_end, "duration_seconds": source_scope_duration,
         "threshold_seconds": source_scope["threshold_seconds"],
         "candidate_window_max_seconds": 4.0 if source_scope["method"] == "full_source_long_video" else None},
    )
    if source_scope["method"] == "full_source_long_video":
        print(
            "[source] Long-source mode scores bounded windows across the full recording; "
            "loudness/motion are proxies, not semantic action or identity recognition.",
            flush=True,
        )
    source_audio_available = _source_has_audio(VIDEO)
    source_feature_error = None
    measured_segment_count = 0
    chapter_candidate_count = 0
    source_chapter_cache_hit = False
    if source_audio_available:
        try:
            bounded_segments = long_source_mode
            if bounded_segments:
                chapter_candidates = build_source_scene_segments(
                    source_scope_start, source_scope_end, [], max_segment_seconds=SOURCE_CHAPTER_SECONDS
                )
                measured_chapters, source_chapter_cache_hit = cached_analysis(
                    "source_chapter_features", [VIDEO],
                    {"chapters": chapter_candidates, "fps": FPS, "feature_version": 1,
                     "signals": ["source_audio_rms", "frame_difference_motion"]},
                    lambda: measure_source_scene_features(VIDEO, chapter_candidates),
                )
                chapter_candidate_count = len(measured_chapters)
                activity_seed_report, _ = choose_source_chapter(
                    measured_chapters, source_scope_start, source_scope_end, SOURCE_CHAPTER_SECONDS
                )
                chapter_track_reports = (
                    measure_candidate_chapter_tracks(
                        VIDEO, activity_seed_report.get("candidate_chapters_ranked", [])[:3], max_candidates=3
                    ) if SUBJECT_LOCK_ENABLED else []
                )
                source_chapter_report, _ = choose_source_chapter(
                    measured_chapters, source_scope_start, source_scope_end, SOURCE_CHAPTER_SECONDS,
                    subject_chapter_reports=chapter_track_reports,
                )
                chapter_start, chapter_end = source_chapter_report["start_seconds"], source_chapter_report["end_seconds"]
                context.update({
                    "start_seconds": chapter_start, "end_seconds": chapter_end,
                    "window_seconds": source_chapter_report["duration_seconds"],
                    "scene_cuts": sum(1 for cut in scenes if chapter_start <= cut < chapter_end),
                    "method": "activity-ranked-contiguous-chapter", "same_person_tracking": False,
                    "source_chapter": dict(source_chapter_report),
                })
                context_start, context_end = chapter_start, chapter_end
                context_duration = max(0.1, chapter_end - chapter_start)
                context_scenes = sorted(cut - chapter_start for cut in scenes if chapter_start <= cut <= chapter_end)
                print(
                    f"[chapter] Chose {chapter_start:.2f}s–{chapter_end:.2f}s "
                    f"({source_chapter_report['duration_seconds']:.2f}s) from {chapter_candidate_count} contiguous chapters "
                    f"using {source_chapter_report.get('selection_policy', 'activity-only')} evidence; not semantic recognition.", flush=True,
                )
                progress_event(
                    "source_chapter_selection", "completed",
                    f"Selected source chapter {chapter_start:.2f}s–{chapter_end:.2f}s from "
                    f"{chapter_candidate_count} coarse candidates using {source_chapter_report.get('selection_policy', 'activity-only')} evidence.",
                    source_chapter_report,
                )
                if SUBJECT_LOCK_ENABLED:
                    progress_event("character_lock", "running", "Tracking the dominant appearance proxy inside the selected chapter.")
                    subject_analysis = detect_person_track(VIDEO, chapter_start, chapter_end)
                else:
                    subject_analysis = {
                        "available": False, "detected": False, "method": "subject-lock-disabled",
                        "reason": "Subject appearance lock is disabled in edit settings.",
                        "observations": [], "track_id": None, "track_quality_proxy": None, "identity_semantics": False,
                    }
                SUBJECT_OBSERVATIONS = subject_analysis.get("observations", []) if subject_analysis.get("detected") else []
                context["subject_tracking"] = {key: value for key, value in subject_analysis.items() if key != "observations"}
                character_lock_report.update({
                    "method": subject_analysis.get("method", "unavailable"),
                    "detected": bool(subject_analysis.get("detected")),
                    "track_id": subject_analysis.get("track_id"),
                    "track_span_seconds": subject_analysis.get("track_span_seconds"),
                    "track_quality_proxy": subject_analysis.get("track_quality_proxy"),
                    "selected_chapter_start_seconds": chapter_start, "selected_chapter_end_seconds": chapter_end,
                })
                scene_segments = build_source_scene_segments(chapter_start, chapter_end, scenes, max_segment_seconds=4.0)
                source_scope_for_features = "selected_source_chapter"
            else:
                scene_segments = build_source_scene_segments(source_scope_start, source_scope_end, scenes, max_segment_seconds=None)
                source_scope_for_features = source_scope["method"]
            measured_segments, source_feature_cache_hit = cached_analysis(
                "source_scene_features", [VIDEO],
                {"scene_segments": scene_segments, "fps": FPS, "audio_weight": 0.6,
                 "motion_weight": 0.4, "feature_version": 4 if bounded_segments else 3,
                 "scope_method": source_scope_for_features,
                 "max_segment_seconds": 4.0 if bounded_segments else None},
                lambda: measure_source_scene_features(VIDEO, scene_segments),
            )
            measured_segment_count = len(measured_segments)
            if bounded_segments and SUBJECT_OBSERVATIONS:
                measured_segments = add_subject_presence_scores(measured_segments, SUBJECT_OBSERVATIONS)
            subject_segment_count = sum(1 for item in measured_segments if item.get("subject_presence_score", 0.0) > 0.0)
            preference_applied = bool(bounded_segments and SUBJECT_LOCK_ENABLED and SUBJECT_OBSERVATIONS and subject_segment_count)
            subject_lock_mode = "not_applicable"
            hard_lock_diagnostics = {
                "applied": False, "reason": "No stable subject observations were measured.",
                "minimum_presence_score": 0.35, "eligible_segment_count": 0, "identity_semantics": False,
            }
            hard_locked_ranges = None
            if bounded_segments and preference_applied:
                hard_locked_ranges, hard_lock_diagnostics = plan_subject_locked_source_ranges(
                    clip_source_durations, measured_segments, FPS, source_gap_frames, minimum_presence_score=0.35
                )
            if hard_locked_ranges is not None:
                planned_source_ranges = hard_locked_ranges
                subject_lock_mode = "subject_presence_constrained"
            else:
                planned_source_ranges = plan_ranked_disjoint_source_ranges(
                    clip_source_durations, measured_segments, FPS, source_gap_frames
                )
                if bounded_segments:
                    subject_lock_mode = "soft_appearance_preference" if preference_applied else "chapter_context_only"
            if bounded_segments:
                character_lock_report.update({
                    "applied": bool(SUBJECT_LOCK_ENABLED and subject_analysis.get("detected")),
                    "preference_applied": preference_applied,
                    "hard_presence_lock_applied": hard_locked_ranges is not None,
                    "selection_mode": subject_lock_mode,
                    "hard_lock_threshold": 0.35,
                    "hard_lock_eligible_segment_count": hard_lock_diagnostics.get("eligible_segment_count", 0),
                    "hard_lock_fallback_reason": None if hard_locked_ranges is not None else hard_lock_diagnostics.get("reason"),
                    "segments_with_subject_evidence": subject_segment_count,
                    "identity_semantics": False,
                    "note": (
                        "All selected source intervals passed the repeated appearance-presence threshold; this is not verified real-player identity."
                        if hard_locked_ranges is not None else
                        "A hard appearance constraint was unavailable or infeasible; audio/motion ranking uses appearance as a soft preference when observations exist. This is not identity verification."
                    ),
                })
                context["character_lock"] = dict(character_lock_report)
                context["dynamic_crop"] = {
                    "configured_method": "piecewise_linear_low_pass" if LAYOUT_MODE == "fill" else "blur_fit_full_frame",
                    "enabled_when_near_track_observations": bool(SUBJECT_OBSERVATIONS and LAYOUT_MODE == "fill"),
                    "smoothing_tau_seconds": 0.65, "bounds_clamped_by_ffmpeg": True,
                }
                if hard_locked_ranges is not None:
                    print(
                        f"[character-lock] Applied subject-presence constraint to all {len(hard_locked_ranges)} clips "
                        f"from {hard_lock_diagnostics['eligible_segment_count']} eligible intervals; "
                        "visual appearance is still not verified player identity.", flush=True,
                    )
                    lock_status, lock_summary = "completed", "All selected clip ranges met the measured subject-presence threshold."
                elif preference_applied:
                    print(
                        f"[character-lock] Hard lock unavailable ({hard_lock_diagnostics.get('reason')}); "
                        f"using soft appearance preference across {subject_segment_count} intervals.", flush=True,
                    )
                    lock_status, lock_summary = "needs_review", "Subject tracking informed ranking, but did not constrain every selected clip."
                else:
                    print(
                        f"[character-lock] No stable appearance track available: {subject_analysis.get('reason', 'not detected')}. "
                        "Chapter-level coherence remains active.", flush=True,
                    )
                    lock_status, lock_summary = "needs_review", "No reliable character lock was applied; the selected chapter is only a context boundary."
                progress_event("character_lock", lock_status, lock_summary, character_lock_report)
            used_segment_counts = {}
            for assignment in planned_source_ranges:
                key = assignment["scene_segment_index"]
                used_segment_counts[key] = used_segment_counts.get(key, 0) + 1
            source_selection_report = {
                "method": "subject_presence_constrained_disjoint_scene_segments" if subject_lock_mode == "subject_presence_constrained" else "ranked_disjoint_scene_segments", "source_audio_available": True,
                "measured_scene_segment_count": measured_segment_count,
                "chapter_candidates_measured": chapter_candidate_count if bounded_segments else None,
                "selected_chapter_segment_count": len(measured_segments) if bounded_segments else None,
                "unique_scene_segments_used": len(used_segment_counts),
                "scene_segments_reused_for_multiple_clips": sum(1 for count in used_segment_counts.values() if count > 1),
                "forced_progression_shift_count": 0,
                "audio_score_weight": 0.6 if not preference_applied else 0.27,
                "motion_score_weight": 0.4 if not preference_applied else 0.18,
                "subject_presence_score_weight": 0.55 if preference_applied else 0.0,
                "subject_lock_mode": subject_lock_mode,
                "hard_presence_lock_applied": subject_lock_mode == "subject_presence_constrained",
                "source_chapter": dict(source_chapter_report), "character_lock": dict(character_lock_report),
                "fallback_reason": None,
            }
            print(
                f"[source] Ranked {measured_segment_count} detailed scene segments"
                + (f" inside chapter {source_chapter_report['start_seconds']:.2f}s–{source_chapter_report['end_seconds']:.2f}s" if bounded_segments else "")
                + f"; assigned {len(planned_source_ranges)} chronological, disjoint clip ranges."
            )
        except (RuntimeError, ValueError, OSError) as exc:
            source_feature_error = str(exc)
            planned_source_ranges = None
            source_selection_report = {
                "method": "legacy_snap_then_progression", "source_audio_available": True,
                "measured_scene_segment_count": measured_segment_count,
                "chapter_candidates_measured": chapter_candidate_count if long_source_mode else None,
                "unique_scene_segments_used": 0, "forced_progression_shift_count": 0,
                "fallback_reason": source_feature_error,
            }
            print(f"[warn] Ranked scene selection unavailable ({exc}); using bounded source progression where possible.", flush=True)
    else:
        print("[source] No audio stream in source video; using bounded scene-context fallback where possible.")
    if long_source_mode and planned_source_ranges is None:
        fallback_chapter = choose_context_window(source_duration, scenes, SOURCE_CHAPTER_SECONDS / 2.0)
        chapter_start, chapter_end = fallback_chapter["start_seconds"], fallback_chapter["end_seconds"]
        source_chapter_report = {
            "applied": True, "method": "scene-density-chapter-fallback",
            "start_seconds": chapter_start, "end_seconds": chapter_end,
            "duration_seconds": round(chapter_end - chapter_start, 3),
            "selection_score": None, "candidate_chapters": chapter_candidate_count or None,
            "selected_chapter_index": None, "measured_segment_count": measured_segment_count,
            "fallback_reason": source_feature_error or "Source audio/features unavailable.",
            "semantic_context_understanding": False,
        }
        source_scope = {**source_scope, "start_seconds": chapter_start, "end_seconds": chapter_end, "method": "scene_density_chapter_fallback"}
        source_scope_start, source_scope_end = chapter_start, chapter_end
        source_scope_duration = chapter_end - chapter_start
        source_scope_scenes = sorted(cut - chapter_start for cut in scenes if chapter_start <= cut <= chapter_end)
        context.update({
            "start_seconds": chapter_start, "end_seconds": chapter_end,
            "window_seconds": source_chapter_report["duration_seconds"],
            "scene_cuts": fallback_chapter.get("scene_cuts", 0),
            "method": "scene-density-chapter-fallback", "same_person_tracking": False,
            "source_chapter": dict(source_chapter_report),
        })
        context_start, context_end = chapter_start, chapter_end
        context_duration = max(0.1, chapter_end - chapter_start)
        context_scenes = source_scope_scenes
        if SUBJECT_LOCK_ENABLED:
            subject_analysis = detect_person_track(VIDEO, chapter_start, chapter_end)
        else:
            subject_analysis = {
                "available": False, "detected": False, "method": "subject-lock-disabled",
                "reason": "Subject appearance lock is disabled in edit settings.",
                "observations": [], "track_id": None, "track_quality_proxy": None, "identity_semantics": False,
            }
        SUBJECT_OBSERVATIONS = subject_analysis.get("observations", []) if subject_analysis.get("detected") else []
        character_lock_report = {
            "requested": SUBJECT_LOCK_ENABLED, "applied": False, "preference_applied": False,
            "detected": bool(subject_analysis.get("detected")), "method": subject_analysis.get("method", "unavailable"),
            "track_id": subject_analysis.get("track_id"), "track_span_seconds": subject_analysis.get("track_span_seconds"),
            "track_quality_proxy": subject_analysis.get("track_quality_proxy"),
            "selected_chapter_start_seconds": chapter_start, "selected_chapter_end_seconds": chapter_end,
            "identity_semantics": False,
            "note": "Fallback chapter is bounded by scene density; HOG observations may guide framing but are not a hard identity lock.",
        }
        context["subject_tracking"] = {key: value for key, value in subject_analysis.items() if key != "observations"}
        context["character_lock"] = dict(character_lock_report)
        progress_event("source_chapter_selection", "needs_review",
                       f"Feature ranking was unavailable; bounded fallback chapter {chapter_start:.2f}s–{chapter_end:.2f}s selected by scene density.",
                       source_chapter_report)
        progress_event("character_lock", "needs_review",
                       "Fallback chapter is bounded, but no subject-weighted source allocation was available.",
                       character_lock_report)
        source_selection_report.update({"source_chapter": dict(source_chapter_report), "character_lock": dict(character_lock_report)})
    else:
        context["source_chapter"] = dict(source_chapter_report)
        context["character_lock"] = dict(character_lock_report)
        source_selection_report.update({"source_chapter": dict(source_chapter_report), "character_lock": dict(character_lock_report)})
    source_scope_scenes = sorted(cut - source_scope_start for cut in scenes if source_scope_start <= cut <= source_scope_end)
    source_selection_report.update({
        "scope_method": source_scope["method"],
        "scope_start_seconds": round(source_scope_start, 3),
        "scope_end_seconds": round(source_scope_end, 3),
        "scope_duration_seconds": round(source_scope_duration, 3),
        "candidate_window_max_seconds": 4.0 if source_scope["method"] == "full_source_long_video" else None,
        "selected_chapter_start_seconds": source_chapter_report.get("start_seconds"),
        "selected_chapter_end_seconds": source_chapter_report.get("end_seconds"),
        "chapter_analysis_cache_hit": source_chapter_cache_hit,
        "analysis_cache_hit": source_feature_cache_hit if source_audio_available and "source_feature_cache_hit" in locals() else False,
    })
    source_selection_summary = (
        f"Selected {len(planned_source_ranges)} non-overlapping clip ranges from "
        f"{source_selection_report['measured_scene_segment_count']} measured candidate windows."
        if planned_source_ranges is not None else
        f"Using source-progression fallback: {source_selection_report['fallback_reason']}."
    )
    progress_event(
        "source_selection", "completed" if planned_source_ranges is not None else "fallback",
        source_selection_summary, source_selection_report,
    )
    context["source_selection_scope"] = dict(source_scope)
    context["source_selection"] = source_selection_report
    edl_video = []
    output_cursor = 0
    previous_source_end_f = None
    forced_source_shift_count = 0
    clip_plan_index = 0
    for start_f, end_f in zip(frame_boundaries, frame_boundaries[1:]):
        dur_f = end_f - start_f
        if dur_f <= 0:
            raise RuntimeError("EDL contains a zero-length clip after frame quantization.")
        source_dur_f = clip_source_durations[clip_plan_index]
        if planned_source_ranges is not None:
            assignment = planned_source_ranges[clip_plan_index]
            source_start_f = assignment["source_start_f"]
            candidate_source_start_f = source_start_f
        else:
            timeline_center = (start_f + dur_f / 2) / FPS
            progress = max(0.0, min(1.0, timeline_center / max(EDIT_DURATION, 1 / FPS)))
            source_power = 1.0 if args.same_source_progression else VARIANT_SOURCE_POWERS.get(VARIANT_INDEX, 1.0)
            # Legacy fallback: snap a target to nearby scene cuts, then enforce
            # the EDL's chronological source progression constraint.
            local_target = (progress ** source_power) * source_scope_duration
            local_center = choose_source_center(local_target, source_scope_scenes, source_scope_duration)
            source_center = source_scope_start + local_center
            track_observation = subject_observation_near(
                SUBJECT_OBSERVATIONS, source_center,
                max_distance_seconds=max(1.5, dur_f / FPS)
            )
            if track_observation is not None:
                source_center = float(track_observation["time_seconds"])
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
                forced_source_shift_count += 1
                clip_number = sum(1 for x in edl_video if x["type"] == "clip") + 1
                print(
                    f"[edit] Shifted source start for clip {clip_number} from frame "
                    f"{candidate_source_start_f} to {source_start_f} to prevent source overlap.", flush=True
                )
        previous_source_end_f = source_start_f + source_dur_f
        clip_plan_index += 1
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

    print("[render 3/4] Adding bass-hit flashes, final freeze, and Phonk audio...")
    progress_event("final_render", "running", "Applying configured flashes, final freeze, optional skull overlay, audio processing and final encoding.")
    final_video = f"{WORK}/final_render.mp4"
    final_freeze_start = edit_frames / FPS
    flash_filter = make_flash_filter(beats)
    # Pad first, then split: the impact branch reads the cloned tail frames.
    # Only the freeze branch is enlarged/shaken, so normal footage stays stable.
    base_chain = (
        f"tpad=stop_mode=clone:stop={freeze_frames},"
        f"eq=contrast=1.32:saturation=0:enable='gte(t,{final_freeze_start:.6f})'"
    )
    if flash_filter:
        base_chain += "," + flash_filter
    base_chain += (
        f",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.78:t=fill:"
        f"enable='between(t,{final_freeze_start - 0.10:.3f},{final_freeze_start - 0.055:.3f})'"
    )
    impact_chain = (
        f"trim=start_frame={edit_frames}:end_frame={total_frames},"
        "setpts=PTS-STARTPTS,"
        f"fps={FPS},"
        f"scale={round(WIDTH * 1.1)}:{round(HEIGHT * 1.1)}:flags=lanczos,"
        f"crop={WIDTH}:{HEIGHT}:"
        "x='(iw-ow)/2+18*sin(t*70)':"
        "y='(ih-oh)/2+18*cos(t*57)',"
        "eq=contrast=1.48:saturation=0:brightness=0.015,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=white@0.55:t=fill:"
        "enable='lt(t,0.055)',"
        f"setpts=PTS+{final_freeze_start:.6f}/TB"
    )
    skull_graph, impact_video_label = build_skull_overlay_graph(final_freeze_start)
    filter_graph = (
        f"[0:v]{base_chain},split[base][impact_src];"
        "[base]setsar=1[baseout];"
        f"[impact_src]{impact_chain}[impact_raw];"
        f"{skull_graph}"
        f"[baseout]{impact_video_label}overlay=0:0:enable='gte(t,{final_freeze_start:.5f})',"
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
    audio_filter = ",".join(audio_filters)
    loop_graph = build_music_loop_graph(
        music_duration, DURATION, MUSIC_LOOP,
        crossfade_seconds=0.10, start_offset_seconds=audio_start_seconds,
    )
    audio_parts = []
    if loop_graph["graph"]:
        audio_parts.append(loop_graph["graph"])
    # Keep source music processing and the generated impact isolated until mixing.
    audio_parts.append(f"[{loop_graph['output_label']}]{audio_filter}[musicout]")
    # A procedural sub-bass frequency sweep plays at the start of the final freeze.
    if ENDING_IMPACT_SFX_ENABLED:
        impact_delay_ms = round(final_freeze_start * 1000)
        audio_parts.append(
            f"[{2 + int(ENDING_SKULL_ENABLED)}:a]adelay={impact_delay_ms}:all=1,apad=whole_dur={DURATION:.6f},"
            f"atrim=duration={DURATION:.6f},volume=0.55[impact_sfx]"
        )
        audio_parts.append(
            "[musicout][impact_sfx]amix=inputs=2:duration=first:dropout_transition=0,"
            "alimiter=limit=0.65:level=0[aout]"
        )
    else:
        audio_parts.append("[musicout]alimiter=limit=0.65:level=0[aout]")
    filter_graph += ";" + ";".join(audio_parts)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", joined]
    if audio_start_seconds > 0:
        cmd += ["-ss", f"{audio_start_seconds:.6f}"]
    cmd += ["-i", audio_source]
    if ENDING_SKULL_ENABLED:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-i", SKULL_ASSET]
    if ENDING_IMPACT_SFX_ENABLED:
        cmd += ["-f", "lavfi", "-i", "aevalsrc=0.32*sin(2*PI*(90*t-55*t*t))*exp(-12*t):s=48000:d=0.45"]
    cmd += ["-filter_complex", filter_graph, "-map", "[outv]", "-map", "[aout]",
            "-t", f"{DURATION:.6f}", "-frames:v", str(total_frames),
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
    source_selection_report["forced_progression_shift_count"] = forced_source_shift_count
    media_analysis = {
        "source_duration_seconds": source_duration,
        "source_width": int(source_video.get("width", 0)),
        "source_height": int(source_video.get("height", 0)),
        "scene_cut_count": len(scenes),
        "music_duration_seconds": music_duration,
        "preview_mode": PREVIEW_MODE,
        "music_shorter_than_edit": music_duration < DURATION,
        "music_loop_enabled": MUSIC_LOOP,
        "music_loop_crossfade_seconds": loop_graph["crossfade_seconds"],
        "music_loop_count": loop_graph["loop_count"],
        "context_window": context,
        "source_selection": source_selection_report,
        "context_caveat": "Temporal scene-cut-density proxy only; no semantic person identification in this build.",
    }
    beat_analysis = {
        "enabled": BEAT_SYNC,
        "candidate_count": len(beats),
        "source_candidate_count": len(raw_beats),
        "loop_expanded": len(beats) > len(raw_beats),
        "fallback": "even_pacing" if BEAT_SYNC and len(beats) < 3 else None,
        "method": BEAT_GRID_ANALYSIS["method"],
        "grid_method": BEAT_GRID_ANALYSIS["method"],
        "grid_confidence": BEAT_GRID_ANALYSIS["confidence"],
        "grid_period_seconds": BEAT_GRID_ANALYSIS["period_seconds"],
        "grid_phase_seconds": BEAT_GRID_ANALYSIS["phase_seconds"],
        "grid_candidate_count": BEAT_GRID_ANALYSIS["candidate_count"],
        "onset_candidate_count": BEAT_GRID_ANALYSIS["onset_candidate_count"],
        "drop_beat_time_seconds": drop_beat_time,
        "drop_beat_strength_proxy": DROP_BEAT_STRENGTH if drop_beat_time is not None else None,
        "drop_freeze_frames": drop_freeze_frames,
        "drop_freeze_duration_seconds": drop_freeze_duration,
    }
    reference_analysis = {
        "enabled": REFERENCE_PACING,
        "available": _has_usable_reference_profile(ref_profile),
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
    hook_proxy_threshold = expected_opening_cuts + max(2.0, expected_opening_cuts * 1.5)
    if opening_cut_count > hook_proxy_threshold:
        opening_activity_interpretation = "overdense_scene_changes"
    elif opening_cut_count < expected_opening_cuts / 2.0:
        opening_activity_interpretation = "sparse_scene_changes"
    else:
        opening_activity_interpretation = "moderate_scene_change_cadence"
    hook_analysis = {
        "window_seconds": hook_window,
        "opening_scene_change_count": opening_cut_count,
        "opening_activity_proxy": round(opening_activity_proxy, 4),
        "opening_activity_interpretation": opening_activity_interpretation,
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
        "visual_clarity": f"source pixel support ratio versus {WIDTH}x{HEIGHT} output (not a sharpness/subject-visibility model)",
        "hook_strength": "opening scene-change cadence proxy only; no semantic hook understanding",
        "motion_energy": "scene cuts per two seconds inside selected temporal context window",
        "drop_impact": "relative strongest bass-onset novelty proxy; not a true musical drop classifier",
    }
    render_critique = analyze_render_critique(final_video, actual)

    progress_event("render_critique", "completed", "Render Critic has measured black intervals, sample peak and encoded true peak.",
                   {"black_segment_count": len(render_critique.get("black_segments", [])),
                    "mean_volume_db": render_critique.get("mean_volume_db"),
                    "max_volume_db": render_critique.get("max_volume_db"),
                    "true_peak_dbfs": render_critique.get("true_peak_dbfs")})

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
        "source_chapter": context.get("source_chapter", {}),
        "character_lock": context.get("character_lock", {}),
        "render_critique": render_critique, "niche_metrics": niche_metrics,
        "niche_tags": ["phonk", "montagem", "vertical", "freeze"],
        "render_report": render_report,
    }, emit=print_agent_event, emit_progress=print_agent_event)
    agent_report["pre_render_review"] = pre_render_review
    agent_report["analysis_cache"] = list(ANALYSIS_CACHE_REPORT)
    agent_report["clip_selection"] = {
        "selected_clip_count": actual_motion_clip_count,
        "requested_clip_count": args.clip_count,
        "selection_mode": clip_selection_mode,
        "min_clips": MIN_CLIPS,
        "max_clips": MAX_CLIPS,
        "min_shot_seconds": MIN_SHOT_SECONDS,
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
        raise RuntimeError(f"Technical QA blocked export; previous final file was preserved. See {report_path}.")
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
        raise RuntimeError(f"Export Storage could not promote the verified render; see {report_path}.")
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
    if VARIANT_INDEX is None:
        artifacts = agent_report.setdefault("artifacts", {})
        artifacts["run_directory"] = OUTDIR
        artifacts["preview_mode"] = PREVIEW_MODE
        try:
            sheet_path = create_contact_sheet(FINAL, Path(OUTDIR) / "contact_sheet.png", DURATION)
            artifacts["contact_sheet"] = sheet_path
        except Exception as exc:
            artifacts["contact_sheet"] = None
            artifacts["contact_sheet_warning"] = str(exc)
            print(f"[warn] Contact sheet skipped: {exc}", flush=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(agent_report, handle, ensure_ascii=False, indent=2)
        publish_latest_run(OUTDIR)
        if not PREVIEW_MODE:
            compatibility = Path("output") / "final_phonk_20s.mp4"
            compatibility.parent.mkdir(parents=True, exist_ok=True)
            temporary_copy = compatibility.with_name(compatibility.name + ".part")
            shutil.copy2(FINAL, temporary_copy)
            os.replace(temporary_copy, compatibility)
            artifacts["compatibility_copy"] = str(compatibility)
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
        raise SystemExit(main() or 0)
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError, RuntimeError) as exc:
        progress_event("fatal_error", "error", str(exc))
        print(f"[ERROR] {exc}")
        print("Check FFmpeg/FFprobe availability, AI-upscaler/model paths, input files, and available storage.")
        sys.exit(1)
