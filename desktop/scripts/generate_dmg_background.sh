#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
BACKGROUND_SOURCE="${EC_DMG_BACKGROUND_SOURCE:-$DESKTOP_DIR/spec/dmg-background.svg}"
OUTPUT_PATH="${1:-$DESKTOP_DIR/build/dmg-background.png}"

fail() {
  echo "DMG background generation failed: $1" >&2
  exit 1
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    fail "missing required command: $command_name"
  fi
}

if [[ ! -f "$BACKGROUND_SOURCE" ]]; then
  fail "missing background source at $BACKGROUND_SOURCE"
fi

require_command sips

mkdir -p "$(dirname "$OUTPUT_PATH")"
sips -s format png "$BACKGROUND_SOURCE" --out "$OUTPUT_PATH" >/dev/null
echo "$OUTPUT_PATH"
