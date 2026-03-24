#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
OUTPUT_DIR="$ROOT_DIR/desktop/build/runtime/bin"
SOURCE_FILE="$ROOT_DIR/backend/services/media_text_extract.swift"
TARGET_FILE="$OUTPUT_DIR/media_text_extract"
MACOS_TARGET="${EC_MACOS_DEPLOYMENT_TARGET:-13.0}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "build_ocr_helper.sh only supports macOS builders" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

xcrun swiftc \
  -O \
  -target "arm64-apple-macos${MACOS_TARGET}" \
  "$SOURCE_FILE" \
  -o "$TARGET_FILE"

chmod +x "$TARGET_FILE"
echo "$TARGET_FILE"
