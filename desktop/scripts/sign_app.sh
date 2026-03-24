#!/bin/zsh
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: sign_app.sh /path/to/Everything\\ Capture.app" >&2
  exit 1
fi

APP_PATH="$1"
IDENTITY="${APPLE_DEVELOPER_IDENTITY:-}"
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
ENTITLEMENTS_PATH="$ROOT_DIR/desktop/spec/entitlements.plist"

if [[ -z "$IDENTITY" ]]; then
  echo "APPLE_DEVELOPER_IDENTITY is required" >&2
  exit 1
fi

if [[ ! -d "$APP_PATH" ]]; then
  echo "App bundle not found: $APP_PATH" >&2
  exit 1
fi

find "$APP_PATH" -type f \( \
  -path "*/desktop_runtime/bin/*" -o \
  -path "*/Contents/MacOS/*" -o \
  -name "*.dylib" -o \
  -name "*.so" \
\) | while read -r file_path; do
  codesign --force --sign "$IDENTITY" --timestamp "$file_path"
done

codesign \
  --force \
  --sign "$IDENTITY" \
  --options runtime \
  --entitlements "$ENTITLEMENTS_PATH" \
  --timestamp \
  "$APP_PATH"

codesign --verify --deep --strict --verbose=2 "$APP_PATH"
echo "Signed: $APP_PATH"
