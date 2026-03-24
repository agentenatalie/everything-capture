#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
BUILD_DIR="$DESKTOP_DIR/build"
VERSION="${EC_DESKTOP_VERSION:-0.1.0}"
APP_DOWNLOAD_URL="${EC_RELEASE_DOWNLOAD_URL:-}"
RELEASE_MANIFEST_OUTPUT="${EC_RELEASE_MANIFEST_OUTPUT:-$BUILD_DIR/release-manifest.json}"
COMPONENTS_MANIFEST_OUTPUT="${EC_HOSTED_COMPONENTS_MANIFEST_OUTPUT:-$BUILD_DIR/components-manifest.json}"
COMPONENT_METADATA_PATHS="${EC_COMPONENT_METADATA_PATHS:-}"

if [[ -z "$APP_DOWNLOAD_URL" ]]; then
  echo "EC_RELEASE_DOWNLOAD_URL is required" >&2
  exit 1
fi

"$DESKTOP_DIR/scripts/build_desktop.sh"

APP_PATH="$(find "$BUILD_DIR/dist" -maxdepth 2 -name '*.app' | head -n 1)"
DMG_PATH="$BUILD_DIR/EverythingCapture-${VERSION}-arm64.dmg"

if [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  echo "App bundle not found under $BUILD_DIR/dist" >&2
  exit 1
fi

if [[ ! -f "$DMG_PATH" ]]; then
  echo "DMG not found: $DMG_PATH" >&2
  exit 1
fi

"$DESKTOP_DIR/scripts/sign_app.sh" "$APP_PATH"
"$DESKTOP_DIR/scripts/notarize_dmg.sh" "$DMG_PATH"

component_args=()
if [[ -n "$COMPONENT_METADATA_PATHS" ]]; then
  IFS=',' read -rA component_paths <<< "$COMPONENT_METADATA_PATHS"
  for component_path in "${component_paths[@]}"; do
    trimmed_path="${component_path## }"
    trimmed_path="${trimmed_path%% }"
    if [[ -n "$trimmed_path" ]]; then
      component_args+=("--component-json" "$trimmed_path")
    fi
  done
fi

"$ROOT_DIR/backend/venv/bin/python" "$DESKTOP_DIR/scripts/generate_release_manifest.py" \
  "$DMG_PATH" \
  "$RELEASE_MANIFEST_OUTPUT" \
  --version "$VERSION" \
  --download-url "$APP_DOWNLOAD_URL" \
  --components-manifest-output "$COMPONENTS_MANIFEST_OUTPUT" \
  "${component_args[@]}"

echo "Release manifest: $RELEASE_MANIFEST_OUTPUT"
echo "Hosted components manifest: $COMPONENTS_MANIFEST_OUTPUT"
