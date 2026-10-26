import os
import re
import json
import random
import subprocess

VIDEO = "input/test_video.mp4"
MUSIC = "input/phonk.mp3"
REFERENCE = "input/reference.mp4"
OUTDIR = "output"
WORK = "output/work"
FINAL = "output/final_phonk_20s.mp4"

DURATION = 20.0
FPS = 60
SPEED = 1.1
CLIPS = 8
FREEZE = 0.7
CRF = 18

def run(cmd, capture=False):
    return subprocess.run(
        cmd, check=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else None,
        text=True
    )

def probe_duration(path):
    r = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ], capture=True)
    return float(r.stdout.strip())

def detect_scenes(path, duration):
    print("[1/5] Analyzing scene changes...")
    cmd = [
        "ffmpeg", "-hide_banner", "-i", path,
        "-vf", "select='gt(scene,0.22)',showinfo",
        "-an", "-f", "null", "-"
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    times = []
    for line in r.stderr.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = float(m.group(1))
            if 1 < t < duration - 3:
                times.append(t)
    return sorted(set(times))

def choose_centers(scenes, duration):
    # Spread selected moments across the source; prefer detected scene changes.
    usable_start = 0.5
    usable_end = max(usable_start + 1, duration - 3)
    targets = [
        usable_start + (usable_end - usable_start) * (i + 0.5) / CLIPS
        for i in range(CLIPS)
    ]
    centers = []
    for target in targets:
        nearby = [t for t in scenes if abs(t - target) < duration / 12]
        center = min(nearby, key=lambda t: abs(t - target)) if nearby else target
        centers.append(max(0.2, min(center, duration - 2.8)))
    return centers

def make_clip(index, center, source_duration):
    # Each clip is 2.4125s after 1.1x speed: 8 clips = 19.3s.
    output_duration = (DURATION - FREEZE) / CLIPS
    input_duration = output_duration * SPEED
    start = max(0, min(center - input_duration / 2, source_duration - input_duration))
    path = f"{WORK}/clip_{index:02d}.mp4"

    # Square foreground over blurred 9:16 background preserves more context
    # than filling the whole vertical frame by cropping a landscape source.
    vf = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=18:2[back];"
        "[fg]scale=1080:1080:force_original_aspect_ratio=increase,"
        "crop=1080:1080,hflip,"
        "eq=contrast=1.12:saturation=1.22:gamma=1.02,"
        "unsharp=5:5:0.65:3:3:0.0[front];"
        "[back][front]overlay=0:420,setsar=1,"
        f"fps={FPS},setpts=PTS/{SPEED},"
        f"trim=duration={output_duration:.4f},setpts=PTS-STARTPTS[v]"
    )

    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-t", f"{input_duration:.4f}",
        "-i", VIDEO,
        "-filter_complex", vf,
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", str(CRF), "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-threads", "2", path
    ])
    return path

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)

    for path in (VIDEO, MUSIC, REFERENCE):
        if not os.path.isfile(path):
            raise SystemExit(f"[ERROR] Missing file: {path}")

    video_duration = probe_duration(VIDEO)
    music_duration = probe_duration(MUSIC)
    print(f"Source video: {video_duration:.1f}s")
    print(f"Music: {music_duration:.1f}s")
    print("Target: 20 seconds, 9:16, 1080x1920")

    scenes = detect_scenes(VIDEO, video_duration)
    print(f"Detected scene-change points: {len(scenes)}")
    centers = choose_centers(scenes, video_duration)

    print("[2/5] Rendering selected clips with speed, mirror and enhancement...")
    clips = []
    for i, center in enumerate(centers):
        print(f"  Clip {i+1}/{CLIPS} at source time {center:.1f}s")
        clips.append(make_clip(i, center, video_duration))

    print("[3/5] Joining clips...")
    concat_file = f"{WORK}/concat.txt"
    with open(concat_file, "w") as f:
        for clip in clips:
            f.write("file '" + os.path.abspath(clip).replace("'", "'\\''") + "'\n")

    joined = f"{WORK}/joined.mp4"
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-c", "copy", joined
    ])

    print("[4/5] Adding Phonk music and final freeze moment...")
    # Hold the last frame for the final 0.7s; show a skull/title if font supports it.
    # Music is trimmed to 20s and faded gently at the end.
    vf = (
        "tpad=stop_mode=clone:stop_duration=0.8,"
        "drawtext=text='FREEZE':fontcolor=white:fontsize=78:"
        "borderw=5:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:"
        "enable='gte(t,19.3)',"
        "trim=duration=20,setsar=1"
    )

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", joined, "-i", MUSIC,
        "-vf", vf,
        "-map", "0:v:0", "-map", "1:a:0",
        "-af", "atrim=0:20,afade=t=out:st=19.2:d=0.8",
        "-t", "20",
        "-c:v", "libx264", "-preset", "veryfast",
        "-crf", str(CRF), "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-threads", "2", FINAL
    ]
    try:
        run(cmd)
    except subprocess.CalledProcessError:
        # Fallback without drawtext if the local FFmpeg lacks font support.
        print("[!] Text overlay failed; retrying freeze without text.")
        run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", joined, "-i", MUSIC,
            "-vf", "tpad=stop_mode=clone:stop_duration=0.8,trim=duration=20,setsar=1",
            "-map", "0:v:0", "-map", "1:a:0",
            "-af", "atrim=0:20,afade=t=out:st=19.2:d=0.8",
            "-t", "20", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", str(CRF), "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-threads", "2", FINAL
        ])

    print("[5/5] Verifying output...")
    final_duration = probe_duration(FINAL)
    print(f"[OK] Rendered file: {FINAL}")
    print(f"[OK] Actual duration: {final_duration:.2f}s")
    print("[NOTE] Scene-change selection is automatic, not semantic AI.")
    print("[NOTE] Current crop is centered square, not face-tracked.")
    print("[NOTE] Music is added; reference typing/SFX are not extracted automatically.")

if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        print(f"[ERROR] {e}")
        print("Check that FFmpeg/FFprobe work and all input files exist.")
