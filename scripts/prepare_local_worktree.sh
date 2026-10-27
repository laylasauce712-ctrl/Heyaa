#!/usr/bin/env bash
# Safely reuse local media, settings, and Real-ESRGAN files from the interrupted
# worktree without changing that worktree. Designed for WSL/Linux.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ARG="${1:-"$ROOT/../Heyaa-ai-upscale-run"}"
if [[ ! -d "$SOURCE_ARG" ]]; then
    echo "[setup] Source worktree not found: $SOURCE_ARG" >&2
    echo "[setup] Pass the existing worktree path as the first argument." >&2
    exit 2
fi
SOURCE="$(cd "$SOURCE_ARG" && pwd)"
if [[ "$SOURCE" == "$ROOT" ]]; then
    echo "[setup] Source and destination worktrees must be different." >&2
    exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "[setup] Python executable not found: $PYTHON_BIN" >&2
    exit 2
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "[setup] Python 3.10 or newer is required." >&2
    exit 2
fi
for file in params.json input/test_video.mp4 input/phonk.mp3; do
    if [[ ! -f "$SOURCE/$file" ]]; then
        echo "[setup] Required source file is missing: $SOURCE/$file" >&2
        exit 2
    fi
done

# Do not overwrite any independent local settings in the destination worktree.
if ! cmp -s "$SOURCE/params.json" "$ROOT/params.json"; then
    if ! git -C "$ROOT" diff --quiet -- params.json ||
       ! git -C "$ROOT" diff --cached --quiet -- params.json; then
        echo "[setup] Destination params.json has local changes and differs from the source." >&2
        echo "[setup] Nothing was overwritten. Review both files before retrying." >&2
        exit 3
    fi
fi

# A symlink keeps the large media files in one place. Existing paths are never replaced.
link_directory() {
    local source_dir="$1"
    local target="$2"
    local label="$3"
    if [[ ! -d "$source_dir" ]]; then
        echo "[setup] Optional directory not found; skipping $label: $source_dir" >&2
        return 0
    fi
    if [[ -L "$target" ]]; then
        if [[ "$(readlink -f "$target")" == "$(readlink -f "$source_dir")" ]]; then
            echo "[setup] $label already linked."
            return 0
        fi
        echo "[setup] Refusing to replace existing $label symlink: $target" >&2
        exit 3
    fi
    if [[ -e "$target" ]]; then
        echo "[setup] Refusing to replace existing $label path: $target" >&2
        exit 3
    fi
    mkdir -p "$(dirname "$target")"
    local relative_source
    relative_source="$(realpath --relative-to="$(dirname "$target")" "$source_dir")"
    ln -s "$relative_source" "$target"
    echo "[setup] Linked $label."
}

link_directory "$SOURCE/input" "$ROOT/input" "input media"

# The configured Real-ESRGAN binary/weights are large and intentionally untracked.
if [[ -d "$SOURCE/tools/realesrgan" ]]; then
    link_directory "$SOURCE/tools/realesrgan" "$ROOT/tools/realesrgan" "Real-ESRGAN executable and models"
else
    echo "[setup] Real-ESRGAN directory not found in source worktree; AI-upscale preflight may require installation." >&2
fi

if ! cmp -s "$SOURCE/params.json" "$ROOT/params.json"; then
    cp "$SOURCE/params.json" "$ROOT/params.json"
    echo "[setup] Copied the local params.json into the new worktree; the source copy is untouched."
else
    echo "[setup] params.json already matches the source settings."
fi

# Keep vision dependencies isolated from the OS Python / other projects.
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    if ! "$PYTHON_BIN" -m venv "$ROOT/.venv"; then
        echo "[setup] Could not create .venv. On Ubuntu/WSL install python3-venv, then rerun this script." >&2
        exit 4
    fi
fi
"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check -r "$ROOT/requirements-vision.txt"
"$ROOT/.venv/bin/python" -c 'import cv2; print("[setup] OpenCV ready:", cv2.__version__)'

echo
echo "[setup] Ready. Run from $ROOT using the repository venv."
echo "[setup] Start with one candidate before spending time on all comparison renders:"
echo "        .venv/bin/python src/agent_director.py --variants 1 --clip-count 8"
echo "[setup] Existing worktree was not changed; no render was started automatically."
