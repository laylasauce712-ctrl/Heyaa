#!/usr/bin/env bash
set -euo pipefail
# This smoke test temporarily replaces the project settings with a tiny fixture.
# Preserve and restore the user's real params.json even if the render/test fails.
PARAMS_BACKUP="$(mktemp)"
cp params.json "$PARAMS_BACKUP"
mkdir -p input output
cleanup() {
  rm -rf input output
  cp "$PARAMS_BACKUP" params.json
  rm -f "$PARAMS_BACKUP"
}
trap cleanup EXIT
cat > params.json <<'JSON'
{
  "style": "phonk_montagem",
  "video_settings": {"resolution": "1080x1920", "fps": 24, "codec": "libx264", "crf": 26, "preset": "ultrafast"},
  "edit_settings": {"duration_seconds": 8, "speed": 1.1, "freeze_duration": 2.0, "drop_freeze_duration": 0.25, "edl_mode": "on", "min_clips": 6, "max_clips": 6, "reference_pacing": false, "mirror_enabled": false, "layout_mode": "blur_fit"},
  "audio_settings": {"beat_sync": false, "beat_flash": false, "bass_boost": false, "music_loop": true}
}
JSON
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "testsrc2=size=640x360:rate=24:duration=10" -an -c:v libx264 -pix_fmt yuv420p input/test_video.mp4
# Deliberately hot input: the final output limiter must keep the export below clipping.
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "sine=frequency=70:sample_rate=44100:duration=2.5" -af "volume=20dB" -c:a libmp3lame input/phonk.mp3
# Exercise reference-audio extraction independently from the renderer's local-music path.
ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "testsrc2=size=640x360:rate=24:duration=4" \
  -f lavfi -i "sine=frequency=440:sample_rate=44100:duration=4" \
  -map 0:v:0 -map 1:a:0 -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac input/reference.mp4
python - <<'PY'
from pathlib import Path
from src import agent_director
from src.heyaa.media_sources import extract_reference_audio, parse_media_source_args, validate_media_file

args = parse_media_source_args([])
assert args.variants == 3, args
assert parse_media_source_args(["--variants", "1"]).variants == 1
music = extract_reference_audio("input/reference.mp4", "input/reference-extracted.mp3")
assert music == Path("input/reference-extracted.mp3") and music.is_file()
validate_media_file(music, "music")
profile = {
    "duration_seconds": 5.0,
    "shot_intervals_seconds": [1.0, 1.0, 1.0, 1.0],
    "cut_timestamps_seconds": [1.0, 2.0, 3.0, 4.0],
}
boundaries = agent_director._reference_boundaries(5, 5.0, profile)
assert boundaries == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0], boundaries
assert agent_director.REFERENCE_CUT_TIMESTAMPS_USED is True
print("Reference soundtrack extraction, three-variant defaults and timestamp mapping passed.")
PY
# Exercise the exact subject-aware 9:16 crop expression used when the optional
# HOG tracker supplies a normalized center; no OpenCV/person model is needed here.
ffmpeg -hide_banner -loglevel error -y -i input/test_video.mp4 \
  -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:x='max(0,min(iw-ow,0.65000*iw-ow/2))':y='max(0,min(ih-oh,0.55000*ih-oh/2))',setsar=1" \
  -frames:v 1 output/subject_crop_smoke.png
test -s output/subject_crop_smoke.png
python src/agent_director.py --variants 1

# Synthetic pixel-statistics fixture: the transparent skull must alter the freeze's
# otherwise uniform background, not just exist as a file or metadata flag.
ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "color=c=gray:s=270x480:r=24:d=0.25" \
  -loop 1 -framerate 24 -i src/heyaa/assets/skull_freeze.svg \
  -filter_complex "[1:v]scale=w='if(lt(n,4),105*(0.62+0.38*n/4),105)':h=-1:eval=frame[skull];[0:v][skull]overlay=(W-w)/2:(H-h)/2:shortest=1,format=rgb24[out]" \
  -map "[out]" -frames:v 6 -f rawvideo output/skull-overlay.rgb
python - <<'PY'
from pathlib import Path
raw = Path("output/skull-overlay.rgb").read_bytes()
width, height, channels = 270, 480, 3
frame_bytes = width * height * channels
assert len(raw) >= frame_bytes, len(raw)
frame = raw[:frame_bytes]
# Sample the expected centered skull region and a corner that should stay gray.
region = []
for y in range(190, 290):
    for x in range(85, 185):
        i = (y * width + x) * channels
        region.extend(frame[i:i + 3])
center_mean = sum(region) / len(region)
corner_i = (20 * width + 20) * channels
corner = raw[corner_i:corner_i + 3]
corner_mean = sum(corner) / len(corner)
changed = sum(1 for i in range(0, len(region), 3)
              if max(region[i:i + 3]) - min(region[i:i + 3]) > 12 or abs(sum(region[i:i + 3]) / 3 - corner_mean) > 20)
assert changed > 500, {"changed_center_pixels": changed, "center_mean": center_mean, "background_mean": corner_mean}
print(f"Ending skull alpha overlay pixel test passed: {changed} visibly changed center pixels.")
PY
python - <<'PY'
import json
import subprocess
from pathlib import Path

path = Path("output/latest/final_phonk_20s.mp4")
report = json.loads(Path("output/latest/agent_report.json").read_text(encoding="utf-8"))
assert report["status"] == "ready_for_human_review", report
assert report["results"]["settings_agent"]["status"] == "ok", report
assert report["results"]["planner"]["status"] == "ok", report
assert report["results"]["director"]["status"] == "ready_for_human_review", report
assert report["results"]["framing_agent"]["status"] == "ok", report
assert report["results"]["hook_analyst"]["status"] == "needs_review", report
assert report["results"]["inspector"]["status"] == "ok", report
assert report["results"]["render_critic"]["status"] in ("ok", "needs_review"), report
assert report["render_critique"]["measurement_errors"] == [], report["render_critique"]
assert isinstance(report["render_critique"]["mean_volume_db"], (int, float)), report["render_critique"]
assert isinstance(report["render_critique"]["max_volume_db"], (int, float)), report["render_critique"]
assert report["render_critique"]["max_volume_db"] <= -0.5, report["render_critique"]
assert isinstance(report["render_critique"]["true_peak_dbfs"], (int, float)), report["render_critique"]
assert report["render_critique"]["true_peak_dbfs"] <= -0.5, report["render_critique"]
assert report["results"]["niche_analyst"]["status"] == "insufficient_evidence", report
assert report["results"]["export_storage"]["status"] == "ok", report
assert path.exists() and path.stat().st_size > 0
assert Path("output/latest/contact_sheet.png").is_file(), "Contact sheet was not generated"
assert Path("output/latest").resolve().parent.name == "runs", Path("output/latest").resolve()
probe = json.loads(subprocess.check_output([
    "ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)
], text=True))
video = next(s for s in probe["streams"] if s["codec_type"] == "video")
audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
assert (video["width"], video["height"]) == (1080, 1920), video
assert int(video["nb_read_frames"]) == 192, video
assert video["avg_frame_rate"] in ("24/1", "24/1"), video
assert abs(float(probe["format"]["duration"]) - 8.0) <= (1 / 24 + 0.005)
assert audio["codec_type"] == "audio"
edl = json.loads(Path("output/latest/edit_decision_list.json").read_text(encoding="utf-8"))
assert edl["version"] == 1
cursor = 0
for item in edl["video"]:
    assert item["start_f"] == cursor, (cursor, item)
    cursor += item["dur_f"]
assert cursor == edl["total_frames"] == 192, (cursor, edl["total_frames"])
assert edl["video"][-1]["type"] == "freeze"
assert edl["video"][-1]["dur_f"] == round(2.0 * edl["fps_num"] / edl["fps_den"])
assert edl["fps_num"] == 24
assert len(report["events"]) == 14
print("Render smoke test passed: exact frame count, continuous EDL, audio, full decode, render Critic, Director decision and atomic export.")
PY

# A rejected render invocation must propagate a non-zero process exit code.
set +e
python3 src/agent_director.py --variants 1 --clip-count 99 > output/blocked-render.log 2>&1
blocked_status=$?
set -e
test "$blocked_status" -ne 0
grep -q "outside params.json bounds" output/blocked-render.log
echo "Blocked-render exit-code test passed (exit=$blocked_status)."