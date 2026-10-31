#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
ENV_DIR="$ROOT/tools/beat-analysis/.venv"
REQUIREMENTS="$ROOT/requirements-beats.txt"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON" >&2
  exit 1
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("The Beat This! shadow worker requires Python 3.10 or newer.")
PY

if [[ -L "$ROOT/tools/beat-analysis" || ( -e "$ROOT/tools/beat-analysis" && ! -d "$ROOT/tools/beat-analysis" ) ]]; then
  echo "Refusing to use an unexpected tools/beat-analysis path." >&2
  exit 1
fi
mkdir -p "$ROOT/tools/beat-analysis"

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

# CPU-only PyTorch keeps this optional environment independent of the host GPU
# and avoids silently downloading a CUDA build into the core environment.
"$ENV_DIR/bin/python" -m pip install --disable-pip-version-check --no-input \
  --index-url https://download.pytorch.org/whl/cpu "torch>=2.0" "torchaudio>=2.0"
"$ENV_DIR/bin/python" -m pip install --disable-pip-version-check --no-input -r "$REQUIREMENTS"
"$ENV_DIR/bin/python" - <<'PY'
from importlib.metadata import version
expected = "1.1.0"
actual = version("beat-this")
if actual != expected:
    raise SystemExit(f"Expected Beat This! {expected}; found {actual}.")
import torch
print(f"Beat This! {actual}; PyTorch {torch.__version__}; device policy: CPU.")
PY
echo "Heyaa will automatically use this backend as a shadow observer during ordinary renders."
echo "The existing FFmpeg beat/onset heuristic remains authoritative; remove only this venv to disable the observer."
