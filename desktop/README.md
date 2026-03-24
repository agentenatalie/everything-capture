# Desktop Packaging

This directory contains the macOS desktop packaging layer only.

- `launcher/`: desktop entrypoint and startup UX
- `build/`: disposable build outputs and staging artifacts only
- `scripts/`: build, sign, notarize, and release helpers
- `spec/`: PyInstaller spec, bundle templates, and bundle resource manifest

Build outputs are intentionally isolated under `desktop/build/` so the directory can be deleted and recreated at any time.

## Phase 2 build flow

1. Install desktop-only build dependencies:
   - `desktop/scripts/install_build_deps.sh`
2. Run the packaging preflight on an Apple Silicon Mac:
   - `EC_FFMPEG_SOURCE=/path/to/ffmpeg desktop/scripts/preflight_desktop.sh`
3. Build the `.app` and `.dmg`:
   - `EC_FFMPEG_SOURCE=/path/to/ffmpeg desktop/scripts/build_desktop.sh`

`build_desktop.sh` now assumes the environment is already prepared. It does not install Python
packages for you, and it verifies the built `.app` contents before creating the DMG.
If `create-dmg` is installed, the generated DMG includes a Finder drag-to-Applications layout.
The DMG background artwork is generated from `desktop/spec/dmg-background.svg`, which should
follow the same visual language as the product logo.
If Finder automation times out on the build machine, the wrapper retries with `--skip-jenkins`
so the DMG still contains an `Applications` link instead of failing outright.
Without `create-dmg`, the script falls back to a plain `hdiutil` DMG.

## Phase 4 release flow

1. Build optional hosted component payloads if needed:
   - Prepare a staged payload directory that already contains the component runtime, for example `python/` for `local-transcription`
   - Package it with `desktop/scripts/build_local_transcription_component.sh`
2. Export component metadata JSON paths via `EC_COMPONENT_METADATA_PATHS=/abs/one.json,/abs/two.json`
3. Provide the public DMG URL with `EC_RELEASE_DOWNLOAD_URL=...`
4. Run `desktop/scripts/release_desktop.sh`

`release_desktop.sh` orchestrates:
- desktop build
- app signing
- DMG notarization/stapling
- release manifest generation
- hosted `components-manifest.json` generation

The hosted component manifest is generated from metadata JSON files produced by
`desktop/scripts/package_component.py` or the `build_local_transcription_component.sh` wrapper.
