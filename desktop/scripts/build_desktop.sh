#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
BUILD_DIR="$DESKTOP_DIR/build"
RUNTIME_DIR="$BUILD_DIR/runtime"
RUNTIME_BIN_DIR="$BUILD_DIR/runtime/bin"
RUNTIME_COMPONENTS_DIR="$RUNTIME_DIR/components"
RUNTIME_COMPONENTS_MANIFEST="$RUNTIME_DIR/components-manifest.json"
DIST_DIR="$BUILD_DIR/dist"
WORK_DIR="$BUILD_DIR/work"
DMG_STAGING_DIR="$BUILD_DIR/dmg-staging"
SPEC_FILE="$DESKTOP_DIR/spec/EverythingCapture.spec"
INFO_TEMPLATE="$DESKTOP_DIR/spec/Info.plist.template"
PYTHON_BIN="${DESKTOP_PYTHON_BIN:-$ROOT_DIR/backend/venv/bin/python}"
VERSION="${EC_DESKTOP_VERSION:-0.1.0}"
BUILD_NUMBER="${EC_DESKTOP_BUILD_NUMBER:-$VERSION}"
LOCAL_TRANSCRIPTION_BUNDLE_DIRNAME="${VERSION//./__dot__}"
APP_ICON_PATH="$BUILD_DIR/icon.icns"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python runtime at $PYTHON_BIN" >&2
  exit 1
fi

"$DESKTOP_DIR/scripts/preflight_desktop.sh"

rm -rf "$RUNTIME_DIR" "$DIST_DIR" "$WORK_DIR" "$DMG_STAGING_DIR"
mkdir -p "$RUNTIME_BIN_DIR" "$DIST_DIR" "$WORK_DIR" "$DMG_STAGING_DIR"

"$DESKTOP_DIR/scripts/generate_app_icon.sh" "$APP_ICON_PATH" >/dev/null
"$DESKTOP_DIR/scripts/build_ocr_helper.sh" >/dev/null

FFMPEG_SOURCE="${EC_FFMPEG_SOURCE:-$(command -v ffmpeg || true)}"
if [[ -z "$FFMPEG_SOURCE" || ! -f "$FFMPEG_SOURCE" ]]; then
  echo "ffmpeg not found. Set EC_FFMPEG_SOURCE or install ffmpeg on the build machine." >&2
  exit 1
fi

cp "$FFMPEG_SOURCE" "$RUNTIME_BIN_DIR/ffmpeg"
chmod +x "$RUNTIME_BIN_DIR/ffmpeg"

LOCAL_TRANSCRIPTION_STAGE_DIR="$RUNTIME_COMPONENTS_DIR/local-transcription/$LOCAL_TRANSCRIPTION_BUNDLE_DIRNAME" \
  zsh "$DESKTOP_DIR/scripts/stage_local_transcription_payload.sh" >/dev/null
find "$RUNTIME_COMPONENTS_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$RUNTIME_COMPONENTS_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

"$PYTHON_BIN" "$DESKTOP_DIR/scripts/generate_bundled_components_manifest.py" \
  --output "$RUNTIME_COMPONENTS_MANIFEST" \
  --version "$VERSION" \
  --component-root "$RUNTIME_COMPONENTS_DIR/local-transcription/$LOCAL_TRANSCRIPTION_BUNDLE_DIRNAME" \
  --entry-python-path "python" >/dev/null

EC_APP_ICON_PATH="$APP_ICON_PATH" "$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --distpath "$DIST_DIR" \
  --workpath "$WORK_DIR" \
  "$SPEC_FILE"

APP_PATH="$(find "$DIST_DIR" -maxdepth 2 -name '*.app' | head -n 1)"
if [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  echo "PyInstaller did not produce an .app bundle under $DIST_DIR" >&2
  exit 1
fi

sed \
  -e "s/__VERSION__/$VERSION/g" \
  -e "s/__BUILD__/$BUILD_NUMBER/g" \
  "$INFO_TEMPLATE" > "$APP_PATH/Contents/Info.plist"

"$PYTHON_BIN" "$DESKTOP_DIR/scripts/fix_component_resource_links.py" --app "$APP_PATH" >/dev/null

BUNDLED_TRANSCRIPTION_PYTHONPATH="$APP_PATH/Contents/Resources/desktop_runtime/components/local-transcription/$LOCAL_TRANSCRIPTION_BUNDLE_DIRNAME/python"
if [[ -d "$BUNDLED_TRANSCRIPTION_PYTHONPATH" ]]; then
  PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONPATH="$BUNDLED_TRANSCRIPTION_PYTHONPATH" \
    "$PYTHON_BIN" -S -c "import mlx_whisper; print(mlx_whisper.__version__)" >/dev/null
fi

find "$APP_PATH/Contents/Resources/desktop_runtime/components" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$APP_PATH/Contents/Resources/desktop_runtime/components" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
codesign --force --sign - "$APP_PATH" >/dev/null

"$PYTHON_BIN" "$DESKTOP_DIR/scripts/verify_app_bundle.py" --app "$APP_PATH" --version "$VERSION"

cp -R "$APP_PATH" "$DMG_STAGING_DIR/"

DMG_PATH="$BUILD_DIR/EverythingCapture-${VERSION}-arm64.dmg"
rm -f "$DMG_PATH"
hdiutil create \
  -volname "Everything Capture" \
  -srcfolder "$DMG_STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "App bundle: $APP_PATH"
echo "DMG: $DMG_PATH"
