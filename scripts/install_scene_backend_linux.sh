#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
ENV_DIR="$ROOT/tools/scene-analysis/.venv"
REQUIREMENTS="$ROOT/requirements-scenes.txt"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON" >&2
  exit 1
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("PySceneDetect 0.7.2 requires Python 3.10 or newer.")
PY

if [[ -L "$ROOT/tools/scene-analysis" || ( -e "$ROOT/tools/scene-analysis" && ! -d "$ROOT/tools/scene-analysis" ) ]]; then
  echo "Refusing to use an unexpected tools/scene-analysis path." >&2
  exit 1
fi
mkdir -p "$ROOT/tools/scene-analysis"

if [[ -L "$ENV_DIR" ]]; then
  echo "Refusing to replace a symlink at $ENV_DIR." >&2
  exit 1
fi
if [[ -e "$ENV_DIR" && ! -f "$ENV_DIR/pyvenv.cfg" ]]; then
  echo "Refusing to replace an existing non-venv directory at $ENV_DIR." >&2
  exit 1
fi
if [[ ! -f "$ENV_DIR/pyvenv.cfg" ]]; then
  "$PYTHON" -m venv "$ENV_DIR"
fi

"$ENV_DIR/bin/python" -m pip install --disable-pip-version-check --no-input -r "$REQUIREMENTS"
"$ENV_DIR/bin/python" - <<'PY'
import scenedetect
expected = "0.7.2"
actual = getattr(scenedetect, "__version__", "unknown")
if actual != expected:
    raise SystemExit(f"Expected PySceneDetect {expected}; found {actual}.")
print(f"PySceneDetect {actual} is ready in the isolated scene-analysis environment.")
PY
echo "Heyaa will automatically use this backend as a shadow observer during ordinary renders."
echo "The existing FFmpeg scene detector remains authoritative; remove this venv to disable the observer."
