import json
import math
import os
import re
import statistics
import struct
import subprocess
from pathlib import Path

try:
    from src.heyaa.agents import run_agent_team
except ModuleNotFoundError:
    from heyaa.agents import run_agent_team

VIDEO = "input/test_video.mp4"
MUSIC = "input/phonk.mp3"
REFERENCE = "input/reference.mp4"
OUTDIR = "output"
WORK = "output/work"
FINAL = "output/final_phonk_20s.mp4"
SKULL_ASSET = str(Path(__file__).parent / "heyaa" / "assets" / "skull_freeze.svg")

DURATION = 20.0
FPS = 60
SPEED = 1.10
FREEZE = 0.70
EDIT_DURATION = DURATION - FREEZE
WIDTH, HEIGHT = 1080, 1920
CRF = 18
PRESET = "veryfast"
BEAT_SYNC = True
BEAT_FLASH = True
BASS_BOOST = True
REFERENCE_PACING = True
MIRROR_ENABLED = True
SMART_CROP_ENABLED = True
MIN_CLIPS = 8
MAX_CLIPS = 16


def load_settings():
    """Load optional edit controls from params.json without requiring extra packages."""
    global DURATION, FPS, WIDTH, HEIGHT, CRF, PRESET, SPEED, FREEZE
    global BEAT_SYNC, BEAT_FLASH, BASS_BOOST, REFERENCE_PACING, MIRROR_ENABLED, SMART_CROP_ENABLED, MIN_CLIPS, MAX_CLIPS
    path = "params.json"
    if not os.path.isfile(path):
        print("[settings] params.json not found; using safe defaults.")
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        video = config.get("video_settings", {})
        audio = config.get("audio_settings", {})
        edit = config.get("edit_settings", {})
        resolution = str(video.get("resolution", "1080x1920")).lower().split("x")
        if len(resolution) == 2:
            width, height = int(resolution[0]), int(resolution[1])
            # This renderer's current layout is designed specifically for 9:16.
            if width == 1080 and height == 1920:
                WIDTH, HEIGHT = width, height
        FPS = max(24, min(60, int(video.get("fps", FPS))))
        CRF = max(16, min(26, int(video.get("crf", CRF))))
        PRESET = str(video.get("preset", PRESET))
        DURATION = max(8.0, min(60.0, float(edit.get("duration_seconds", DURATION))))
        FREEZE = max(0.35, min(1.2, float(edit.get("freeze_seconds", FREEZE))))
        SPEED = max(1.0, min(1.35, float(edit.get("speed", SPEED))))
        MIN_CLIPS = max(6, min(12, int(edit.get("min_clips", MIN_CLIPS))))
        MAX_CLIPS = max(MIN_CLIPS, min(18, int(edit.get("max_clips", MAX_CLIPS))))
        BEAT_SYNC = bool(audio.get("beat_sync", BEAT_SYNC))
        BEAT_FLASH = bool(audio.get("beat_flash", BEAT_FLASH))
        BASS_BOOST = bool(audio.get("bass_boost", BASS_BOOST))
        REFERENCE_PACING = bool(edit.get("reference_pacing", REFERENCE_PACING))
        MIRROR_ENABLED = bool(edit.get("mirror_enabled", MIRROR_ENABLED))
        SMART_CROP_ENABLED = bool(edit.get("smart_crop", SMART_CROP_ENABLED))
        print(f"[settings] Style={config.get('style', 'phonk_montagem')} | {WIDTH}x{HEIGHT}@{FPS} | {DURATION:.1f}s | speed={SPEED:.2f}x | mirror={MIRROR_ENABLED} | smart_crop={SMART_CROP_ENABLED}")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"[warn] Invalid params.json ({exc}); using safe defaults.")


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


def detect_scenes(path, duration):
    """Use FFmpeg scene-change scores as an inexpensive cut detector."""
    print(f"[analyze] Scene changes: {Path(path).name}")
    cmd = [
        "ffmpeg", "-hide_banner", "-i", path,
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


def _estimate_period_frames(envelope, min_lag=25, max_lag=100):
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


def detect_music_beats(path, limit):
    """Estimate beat candidates from bass transients plus an autocorrelation tempo prior.

    This remains a lightweight heuristic, not a downbeat detector. It combines
    local onset novelty with periodicity so repeated loud bass noise is less
    likely to be mistaken for a sequence of unrelated beats.
    """
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


def make_clip(index, center, output_duration, source_duration):
    input_duration = output_duration * SPEED
    start = max(0.0, min(center - input_duration / 2.0, max(0.0, source_duration - input_duration)))
    path = f"{WORK}/clip_{index:02d}.mp4"
    # Horizontal mirror is an explicit transform, independent of visual effects.
    mirror = ",hflip" if MIRROR_ENABLED else ""

    # Smart crop means full-frame 9:16 center crop; it is not face tracking.
    # The legacy blurred-background layout remains available when disabled.
    if SMART_CROP_ENABLED:
        vf = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            f"{'hflip,' if MIRROR_ENABLED else ''}"
            "eq=contrast=1.16:saturation=1.30:gamma=1.02,"
            "unsharp=5:5:0.72:3:3:0.0,setsar=1,"
            f"fps={FPS},setpts=PTS/{SPEED},"
            f"trim=duration={output_duration:.5f},setpts=PTS-STARTPTS[v]"
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
            f"fps={FPS},setpts=PTS/{SPEED},"
            f"trim=duration={output_duration:.5f},setpts=PTS-STARTPTS[v]"
        )

    # Loop only for unusually short source videos so every segment reaches its duration.
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if source_duration < input_duration + start:
        cmd += ["-stream_loop", "-1"]
    cmd += [
        "-ss", f"{start:.4f}", "-t", f"{input_duration:.5f}", "-i", VIDEO,
        "-filter_complex", vf, "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", str(CRF),
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-threads", "2", path
    ]
    run(cmd)
    return path


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
    info = probe(path)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise RuntimeError("Final file has no video stream.")
    if audio is None:
        raise RuntimeError("Final file has no audio stream.")
    if int(video.get("width", 0)) != WIDTH or int(video.get("height", 0)) != HEIGHT:
        raise RuntimeError(
            f"Wrong output resolution: {video.get('width')}x{video.get('height')}"
        )
    actual_duration = float(info["format"]["duration"])
    if abs(actual_duration - DURATION) > 0.30:
        raise RuntimeError(f"Output duration is {actual_duration:.2f}s, expected {DURATION:.2f}s.")
    return actual_duration, video.get("codec_name", "unknown"), audio.get("codec_name", "unknown")


def main():
    load_settings()
    global EDIT_DURATION
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
    beats = detect_music_beats(MUSIC, EDIT_DURATION) if BEAT_SYNC else []
    ref_interval = reference_cut_interval(REFERENCE) if REFERENCE_PACING else None
    clip_count = choose_clip_count(ref_interval)
    boundaries = make_boundaries(clip_count, beats)

    print("[render 1/4] Building clips with vertical framing and enhancement...")
    clips = []
    for index, (left, right) in enumerate(zip(boundaries, boundaries[1:])):
        timeline_center = (left + right) / 2.0
        source_target = timeline_center / EDIT_DURATION * source_duration
        center = choose_source_center(source_target, scenes, source_duration)
        length = right - left
        print(f"  Clip {index + 1}/{clip_count}: source {center:.2f}s, output {length:.2f}s")
        clips.append(make_clip(index, center, length, source_duration))

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
        f"tpad=stop_mode=clone:stop_duration={FREEZE:.3f},"
        f"eq=contrast=1.32:saturation=0:enable='gte(t,{EDIT_DURATION:.3f})'"
    )
    if flash_filter:
        base_chain += "," + flash_filter
    base_chain += (
        f",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.78:t=fill:"
        f"enable='between(t,{EDIT_DURATION - 0.10:.3f},{EDIT_DURATION - 0.055:.3f})'"
    )
    impact_chain = (
        f"trim=start={EDIT_DURATION:.5f}:duration={FREEZE:.5f},"
        "setpts=PTS-STARTPTS,"
        "scale=1188:2112:flags=lanczos,"
        "crop=1080:1920:"
        "x='(iw-ow)/2+18*sin(t*70)':"
        "y='(ih-oh)/2+18*cos(t*57)',"
        "eq=contrast=1.48:saturation=0:brightness=0.015,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=white@0.55:t=fill:"
        "enable='lt(t,0.055)',"
        f"setpts=PTS+{EDIT_DURATION:.5f}/TB"
    )
    filter_graph = (
        f"[0:v]{base_chain},split[base][impact_src];"
        "[base]setsar=1[baseout];"
        f"[impact_src]{impact_chain}[impact_raw];"
        "[2:v]scale=300:-1[skull];"
        f"[impact_raw][skull]overlay=(W-w)/2:(H-h)/2:enable='gte(t,{EDIT_DURATION:.5f})'[impact];"
        f"[baseout][impact]overlay=0:0:enable='gte(t,{EDIT_DURATION:.5f})',"
        f"trim=duration={DURATION:.3f},setsar=1[outv]"
    )
    bass_filter = "bass=g=3:f=90:w=0.5,alimiter=limit=0.95," if BASS_BOOST else ""
    audio_filter = f"{bass_filter}atrim=duration={DURATION:.3f},afade=t=out:st={DURATION - 0.8:.3f}:d=0.8"

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", joined, "-stream_loop", "-1", "-i", MUSIC,
        "-filter_complex", filter_graph, "-map", "[outv]", "-map", "1:a:0",
        "-af", audio_filter, "-t", f"{DURATION:.3f}",
        "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-threads", "2", final_video
    ]
    try:
        run(cmd)
    except subprocess.CalledProcessError:
        print("[warn] Skull glyph/font unavailable; retrying with FREEZE text.")
        fallback_graph = filter_graph.replace(
            "drawtext=text='☠':fontcolor=white:fontsize=170:borderw=8:"
            "bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2",
            "drawtext=text='FREEZE':fontcolor=white:fontsize=88:borderw=6:"
            "bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2"
        )
        cmd[cmd.index("-filter_complex") + 1] = fallback_graph
        run(cmd)

    print("[render 4/4] Verifying the rendered file...")
    actual, video_codec, audio_codec = verify_output(final_video)
    os.replace(final_video, FINAL)
    print(f"[OK] Final video: {FINAL}")
    print(f"[OK] Duration: {actual:.2f}s | Resolution: {WIDTH}x{HEIGHT} | FPS: {FPS}")
    print(f"[OK] Video codec: {video_codec} | Audio codec: {audio_codec}")
    settings = {"resolution": f"{WIDTH}x{HEIGHT}", "speed": SPEED, "smart_crop": SMART_CROP_ENABLED}
    render_report = {
        "width": WIDTH, "height": HEIGHT, "duration_seconds": actual, "expected_duration_seconds": DURATION,
        "has_audio": True, "video_codec": video_codec, "audio_codec": audio_codec,
        "file": FINAL,
    }
    agent_report = run_agent_team({
        "settings": settings, "niche_metrics": {}, "niche_tags": ["phonk", "montagem"],
        "render_report": render_report,
    })
    report_path = os.path.join(OUTDIR, "agent_report.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(agent_report, handle, ensure_ascii=False, indent=2)
    print(f"[agents] Status: {agent_report['status']} | report: {report_path}")
    if agent_report["status"] == "blocked":
        raise RuntimeError("Agent Inspector blocked this render; see output/agent_report.json.")
    print("[NOTE] Reference mode learns rough cut pacing; it does not copy copyrighted frames/effects.")
    print("[NOTE] Upscaling improves presentation but cannot restore detail absent from the source.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        print("Check FFmpeg/FFprobe availability, input files, and available storage.")
