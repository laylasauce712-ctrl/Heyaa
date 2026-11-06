#!/usr/bin/env bash
# Create three distinct 20-second edits using the soundtrack from input/reference.mp4.
# Run from any directory: bash scripts/export_reference_audio_batch.sh
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${HEYAA_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON="$(command -v python3 || true)"
  fi
fi
[[ -n "$PYTHON" && -x "$PYTHON" ]] || {
  echo "[export] ERROR: Python 3 was not found. Create .venv or set HEYAA_PYTHON." >&2
  exit 1
}

for required in ffmpeg ffprobe; do
  command -v "$required" >/dev/null 2>&1 || {
    echo "[export] ERROR: $required is required on PATH." >&2
    exit 1
  }
done

VIDEO_PATH="${HEYAA_VIDEO_PATH:-input/test_video.mp4}"
REFERENCE_PATH="${HEYAA_REFERENCE_PATH:-input/reference.mp4}"
AUDIO_PATH="${HEYAA_REFERENCE_AUDIO_PATH:-input/reference_audio.mp3}"
EDIT_COUNT="${HEYAA_EDIT_COUNT:-3}"
BASE_PROFILE="${HEYAA_EXPORT_BASE_PROFILE:-}"

if [[ ! "$EDIT_COUNT" =~ ^[1-5]$ ]]; then
  echo "[export] ERROR: HEYAA_EDIT_COUNT must be an integer from 1 to 5." >&2
  exit 1
fi
[[ -s "$VIDEO_PATH" ]] || {
  echo "[export] ERROR: source footage is missing or empty: $VIDEO_PATH" >&2
  exit 1
}
[[ -s "$REFERENCE_PATH" ]] || {
  echo "[export] ERROR: reference video is missing or empty: $REFERENCE_PATH" >&2
  exit 1
}

if [[ -z "$BASE_PROFILE" ]]; then
  if [[ -s "$ROOT/params.local.json" ]]; then
    BASE_PROFILE="$ROOT/params.local.json"
  else
    BASE_PROFILE="$ROOT/params.json"
  fi
fi
[[ -s "$BASE_PROFILE" ]] || {
  echo "[export] ERROR: settings profile is missing: $BASE_PROFILE" >&2
  exit 1
}

echo "[export] Validating source and reference with ffprobe JSON output..."
"$PYTHON" - "$VIDEO_PATH" "$REFERENCE_PATH" <<'PY'
import json
import shutil
import subprocess
import sys
from pathlib import Path

ffprobe = shutil.which("ffprobe")
if not ffprobe:
    raise SystemExit("ffprobe is not on PATH")

def inspect(path, label, required_streams):
    media = Path(path)
    if not media.is_file() or media.stat().st_size <= 0:
        raise SystemExit(f"{label} is missing or empty: {media}")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(media)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    data = json.loads(result.stdout)
    stream_types = {
        stream.get("codec_type")
        for stream in data.get("streams", [])
        if isinstance(stream, dict)
    }
    missing = set(required_streams) - stream_types
    if missing:
        raise SystemExit(f"{label} is missing required stream(s): {', '.join(sorted(missing))}")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise SystemExit(f"{label} has no valid positive duration.")
    print(f"[export] {label}: {duration:.2f}s; streams={','.join(sorted(stream_types))}")

inspect(sys.argv[1], "source footage", {"video"})
inspect(sys.argv[2], "reference", {"video", "audio"})
PY

echo "[export] Extracting reference audio to $AUDIO_PATH ..."
mkdir -p "$(dirname "$AUDIO_PATH")"
TEMP_AUDIO="${AUDIO_PATH}.part.mp3"
trap 'rm -f "$TEMP_AUDIO" "${PROFILE:-}"' EXIT
rm -f "$TEMP_AUDIO"
ffmpeg -nostdin -hide_banner -loglevel error -y \
  -i "$REFERENCE_PATH" -map 0:a:0 -vn -ac 2 -ar 44100 \
  -c:a libmp3lame -q:a 0 "$TEMP_AUDIO"
[[ -s "$TEMP_AUDIO" ]] || {
  echo "[export] ERROR: FFmpeg did not create the reference soundtrack." >&2
  exit 1
}
mv -f "$TEMP_AUDIO" "$AUDIO_PATH"

echo "[export] Checking Real-ESRGAN executable and model weights ..."
if [[ ! -x "$ROOT/tools/realesrgan/realesrgan-ncnn-vulkan" \
   || ! -s "$ROOT/tools/realesrgan/models/realesrgan-x4plus.param" \
   || ! -s "$ROOT/tools/realesrgan/models/realesrgan-x4plus.bin" ]]; then
  bash "$ROOT/scripts/install_realesrgan_linux.sh"
fi

mkdir -p "$ROOT/output"
PROFILE="$(mktemp "$ROOT/output/.params-export.XXXXXX.json")"
export HEYAA_EXPORT_PROFILE_SOURCE="$BASE_PROFILE"
export HEYAA_EXPORT_PROFILE_DEST="$PROFILE"

echo "[export] Preparing a temporary profile (tracked params.json stays unchanged) ..."
"$PYTHON" - <<'PY'
import json
import os
from pathlib import Path

source = Path(os.environ["HEYAA_EXPORT_PROFILE_SOURCE"])
destination = Path(os.environ["HEYAA_EXPORT_PROFILE_DEST"])
config = json.loads(source.read_text(encoding="utf-8"))

video = config.setdefault("video_settings", {})
edit = config.setdefault("edit_settings", {})
audio = config.setdefault("audio_settings", {})

video["resolution"] = "1080x1920"
video["fps"] = 60
video["ai_upscale_enabled"] = True

edit["duration_seconds"] = 20
edit["min_clips"] = 11
edit["max_clips"] = max(11, int(edit.get("max_clips", 40)))
edit["freeze_duration"] = 2.0
edit["reference_pacing"] = True
edit["mirror_enabled"] = True
edit["ending_skull_enabled"] = False
edit["edl_mode"] = "on"

audio["music_loop"] = True

destination.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
print(f"[export] Profile prepared from {source}")
PY

export HEYAA_PARAMS_PATH="$PROFILE"

echo "[export] Running dependency, model and hardware-Vulkan preflight ..."
"$PYTHON" "$ROOT/src/agent_director.py" doctor

echo "[export] Starting $EDIT_COUNT distinct edit(s) ..."
"$PYTHON" "$ROOT/src/agent_director.py" \
  --video-path "$VIDEO_PATH" \
  --music-path "$AUDIO_PATH" \
  --reference-path "$REFERENCE_PATH" \
  --require-reference \
  --edits "$EDIT_COUNT"

RUN_DIR="$(find "$ROOT/output/runs" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
  | sort -nr | head -1 | cut -d' ' -f2-)"
[[ -n "$RUN_DIR" && -d "$RUN_DIR/edits" ]] || {
  echo "[export] ERROR: completed run directory was not found." >&2
  exit 1
}

mapfile -d '' EXPORTS < <(
  find "$RUN_DIR/edits" -type f -name 'final_phonk_20s.mp4' -print0 | sort -z
)
echo "[export] Finished video files: ${#EXPORTS[@]} / $EDIT_COUNT"
printf '  %s\n' "${EXPORTS[@]}"
if [[ "${#EXPORTS[@]}" -ne "$EDIT_COUNT" ]]; then
  echo "[export] ERROR: not every requested edit produced a final MP4. Inspect $RUN_DIR." >&2
  exit 1
fi

echo "[export] Reports and EDLs: $RUN_DIR"
echo "[export] Temporary profile will be removed; your saved settings are unchanged."
