# Bundle Resource Manifest

This file documents which non-Python resources must be present in the final macOS app bundle.
The machine-readable source of truth lives in `desktop/spec/bundle_manifest.py`, and both the
PyInstaller spec and bundle verification script import it directly.

## Always bundled

- `frontend/` -> mounted by FastAPI as the desktop UI
- `desktop/launcher/error_page.html` -> startup failure page shown by the launcher
- `desktop/spec/components-manifest.json` -> fallback runtime component catalog used when no hosted manifest URL is configured

## Runtime binaries staged into `desktop/build/runtime/bin/` before PyInstaller runs

- `ffmpeg`
- `media_text_extract`

The build pipeline copies these staged binaries into the bundle destination `desktop_runtime/bin/`.

## Templates and signing metadata used during packaging

- `desktop/spec/EverythingCapture.spec`
- `desktop/spec/Info.plist.template`
- `desktop/spec/entitlements.plist`
- `desktop/spec/bundle-manifest.md`
- `logo/logo-128.svg` -> build-time source used to generate `desktop/build/icon.icns`
- `desktop/spec/icon.icns` if present

If you add another helper binary, model asset, or static runtime file, add it to
`desktop/spec/bundle_manifest.py`, then update this document if the human-readable explanation changed.
