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
from pathlib import Path
report = json.loads(Path("output/agent_report.json").read_text(encoding="utf-8"))
assert report["status"] == "ready_for_human_review", report
assert report["results"]["inspector"]["status"] == "ok", report
assert report["results"]["niche_analyst"]["status"] == "insufficient_evidence", report
assert Path("output/final_phonk_20s.mp4").exists()
print("Render smoke test passed; niche metrics correctly reported as unavailable.")
PY
