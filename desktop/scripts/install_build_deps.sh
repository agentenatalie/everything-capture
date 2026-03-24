#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
PYTHON_BIN="${DESKTOP_PYTHON_BIN:-$ROOT_DIR/backend/venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python runtime at $PYTHON_BIN" >&2
  exit 1
fi

"$PYTHON_BIN" -m pip install -r "$DESKTOP_DIR/requirements-build.txt"
