#!/usr/bin/env bash
set -euo pipefail
mkdir -p input output
cleanup() {
  rm -rf input output
}
trap cleanup EXIT
cat > params.json <<'JSON'
{
  "style": "phonk_montagem",
  "video_settings": {"resolution": "1080x1920", "fps": 24, "codec": "libx264", "crf": 26, "preset": "ultrafast"},
  "edit_settings": {"duration_seconds": 8, "speed": 1.1, "freeze_duration": 0.35, "edl_mode": "on", "min_clips": 6, "max_clips": 6, "reference_pacing": false, "mirror_enabled": false, "smart_crop": true},
  "audio_settings": {"beat_sync": false, "beat_flash": false, "bass_boost": false, "music_loop": true}
}
JSON
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "testsrc2=size=640x360:rate=24:duration=10" -an -c:v libx264 -pix_fmt yuv420p input/test_video.mp4
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "sine=frequency=70:sample_rate=44100:duration=9" -c:a libmp3lame input/phonk.mp3
python src/agent_director.py
python - <<'PY'
import json
import subprocess
from pathlib import Path

path = Path("output/final_phonk_20s.mp4")
report = json.loads(Path("output/agent_report.json").read_text(encoding="utf-8"))
assert report["status"] == "ready_for_human_review", report
assert report["results"]["settings_agent"]["status"] == "ok", report
assert report["results"]["planner"]["status"] == "ok", report
assert report["results"]["director"]["status"] == "ready_for_human_review", report
assert report["results"]["framing_agent"]["status"] == "ok", report
assert report["results"]["hook_analyst"]["status"] == "insufficient_evidence", report
assert report["results"]["inspector"]["status"] == "ok", report
assert report["results"]["render_critic"]["status"] in ("ok", "needs_review"), report
assert report["render_critique"]["measurement_errors"] == [], report["render_critique"]
assert isinstance(report["render_critique"]["mean_volume_db"], (int, float)), report["render_critique"]
assert isinstance(report["render_critique"]["max_volume_db"], (int, float)), report["render_critique"]
assert report["results"]["niche_analyst"]["status"] == "insufficient_evidence", report
assert report["results"]["export_storage"]["status"] == "ok", report
assert path.exists() and path.stat().st_size > 0
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
edl = json.loads(Path("output/edit_decision_list.json").read_text(encoding="utf-8"))
assert edl["version"] == 1
cursor = 0
for item in edl["video"]:
    assert item["start_f"] == cursor, (cursor, item)
    cursor += item["dur_f"]
assert cursor == edl["total_frames"] == 192, (cursor, edl["total_frames"])
assert edl["video"][-1]["type"] == "freeze"
assert edl["fps_num"] == 24
assert len(report["events"]) == 12
print("Render smoke test passed: exact frame count, continuous EDL, audio, full decode, render Critic, Director decision and atomic export.")
PY
