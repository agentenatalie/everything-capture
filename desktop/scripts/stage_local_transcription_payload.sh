#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
BUILD_DIR="$DESKTOP_DIR/build"
OUTPUT_DIR="${LOCAL_TRANSCRIPTION_STAGE_DIR:-${LOCAL_TRANSCRIPTION_SOURCE_DIR:-$BUILD_DIR/components/local-transcription-payload}}"
SUMMARY_OUTPUT="${LOCAL_TRANSCRIPTION_STAGE_SUMMARY_OUTPUT:-$BUILD_DIR/components/local-transcription-payload-summary.json}"
PYTHON_BIN="${DESKTOP_PYTHON_BIN:-$ROOT_DIR/backend/venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python runtime at $PYTHON_BIN" >&2
  exit 1
fi

"$PYTHON_BIN" "$DESKTOP_DIR/scripts/stage_local_transcription_payload.py" \
  --output-dir "$OUTPUT_DIR" \
  --root-dist "mlx-whisper" \
  --exclude-dist "torch" \
  --exclude-dist "numba" \
  --exclude-dist "llvmlite" \
  --summary-output "$SUMMARY_OUTPUT"
