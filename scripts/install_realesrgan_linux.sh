#!/usr/bin/env bash
set -euo pipefail

# Pin the official portable pack that includes the Linux executable and NCNN
# model files. The older Real-ESRGAN-ncnn-vulkan v0.2.0 asset contains no
# models, so it is not sufficient for this renderer's explicit model preflight.
VERSION="v0.2.5.0"
ASSET="realesrgan-ncnn-vulkan-20220424-ubuntu.zip"
URL="https://github.com/xinntao/Real-ESRGAN/releases/download/${VERSION}/${ASSET}"
DEST="${1:-tools/realesrgan}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for command in curl unzip find install cp; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "[upscale install] Missing required command: $command" >&2
    exit 1
  }
done

echo "[upscale install] Downloading official Real-ESRGAN ncnn-vulkan ${VERSION} portable pack..."
curl --fail --location --retry 3 --connect-timeout 20 "$URL" --output "$TMP/$ASSET"
mkdir -p "$TMP/unpacked"
unzip -q "$TMP/$ASSET" -d "$TMP/unpacked"

BINARY="$(find "$TMP/unpacked" -type f -name 'realesrgan-ncnn-vulkan' -print -quit)"
MODELS="$(find "$TMP/unpacked" -type d -name models -print -quit)"
if [[ -z "$BINARY" || ! -f "$BINARY" ]]; then
  echo "[upscale install] Official archive did not contain the expected Linux executable." >&2
  exit 1
fi
if [[ -z "$MODELS" || ! -d "$MODELS" || -z "$(find "$MODELS" -type f -print -quit)" ]]; then
  echo "[upscale install] Official archive did not contain its model directory/files." >&2
  exit 1
fi

mkdir -p "$DEST"
install -m 0755 "$BINARY" "$DEST/realesrgan-ncnn-vulkan"
mkdir -p "$DEST/models"
cp -a "$MODELS/." "$DEST/models/"

# The configured default model must be present, not just any model file.
for suffix in param bin; do
  if [[ ! -s "$DEST/models/realesrgan-x4plus.$suffix" ]]; then
    echo "[upscale install] Required default weight is missing: $DEST/models/realesrgan-x4plus.$suffix" >&2
    exit 1
  fi
done

"$DEST/realesrgan-ncnn-vulkan" -h >/dev/null
echo "[upscale install] Installed executable: $DEST/realesrgan-ncnn-vulkan"
echo "[upscale install] Installed model directory: $DEST/models"
echo "[upscale install] Default realesrgan-x4plus weights verified."
echo "[upscale install] Check params.json: video_settings.ai_upscale_enabled must be true to run AI restoration."
