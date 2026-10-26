import json
import math
import os
import re
import statistics
import struct
import subprocess
from pathlib import Path

VIDEO = "input/test_video.mp4"
MUSIC = "input/phonk.mp3"
REFERENCE = "input/reference.mp4"
OUTDIR = "output"
WORK = "output/work"
FINAL = "output/final_phonk_20s.mp4"

DURATION = 20.0
FPS = 60
SPEED = 1.10
FREEZE = 0.70
EDIT_DURATION = DURATION - FREEZE
WIDTH, HEIGHT = 1080, 1920
CRF = 18
PRESET = "veryfast"


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


def detect_music_beats(path, limit):
    """Estimate beat transients from low-frequency PCM energy using stdlib only."""
    print("[analyze] Phonk beat/bass transients...")
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
    if len(energies) < 5:
        return []

    ordered = sorted(energies)
    median = ordered[len(ordered) // 2]
    peak_value = max(energies)
    threshold = median + (peak_value - median) * 0.24
    candidates = []
    for i in range(2, len(energies) - 2):
        value = energies[i]
        if value < threshold:
            continue
        if value >= max(energies[i - 2:i]) and value >= max(energies[i + 1:i + 3]):
            timestamp = i * 0.02
            if 0.08 <= timestamp < min(limit, len(energies) * 0.02):
                candidates.append((value, timestamp))

    # Keep the strongest transient in each short interval to avoid double hits.
    chosen = []
    for value, timestamp in sorted(candidates, reverse=True):
        if all(abs(timestamp - existing) >= 0.24 for existing in chosen):
            chosen.append(timestamp)
    beats = sorted(t for t in chosen if t < limit)
    if len(beats) < 3:
        print("[warn] Few clear bass hits found; edit timing will use fallback beats.")
        return []
    print(f"[analyze] Detected {len(beats)} likely beat hits in the edit window.")
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
        return 8
    return max(8, min(16, round(EDIT_DURATION / max(0.75, min(2.4, reference_interval)))))


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
    mirror = ",hflip" if index % 2 == 1 else ""

    # A blurred 9:16 canvas retains a vertical composition; the foreground has
    # a controlled zoom and restrained shake instead of a crude full-frame crop.
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
    beats = detect_music_beats(MUSIC, EDIT_DURATION)
    ref_interval = reference_cut_interval(REFERENCE)
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

    print("[render 3/4] Adding bass-hit flashes, skull freeze, and Phonk audio...")
    final_video = f"{WORK}/final_render.mp4"
    flash_filter = make_flash_filter(beats)
    base_filter = (
        f"tpad=stop_mode=clone:stop_duration={FREEZE:.3f},"
        f"eq=contrast=1.32:saturation=0:enable='gte(t,{EDIT_DURATION:.3f})'"
    )
    if flash_filter:
        base_filter += "," + flash_filter
    base_filter += (
        f",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.78:t=fill:"
        f"enable='between(t,{EDIT_DURATION - 0.10:.3f},{EDIT_DURATION - 0.055:.3f})'"
    )
    skull_filter = (
        base_filter
        + ",drawtext=text='☠':fontcolor=white:fontsize=150:borderw=7:"
        "bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:"
        f"enable='gte(t,{EDIT_DURATION:.3f})',"
        f"trim=duration={DURATION:.3f},setsar=1"
    )
    audio_filter = f"atrim=duration={DURATION:.3f},afade=t=out:st={DURATION - 0.8:.3f}:d=0.8"

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", joined, "-stream_loop", "-1", "-i", MUSIC,
        "-vf", skull_filter, "-map", "0:v:0", "-map", "1:a:0",
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
        fallback_filter = (
            base_filter
            + ",drawtext=text='FREEZE':fontcolor=white:fontsize=88:borderw=6:"
            "bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:"
            f"enable='gte(t,{EDIT_DURATION:.3f})',"
            f"trim=duration={DURATION:.3f},setsar=1"
        )
        cmd[cmd.index("-vf") + 1] = fallback_filter
        run(cmd)

    print("[render 4/4] Verifying the rendered file...")
    actual, video_codec, audio_codec = verify_output(final_video)
    os.replace(final_video, FINAL)
    print(f"[OK] Final video: {FINAL}")
    print(f"[OK] Duration: {actual:.2f}s | Resolution: {WIDTH}x{HEIGHT} | FPS: {FPS}")
    print(f"[OK] Video codec: {video_codec} | Audio codec: {audio_codec}")
    print("[NOTE] Reference mode learns rough cut pacing; it does not copy copyrighted frames/effects.")
    print("[NOTE] Upscaling improves presentation but cannot restore detail absent from the source.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        print("Check FFmpeg/FFprobe availability, input files, and available storage.")
