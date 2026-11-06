#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
ENV_DIR="$ROOT/tools/norfair-analysis/.venv"
REQUIREMENTS="$ROOT/requirements-tracking.txt"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON" >&2
  exit 1
fi
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("The Norfair worker requires Python 3.10 or newer.")
PY

if [[ -L "$ROOT/tools/norfair-analysis" || ( -e "$ROOT/tools/norfair-analysis" && ! -d "$ROOT/tools/norfair-analysis" ) ]]; then
  echo "Refusing to use an unexpected tools/norfair-analysis path." >&2
  exit 1
fi
mkdir -p "$ROOT/tools/norfair-analysis"

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
from importlib.metadata import version
expected = "2.3.0"
actual = version("norfair")
if actual != expected:
    raise SystemExit(f"Expected Norfair {expected}; found {actual}.")
print(f"Norfair {actual} is ready in its isolated tracking environment.")
PY
echo "Norfair will observe existing HOG detections during ordinary subject analysis."
echo "The existing greedy appearance tracker remains authoritative; remove only this venv to disable the observer."
