#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
BUILD_DIR="$DESKTOP_DIR/build"
OUTPUT_DIR="${EC_COMPONENT_OUTPUT_DIR:-$BUILD_DIR/components}"
VERSION="${EC_COMPONENT_VERSION:-${EC_DESKTOP_VERSION:-0.1.0}}"
SOURCE_DIR="${LOCAL_TRANSCRIPTION_SOURCE_DIR:-}"
DOWNLOAD_URL="${LOCAL_TRANSCRIPTION_DOWNLOAD_URL:-}"
METADATA_OUTPUT="${LOCAL_TRANSCRIPTION_METADATA_OUTPUT:-$OUTPUT_DIR/local-transcription-${VERSION}.json}"
UNAVAILABLE_REASON="${LOCAL_TRANSCRIPTION_UNAVAILABLE_REASON:-}"
PYTHON_BIN="${DESKTOP_PYTHON_BIN:-$ROOT_DIR/backend/venv/bin/python}"

if [[ -z "$SOURCE_DIR" ]]; then
  echo "LOCAL_TRANSCRIPTION_SOURCE_DIR is required and must point to a staged component payload directory." >&2
  exit 1
fi

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "Component source directory not found: $SOURCE_DIR" >&2
  exit 1
fi

if [[ ! -d "$SOURCE_DIR/python" ]]; then
  echo "Local transcription component source must contain a python/ directory: $SOURCE_DIR" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python runtime at $PYTHON_BIN" >&2
  exit 1
fi

component_args=(
  --component-id "local-transcription"
  --title "Local Transcription"
  --description "为视频启用本地音频转录。组件包应提供 mlx-whisper 及其依赖的 Python 目录。"
  --version "$VERSION"
  --source-dir "$SOURCE_DIR"
  --output-dir "$OUTPUT_DIR"
  --metadata-output "$METADATA_OUTPUT"
  --download-url "$DOWNLOAD_URL"
  --platform "macos-arm64"
  --entry-python-path "python"
)

if [[ -n "$UNAVAILABLE_REASON" ]]; then
  component_args+=(--unavailable-reason "$UNAVAILABLE_REASON")
fi

"$PYTHON_BIN" "$DESKTOP_DIR/scripts/package_component.py" "${component_args[@]}"
