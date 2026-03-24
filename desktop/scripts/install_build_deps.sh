#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
PYTHON_BIN="${DESKTOP_PYTHON_BIN:-$ROOT_DIR/backend/venv/bin/python}"

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

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python runtime at $PYTHON_BIN" >&2
  exit 1
fi

"$PYTHON_BIN" -m pip install -r "$DESKTOP_DIR/requirements-build.txt"

if [[ "$(uname -s)" == "Darwin" ]]; then
  BREW_BIN="${HOMEBREW_BIN:-$(find_optional_command brew || true)}"
  CREATE_DMG_BIN="${EC_CREATE_DMG_BIN:-$(find_optional_command create-dmg || true)}"

  if [[ -n "$CREATE_DMG_BIN" ]]; then
    echo "create-dmg already installed at $CREATE_DMG_BIN"
  elif [[ -n "$BREW_BIN" ]]; then
    "$BREW_BIN" install create-dmg
  else
    echo "warning: Homebrew not found; install create-dmg manually if you want Finder-styled DMGs" >&2
  fi
fi
