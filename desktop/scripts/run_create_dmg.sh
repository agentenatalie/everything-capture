#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"

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

resolve_support_dir() {
  local create_dmg_bin="$1"
  local script_dir
  script_dir="$(cd "$(dirname "$create_dmg_bin")" && pwd)"

  if [[ -f "$script_dir/.this-is-the-create-dmg-repo" ]]; then
    echo "$script_dir/support"
    return 0
  fi

  echo "$(cd "$script_dir/.." && pwd)/share/create-dmg/support"
}

wrap_applescript_template() {
  local source_template="$1"
  local destination_template="$2"
  local timeout_seconds="$3"

  awk -v timeout_seconds="$timeout_seconds" '
NR == 1 {
  print
  print "\twith timeout of " timeout_seconds " seconds"
  next
}
{
  lines[NR] = $0
}
END {
  for (i = 2; i < NR; i++) {
    print lines[i]
  }
  print "\tend timeout"
  print lines[NR]
}
' "$source_template" > "$destination_template"
}

CREATE_DMG_BIN="${EC_CREATE_DMG_BIN:-$(find_optional_command create-dmg || true)}"
if [[ -z "$CREATE_DMG_BIN" ]]; then
  echo "create-dmg not found" >&2
  exit 1
fi

CREATE_DMG_SUPPORT_DIR="$(resolve_support_dir "$CREATE_DMG_BIN")"
if [[ ! -d "$CREATE_DMG_SUPPORT_DIR" ]]; then
  echo "create-dmg support directory not found: $CREATE_DMG_SUPPORT_DIR" >&2
  exit 1
fi

APPLESCRIPT_TIMEOUT="${EC_CREATE_DMG_APPLESCRIPT_TIMEOUT:-90}"
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/create-dmg-wrapper.XXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT

mkdir -p "$TEMP_DIR/support"
cp "$CREATE_DMG_BIN" "$TEMP_DIR/create-dmg"
chmod +x "$TEMP_DIR/create-dmg"
touch "$TEMP_DIR/.this-is-the-create-dmg-repo"
cp "$CREATE_DMG_SUPPORT_DIR/eula-resources-template.xml" "$TEMP_DIR/support/eula-resources-template.xml"

APPSCRIPT_TEMPLATE_SOURCE="$CREATE_DMG_SUPPORT_DIR/template.applescript"
if [[ -f "$DESKTOP_DIR/spec/create-dmg-template.applescript" ]]; then
  APPSCRIPT_TEMPLATE_SOURCE="$DESKTOP_DIR/spec/create-dmg-template.applescript"
fi

wrap_applescript_template \
  "$APPSCRIPT_TEMPLATE_SOURCE" \
  "$TEMP_DIR/support/template.applescript" \
  "$APPLESCRIPT_TIMEOUT"

if "$TEMP_DIR/create-dmg" "$@"; then
  exit 0
fi

if [[ "${EC_CREATE_DMG_RETRY_SKIP_JENKINS:-1}" != "1" ]]; then
  exit 1
fi

typeset -a forwarded_args
forwarded_args=("$@")
if [[ "${forwarded_args[(Ie)--skip-jenkins]}" -eq 0 ]]; then
  OUTPUT_DMG="${forwarded_args[-2]}"
  rm -f "$OUTPUT_DMG"
  echo "create-dmg Finder automation failed; retrying with --skip-jenkins" >&2
  "$TEMP_DIR/create-dmg" --skip-jenkins "$@"
  exit $?
fi

exit 1
