import json
import math
import os
import re
import statistics
import struct
import subprocess
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
except ModuleNotFoundError:
    from heyaa.agents import run_agent_team, export_storage_agent

VIDEO = "input/test_video.mp4"
MUSIC = "input/phonk.mp3"
REFERENCE = "input/reference.mp4"
OUTDIR = "output"
WORK = "output/work"
FINAL = "output/final_phonk_20s.mp4"
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
SMART_CROP_ENABLED = None
MIN_CLIPS = None
MAX_CLIPS = None
MUSIC_LOOP = None
CODEC = None
CONFIG = None
DROP_FREEZE_DURATION = 0.25
DROP_BEAT_TIME = None
DROP_BEAT_STRENGTH = None


def load_settings():
    """Load and strictly validate params.json; unsupported values fail fast."""
    global DURATION, FPS, WIDTH, HEIGHT, CRF, PRESET, SPEED, FREEZE, EDIT_DURATION
    global BEAT_SYNC, BEAT_FLASH, BASS_BOOST, REFERENCE_PACING, MIRROR_ENABLED, SMART_CROP_ENABLED
    global MIN_CLIPS, MAX_CLIPS, MUSIC_LOOP, CODEC, CONFIG, DROP_FREEZE_DURATION
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
    for key in ("reference_pacing", "mirror_enabled", "smart_crop"):
        if not isinstance(edit.get(key), bool):
            raise ValueError(f"edit_settings.{key} must be an explicit boolean.")
    for key in ("beat_sync", "beat_flash", "bass_boost", "music_loop"):
        if not isinstance(audio.get(key), bool):
            raise ValueError(f"audio_settings.{key} must be an explicit boolean.")
    BEAT_SYNC, BEAT_FLASH = audio["beat_sync"], audio["beat_flash"]
    BASS_BOOST, MUSIC_LOOP = audio["bass_boost"], audio["music_loop"]
    REFERENCE_PACING = edit["reference_pacing"]
    MIRROR_ENABLED, SMART_CROP_ENABLED = edit["mirror_enabled"], edit["smart_crop"]
    if edit.get("edl_mode") != "on":
        raise ValueError("edit_settings.edl_mode must be 'on' for the integrated EDL renderer.")
    total_frames, freeze_frames = round(DURATION * FPS), round(FREEZE * FPS)
    if freeze_frames <= 0 or freeze_frames >= total_frames:
        raise ValueError("freeze_duration must occupy at least one frame and less than the full timeline.")
    FREEZE = freeze_frames / FPS
    DURATION = total_frames / FPS
    EDIT_DURATION = (total_frames - freeze_frames) / FPS
    CONFIG = config
    print(f"[settings] {WIDTH}x{HEIGHT}@{FPS} | {DURATION:.3f}s | speed={SPEED:.2f}x | final_freeze={FREEZE:.3f}s (minimum 1.7s) | drop_freeze={DROP_FREEZE_DURATION:.3f}s | mirror={MIRROR_ENABLED} | smart_crop={SMART_CROP_ENABLED} | music_loop={MUSIC_LOOP} | EDL=on")
    return config

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

def reference_cut_interval(reference_path):
    """Turn reference.mp4 cut rhythm into a rough pacing profile."""
    if not os.path.isfile(reference_path):
        print("[warn] reference.mp4 missing; using the default Phonk pacing.")
        return None
    try:
        ref_duration = duration_of(reference_path)
        cuts = detect_scenes(reference_path, ref_duration)
        gaps = [
            b - a for a, b in zip(cuts, cuts[1:])
            if 0.25 <= b - a <= 4.0
        ]
        if len(gaps) < 2:
            print("[warn] Reference has too few clear cuts; using default pacing.")
            return None
        interval = statistics.median(gaps)
        print(f"[analyze] Reference cut rhythm: median {interval:.2f}s.")
        return interval
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"[warn] Could not analyze reference.mp4: {exc}")
        return None


def choose_clip_count(reference_interval):
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


def make_boundaries(clip_count, beats):
    """Prefer real music transients for cut points, while keeping clips watchable."""
    boundaries = [0.0]
    if beats:
        for index in range(1, clip_count):
            target = EDIT_DURATION * index / clip_count
            nearby = [beat for beat in beats if abs(beat - target) <= 0.42]
            candidate = min(nearby, key=lambda beat: abs(beat - target)) if nearby else target
            min_gap = 0.88
            remaining = clip_count - index
            if candidate - boundaries[-1] < min_gap:
                candidate = target
            if EDIT_DURATION - candidate < remaining * min_gap:
                candidate = target
            boundaries.append(candidate)
    else:
        boundaries.extend(EDIT_DURATION * index / clip_count for index in range(1, clip_count))
    boundaries.append(EDIT_DURATION)

    lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
    if min(lengths) < 0.75 or max(lengths) > 3.3:
        boundaries = [EDIT_DURATION * index / clip_count for index in range(clip_count + 1)]
        lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
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

    # Smart crop is a center crop, not face/subject tracking.
    # EDL crop currently describes the full normalized source area; aspect-fit
    # and centering are renderer policy for the fixed 9:16 canvas.
    if SMART_CROP_ENABLED:
        vf = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            f"{'hflip,' if MIRROR_ENABLED else ''}"
            "eq=contrast=1.16:saturation=1.30:gamma=1.02,"
            "unsharp=5:5:0.72:3:3:0.0,setsar=1,"
            f"fps={FPS},setpts=PTS/{SPEED},fps={FPS},trim=end_frame={output_frames},setpts=PTS-STARTPTS[v]"
        )
    else:
        vf = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=20:2,eq=brightness=-0.08:saturation=0.78[back];"
            "[fg]scale=1188:1188:force_original_aspect_ratio=increase,"
            "crop=1080:1080:x='(iw-1080)/2+5*sin(t*10)':y='(ih-1080)/2+4*cos(t*8)'"
            f"{mirror},"
            "eq=contrast=1.16:saturation=1.30:gamma=1.02,"
            "unsharp=5:5:0.72:3:3:0.0[front];"
            "[back][front]overlay=0:420,setsar=1,"
            f"fps={FPS},setpts=PTS/{SPEED},fps={FPS},trim=end_frame={output_frames},setpts=PTS-STARTPTS[v]"
        )

    # Loop only when the selected range cannot supply the requested source time.
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if source_duration < input_duration + start:
        cmd += ["-stream_loop", "-1"]
    cmd += [
        "-ss", f"{start:.6f}", "-t", f"{input_duration:.6f}", "-i", VIDEO,
        "-filter_complex", vf, "-map", "[v]", "-an",
        "-c:v", CODEC, "-preset", PRESET, "-crf", str(CRF),
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-frames:v", str(output_frames),
        "-threads", "2", path
    ]
    run(cmd)
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


def main(argv=None):
    global VIDEO, MUSIC, REFERENCE, EDIT_DURATION, DURATION, FREEZE
    args = parse_media_source_args(argv)
    VIDEO, MUSIC, REFERENCE = prepare_media_sources(
        video_url=args.video_url,
        music_url=args.music_url,
        reference_url=args.reference_url,
        video_path=VIDEO,
        music_path=MUSIC,
        reference_path=REFERENCE,
    )
    load_settings()
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

    scenes = detect_scenes(VIDEO, source_duration)
    raw_beats = detect_music_beats(MUSIC, EDIT_DURATION) if BEAT_SYNC else []
    beats = extend_looped_beats(raw_beats, music_duration, EDIT_DURATION, MUSIC_LOOP)
    ref_interval = reference_cut_interval(REFERENCE) if REFERENCE_PACING else None
    clip_count = choose_clip_count(ref_interval)
    boundaries_seconds = make_boundaries(clip_count, beats)
    total_frames, freeze_frames = round(DURATION * FPS), round(FREEZE * FPS)
    edit_frames = total_frames - freeze_frames
    frame_boundaries = [round(value * FPS) for value in boundaries_seconds]
    frame_boundaries[0], frame_boundaries[-1] = 0, edit_frames
    frame_boundaries = sorted(set(frame_boundaries))
    if len(frame_boundaries) != clip_count + 1:
        raise RuntimeError("Frame quantization changed the planned clip count; regenerate the edit plan.")
    if len(frame_boundaries) < 2 or frame_boundaries[0] != 0 or frame_boundaries[-1] != edit_frames:
        raise RuntimeError("Could not create contiguous integer-frame EDL boundaries.")
    edl_video = []
    for start_f, end_f in zip(frame_boundaries, frame_boundaries[1:]):
        dur_f = end_f - start_f
        if dur_f <= 0:
            raise RuntimeError("EDL contains a zero-length clip after frame quantization.")
        timeline_center = (start_f + dur_f / 2) / FPS
        source_target = timeline_center / EDIT_DURATION * source_duration
        source_center = choose_source_center(source_target, scenes, source_duration)
        source_dur_f = max(1, round(dur_f * SPEED))
        source_start_seconds = max(0.0, min(
            source_center - (source_dur_f / FPS) / 2,
            max(0.0, source_duration - source_dur_f / FPS)
        ))
        edl_video.append({
            "type": "clip", "source": VIDEO,
            "source_start_f": round(source_start_seconds * FPS),
            "source_dur_f": source_dur_f,
            "start_f": start_f, "dur_f": dur_f, "speed": SPEED,
            "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
        })
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
    validate_edl(edl)
    # Fail before expensive clip rendering if the contract contains features the
    # current FFmpeg renderer explicitly does not implement.
    if edl["video"][-1]["type"] != "freeze" or sum(1 for item in edl["video"] if item["type"] == "freeze") != 1:
        raise RuntimeError("EDL must contain exactly one freeze segment at the end.")
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
    print(f"[edl] Validated {len(edl_video) - 1} clips + freeze; {total_frames} frames, no gaps.")

    print("[render 1/4] Building clips from validated EDL...")
    clips = []
    for index, item in enumerate(edl_video[:-1]):
        length = item["dur_f"] / FPS
        center = item["source_start_f"] / FPS + (item["source_dur_f"] / FPS) / 2
        print(f"  EDL clip {index + 1}/{len(edl_video) - 1}: source {center:.2f}s, output {length:.3f}s [{item['start_f']}..{item['start_f'] + item['dur_f']})")
        clips.append(make_clip(index, item, source_duration))

    print("[render 2/4] Joining clips...")
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

    print("[render 3/4] Adding bass-hit flashes, cinematic skull freeze, and Phonk audio...")
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
        "[2:v]scale=300:-1[skull];"
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
        audio_filters.extend(["bass=g=3:f=90:w=0.5", "alimiter=limit=0.95"])
    if fade_in_seconds > 0:
        audio_filters.append(f"afade=t=in:st=0:d={fade_in_seconds:.6f}")
    audio_filters.extend([f"apad=whole_dur={DURATION:.6f}", f"atrim=duration={DURATION:.6f}"])
    if fade_out_seconds > 0:
        fade_start = max(0.0, DURATION - fade_out_seconds)
        audio_filters.append(f"afade=t=out:st={fade_start:.6f}:d={fade_out_seconds:.6f}")
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

    print("[render 4/4] Verifying the rendered file...")
    actual, video_codec, audio_codec, render_report = verify_output(final_video)
    source_streams = probe(VIDEO).get("streams", [])
    source_video = next((stream for stream in source_streams if stream.get("codec_type") == "video"), {})
    media_analysis = {
        "source_duration_seconds": source_duration,
        "source_width": int(source_video.get("width", 0)),
        "source_height": int(source_video.get("height", 0)),
        "scene_cut_count": len(scenes),
        "music_duration_seconds": music_duration,
    }
    beat_analysis = {
        "enabled": BEAT_SYNC,
        "candidate_count": len(beats),
        "source_candidate_count": len(raw_beats),
        "loop_expanded": len(beats) > len(raw_beats),
        "fallback": "even_pacing" if BEAT_SYNC and len(beats) < 3 else None,
        "method": "bass-lowpass-rms-novelty-autocorrelation-heuristic" if BEAT_SYNC else "disabled",
    }
    reference_analysis = {
        "enabled": REFERENCE_PACING,
        "available": os.path.isfile(REFERENCE) and ref_interval is not None,
        "median_cut_interval_seconds": ref_interval,
        "source": REFERENCE if os.path.isfile(REFERENCE) else None,
    }
    hook_window = min(2.0, actual)
    final_scenes = detect_scenes(final_video, actual, scan_duration=hook_window)
    hook_analysis = {
        "window_seconds": hook_window,
        "opening_scene_change_count": sum(1 for time in final_scenes if 0.0 < time <= hook_window),
        "measurement": "ffmpeg_scene_change",
    }
    cut_times = [item["start_f"] / FPS for item in edl_video[:-1] if item["start_f"] > 0]
    niche_metrics = {}
    if cut_times and beats:
        tolerance = 0.12
        alignment = [max(0.0, 1.0 - min(abs(cut - beat) for beat in beats) / tolerance)
                     for cut in cut_times]
        niche_metrics["beat_alignment"] = round(sum(alignment) / len(alignment), 4)
    render_critique = analyze_render_critique(final_video, actual)
    agent_report = run_agent_team({
        "settings": CONFIG, "edl": edl,
        "media_analysis": media_analysis, "beat_analysis": beat_analysis,
        "reference_analysis": reference_analysis, "hook_analysis": hook_analysis,
        "render_critique": render_critique, "niche_metrics": niche_metrics, "niche_tags": ["phonk", "montagem", "vertical", "freeze"],
        "render_report": render_report,
    })
    for event in agent_report["events"]:
        print(f"[agent:{event['agent']}] {event['status']}: {event['summary']}")
    report_path = os.path.join(OUTDIR, "agent_report.json")
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
    print(f"[agents] Status: {agent_report['status']} | report: {report_path}")
    print(f"[agents] Niche result: {agent_report['results']['niche_analyst']['status']} (no unsupported virality score)")
    print("[NOTE] Reference mode learns rough cut pacing; it does not copy copyrighted frames/effects.")
    print("[NOTE] Standard FFmpeg scaling only; no AI upscaling or new source detail is generated.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        print("Check FFmpeg/FFprobe availability, input files, and available storage.")
