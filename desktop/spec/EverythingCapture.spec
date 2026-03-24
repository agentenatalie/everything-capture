# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
DESKTOP_ROOT = SPEC_DIR.parent
PROJECT_ROOT = DESKTOP_ROOT.parent
ICON_PATH = DESKTOP_ROOT / "spec" / "icon.icns"
SPEC_ROOT = DESKTOP_ROOT / "spec"

if str(SPEC_ROOT) not in sys.path:
    sys.path.insert(0, str(SPEC_ROOT))

from bundle_manifest import bundle_data_entries, runtime_bundle_entries

datas = [
    (str(entry.source), entry.destination)
    for entry in bundle_data_entries(PROJECT_ROOT, DESKTOP_ROOT)
]

binaries = []
for entry in runtime_bundle_entries(DESKTOP_ROOT):
    if entry.source.exists():
        binaries.append((str(entry.source), entry.destination))

hiddenimports = collect_submodules("routers") + collect_submodules("services")

a = Analysis(
    [str(DESKTOP_ROOT / "launcher" / "app.py")],
    pathex=[
        str(DESKTOP_ROOT / "launcher"),
        str(PROJECT_ROOT / "backend"),
        str(PROJECT_ROOT),
    ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EverythingCapture",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="EverythingCapture",
)
app = BUNDLE(
    coll,
    name="Everything Capture.app",
    icon=str(ICON_PATH) if ICON_PATH.exists() else None,
    bundle_identifier="com.everythingcapture.desktop",
)
