#!/usr/bin/env sh
# Optional deterministic media fixture for later renderer integration tests.
set -eu
OUT_DIR="${1:-tests/fixtures/generated}"
mkdir -p "$OUT_DIR"
if ! command -v ffmpeg >/dev/null 2>&1; then echo "SKIP: ffmpeg not installed" >&2; exit 0; fi
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "testsrc2=size=320x240:rate=30:duration=2" -f lavfi -i "sine=frequency=80:sample_rate=48000:duration=2" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$OUT_DIR/testsrc.mp4"
echo "Created $OUT_DIR/testsrc.mp4"
