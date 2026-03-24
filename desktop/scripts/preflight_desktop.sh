#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
PYTHON_BIN="${DESKTOP_PYTHON_BIN:-$ROOT_DIR/backend/venv/bin/python}"
FFMPEG_SOURCE="${EC_FFMPEG_SOURCE:-$(command -v ffmpeg || true)}"

fail() {
  echo "preflight failed: $1" >&2
  exit 1
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    fail "missing required command: $command_name"
  fi
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "desktop packaging currently supports macOS build machines only"
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  fail "desktop packaging Phase 2 is scoped to Apple Silicon (arm64) builders"
fi

require_command xcrun
require_command hdiutil

if ! xcrun --find swiftc >/dev/null 2>&1; then
  fail "swiftc not found via xcrun"
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  fail "missing Python runtime at $PYTHON_BIN"
fi

if [[ -z "$FFMPEG_SOURCE" || ! -f "$FFMPEG_SOURCE" ]]; then
  fail "ffmpeg not found; set EC_FFMPEG_SOURCE or install ffmpeg on the build machine"
fi

if [[ ! -f "$DESKTOP_DIR/spec/EverythingCapture.spec" ]]; then
  fail "missing desktop spec file"
fi

if [[ ! -f "$DESKTOP_DIR/spec/bundle_manifest.py" ]]; then
  fail "missing machine-readable bundle manifest"
fi

"$PYTHON_BIN" -c "import PyInstaller, webview" >/dev/null 2>&1 || \
  fail "build Python is missing PyInstaller or pywebview; run desktop/scripts/install_build_deps.sh"

echo "preflight ok"
echo "python: $PYTHON_BIN"
echo "ffmpeg: $FFMPEG_SOURCE"
echo "swiftc: $(xcrun --find swiftc)"
