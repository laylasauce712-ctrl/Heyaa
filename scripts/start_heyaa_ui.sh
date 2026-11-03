#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v python3 >/dev/null 2>&1 || {
  echo "[Heyaa Studio] Python 3 is required." >&2
  exit 1
}

mkdir -p input output/runs output/releases

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "[Heyaa Studio] FFmpeg and ffprobe must be installed and available on PATH." >&2
  exit 1
fi

echo "[Heyaa Studio] Starting the local Studio on http://127.0.0.1:8765"
echo "[Heyaa Studio] Press Ctrl+C in this terminal to stop the UI server."
exec python3 -m src.heyaa.local_app
