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

find_optional_command() {
  local command_name="$1"
  local homebrew_path="/opt/homebrew/bin/$command_name"
  local usr_local_path="/usr/local/bin/$command_name"

  if command -v "$command_name" >/dev/null 2>&1; then
    command -v "$command_name"
    return 0
  fi

  if [[ -x "$homebrew_path" ]]; then
    echo "$homebrew_path"
    return 0
  fi

  if [[ -x "$usr_local_path" ]]; then
    echo "$usr_local_path"
    return 0
  fi

  return 1
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "desktop packaging currently supports macOS build machines only"
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  fail "desktop packaging Phase 2 is scoped to Apple Silicon (arm64) builders"
fi

require_command xcrun
require_command hdiutil
require_command sips
require_command iconutil

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

if [[ ! -f "${EC_APP_ICON_SOURCE:-$ROOT_DIR/logo/logo-128.svg}" ]]; then
  fail "missing app icon source; set EC_APP_ICON_SOURCE or add logo/logo-128.svg"
fi

if [[ ! -f "${EC_DMG_BACKGROUND_SOURCE:-$DESKTOP_DIR/spec/dmg-background.svg}" ]]; then
  fail "missing DMG background source; set EC_DMG_BACKGROUND_SOURCE or add desktop/spec/dmg-background.svg"
fi

"$PYTHON_BIN" -c "import PyInstaller, webview" >/dev/null 2>&1 || \
  fail "build Python is missing PyInstaller or pywebview; run desktop/scripts/install_build_deps.sh"

echo "preflight ok"
echo "python: $PYTHON_BIN"
echo "ffmpeg: $FFMPEG_SOURCE"
echo "swiftc: $(xcrun --find swiftc)"

CREATE_DMG_BIN="${EC_CREATE_DMG_BIN:-$(find_optional_command create-dmg || true)}"
if [[ -n "$CREATE_DMG_BIN" ]]; then
  echo "create-dmg: $CREATE_DMG_BIN"
else
  echo "create-dmg: not found (build will fall back to plain hdiutil DMG without Applications drag layout)"
fi
