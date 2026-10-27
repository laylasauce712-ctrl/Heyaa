#!/usr/bin/env bash
# Safely reuse local media, settings, and Real-ESRGAN files from the interrupted
# worktree without changing that worktree. Designed for WSL/Linux.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ARG="$ROOT/../Heyaa-ai-upscale-run"
DISABLE_AI_UPSCALE=0
while (($#)); do
    case "$1" in
        --disable-ai-upscale)
            DISABLE_AI_UPSCALE=1
            shift
            ;;
        --source-worktree)
            if [[ $# -lt 2 ]]; then
                echo "[setup] --source-worktree needs a path." >&2
                exit 2
            fi
            SOURCE_ARG="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: bash scripts/prepare_local_worktree.sh [--disable-ai-upscale] [--source-worktree PATH]"
            echo "The default source path is ../Heyaa-ai-upscale-run relative to this worktree."
            exit 0
            ;;
        -*)
            echo "[setup] Unknown option: $1" >&2
            exit 2
            ;;
        *)
            # Backward-compatible positional source path.
            SOURCE_ARG="$1"
            shift
            ;;
    esac
done
if [[ ! -d "$SOURCE_ARG" ]]; then
    echo "[setup] Source worktree not found: $SOURCE_ARG" >&2
    echo "[setup] Pass --source-worktree PATH or the existing worktree path as the first argument." >&2
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

# Check whether the Python venv can actually be created before changing local paths.
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    VENV_PROBE="$(mktemp -d)"
    if ! "$PYTHON_BIN" -m venv "$VENV_PROBE/probe" >/dev/null 2>&1; then
        rm -rf "$VENV_PROBE"
        echo "[setup] Python venv support is missing. Install it first with: apt install -y python3-venv" >&2
        echo "[setup] No input symlinks or settings have been changed." >&2
        exit 4
    fi
    rm -rf "$VENV_PROBE"
fi

# Accept only the source settings or the exact settings produced by this helper.
# This makes --disable-ai-upscale repeatable without permitting unrelated edits to be overwritten.
if [[ -f "$ROOT/params.json" ]]; then
    if ! "$PYTHON_BIN" - "$SOURCE/params.json" "$ROOT/params.json" "$DISABLE_AI_UPSCALE" <<'PY'
import json, pathlib, sys
source_path, target_path, disable = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
source = json.loads(pathlib.Path(source_path).read_text(encoding="utf-8"))
target = json.loads(pathlib.Path(target_path).read_text(encoding="utf-8"))
desired = json.loads(json.dumps(source))
if disable:
    desired.setdefault("video_settings", {})["ai_upscale_enabled"] = False
raise SystemExit(0 if target == desired else 1)
PY
    then
        if ! git -C "$ROOT" diff --quiet -- params.json ||
           ! git -C "$ROOT" diff --cached --quiet -- params.json; then
            echo "[setup] Destination params.json has independent local edits; refusing to overwrite it." >&2
            echo "[setup] Nothing in params.json was changed. Review the two files first." >&2
            exit 3
        fi
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

if [[ ! -f "$ROOT/params.json" ]] ||
   ! "$PYTHON_BIN" - "$SOURCE/params.json" "$ROOT/params.json" "$DISABLE_AI_UPSCALE" <<'PY'
import json, pathlib, sys
source_path, target_path, disable = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
source = json.loads(pathlib.Path(source_path).read_text(encoding="utf-8"))
target = json.loads(pathlib.Path(target_path).read_text(encoding="utf-8")) if pathlib.Path(target_path).exists() else None
desired = json.loads(json.dumps(source))
if disable:
    desired.setdefault("video_settings", {})["ai_upscale_enabled"] = False
raise SystemExit(0 if target == desired else 1)
PY
then
    cp "$SOURCE/params.json" "$ROOT/params.json"
    if [[ "$DISABLE_AI_UPSCALE" -eq 1 ]]; then
        "$PYTHON_BIN" - "$ROOT/params.json" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data.setdefault("video_settings", {})["ai_upscale_enabled"] = False
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
        echo "[setup] Copied local settings and disabled AI upscaling in this worktree only."
    else
        echo "[setup] Copied the local params.json into the new worktree; the source copy is untouched."
    fi
else
    echo "[setup] params.json already matches the requested local setup."
fi

# Keep vision dependencies isolated from the OS Python / other projects.
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check -r "$ROOT/requirements-vision.txt"
"$ROOT/.venv/bin/python" -c 'import cv2; print("[setup] OpenCV ready:", cv2.__version__)'

echo
echo "[setup] Ready. Run from $ROOT using the repository venv."
echo "[setup] Start with one candidate before spending time on all comparison renders:"
echo "        .venv/bin/python src/agent_director.py --variants 1 --clip-count 8"
echo "[setup] Existing worktree was not changed; no render was started automatically."
