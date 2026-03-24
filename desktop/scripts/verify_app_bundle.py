from __future__ import annotations

import argparse
import plistlib
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DESKTOP_DIR = SCRIPT_DIR.parent
SPEC_DIR = DESKTOP_DIR / "spec"

if str(SPEC_DIR) not in sys.path:
    sys.path.insert(0, str(SPEC_DIR))

from bundle_manifest import bundle_data_entries, runtime_bundle_entries


class BundleVerificationError(RuntimeError):
    pass


def _candidate_bundle_roots(app_path: Path) -> tuple[Path, ...]:
    return (
        app_path / "Contents" / "MacOS",
        app_path / "Contents" / "Resources",
    )


def _find_bundle_path(app_path: Path, relative_path: str) -> Path | None:
    relative = Path(relative_path)
    for root in _candidate_bundle_roots(app_path):
        candidate = root / relative
        if candidate.exists():
            return candidate
    return None


def verify_app_bundle(app_path: Path, *, version: str | None = None) -> None:
    if not app_path.is_dir():
        raise BundleVerificationError(f"App bundle not found: {app_path}")

    info_plist_path = app_path / "Contents" / "Info.plist"
    if not info_plist_path.is_file():
        raise BundleVerificationError(f"Missing Info.plist: {info_plist_path}")

    info_plist = plistlib.loads(info_plist_path.read_bytes())
    if version and info_plist.get("CFBundleShortVersionString") != version:
        raise BundleVerificationError(
            "Info.plist CFBundleShortVersionString "
            f"expected {version!r}, got {info_plist.get('CFBundleShortVersionString')!r}"
        )

    executable_name = info_plist.get("CFBundleExecutable") or "EverythingCapture"
    executable_path = app_path / "Contents" / "MacOS" / executable_name
    if not executable_path.is_file():
        raise BundleVerificationError(f"Missing app executable: {executable_path}")

    project_root = DESKTOP_DIR.parent
    missing_entries: list[str] = []
    for entry in bundle_data_entries(project_root, DESKTOP_DIR) + runtime_bundle_entries(DESKTOP_DIR):
        if _find_bundle_path(app_path, entry.bundle_path) is None:
            missing_entries.append(f"{entry.bundle_path} ({entry.description})")

    if missing_entries:
        details = "\n".join(f"- {entry}" for entry in missing_entries)
        raise BundleVerificationError(f"App bundle is missing required resources:\n{details}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the packaged Everything Capture .app bundle.")
    parser.add_argument("--app", required=True, help="Path to the built .app bundle")
    parser.add_argument("--version", help="Expected CFBundleShortVersionString value")
    args = parser.parse_args()

    verify_app_bundle(Path(args.app).expanduser().resolve(), version=args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
