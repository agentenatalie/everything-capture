#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
BUILD_DIR="$DESKTOP_DIR/build"
ICON_SOURCE="${EC_APP_ICON_SOURCE:-$ROOT_DIR/logo/logo-128.svg}"
OUTPUT_PATH="${1:-$BUILD_DIR/icon.icns}"
ICONSET_DIR="$BUILD_DIR/icon.iconset"

fail() {
  echo "icon generation failed: $1" >&2
  exit 1
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    fail "missing required command: $command_name"
  fi
}

if [[ ! -f "$ICON_SOURCE" ]]; then
  fail "missing app icon source at $ICON_SOURCE"
fi

require_command sips
require_command iconutil

mkdir -p "$(dirname "$OUTPUT_PATH")"
rm -rf "$ICONSET_DIR"
mkdir -p "$ICONSET_DIR"

render_icon() {
  local name="$1"
  local pixel_size="$2"
  sips -s format png "$ICON_SOURCE" --resampleHeightWidth "$pixel_size" "$pixel_size" --out "$ICONSET_DIR/$name" >/dev/null
}

render_icon icon_16x16.png 16
render_icon icon_16x16@2x.png 32
render_icon icon_32x32.png 32
render_icon icon_32x32@2x.png 64
render_icon icon_128x128.png 128
render_icon icon_128x128@2x.png 256
render_icon icon_256x256.png 256
render_icon icon_256x256@2x.png 512
render_icon icon_512x512.png 512
render_icon icon_512x512@2x.png 1024

iconutil -c icns "$ICONSET_DIR" -o "$OUTPUT_PATH"
echo "$OUTPUT_PATH"
