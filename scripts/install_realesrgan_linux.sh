#!/usr/bin/env bash
set -euo pipefail

# Pinned official upstream Linux release. The archive includes the executable
# and its model files; no Python/PyTorch installation is required.
VERSION="v0.2.0"
ASSET="realesrgan-ncnn-vulkan-v0.2.0-ubuntu.zip"
URL="https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases/download/${VERSION}/${ASSET}"
DEST="${1:-tools/realesrgan}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for command in curl unzip find install; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "[upscale install] Missing required command: $command" >&2
    exit 1
  }
done

echo "[upscale install] Downloading official Real-ESRGAN ncnn-vulkan ${VERSION} release..."
curl --fail --location --retry 3 --connect-timeout 20 "$URL" --output "$TMP/$ASSET"
mkdir -p "$TMP/unpacked"
unzip -q "$TMP/$ASSET" -d "$TMP/unpacked"

BINARY="$(find "$TMP/unpacked" -type f -name 'realesrgan-ncnn-vulkan' -print -quit)"
MODELS="$(find "$TMP/unpacked" -type d -name models -print -quit)"
if [[ -z "$BINARY" || ! -f "$BINARY" ]]; then
  echo "[upscale install] Upstream archive did not contain the expected Linux executable." >&2
  exit 1
fi
if [[ -z "$MODELS" || ! -d "$MODELS" || -z "$(find "$MODELS" -type f -print -quit)" ]]; then
  echo "[upscale install] Upstream archive did not contain its model files." >&2
  exit 1
fi

mkdir -p "$DEST"
install -m 0755 "$BINARY" "$DEST/realesrgan-ncnn-vulkan"
mkdir -p "$DEST/models"
cp -a "$MODELS/." "$DEST/models/"

"$DEST/realesrgan-ncnn-vulkan" -h >/dev/null
echo "[upscale install] Installed executable: $DEST/realesrgan-ncnn-vulkan"
echo "[upscale install] Installed models: $DEST/models"
echo "[upscale install] Check params.json: video_settings.ai_upscale_enabled must be true to run AI restoration."
