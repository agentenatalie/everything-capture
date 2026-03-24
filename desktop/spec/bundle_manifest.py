from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BundleEntry:
    source: Path
    destination: str
    bundle_path: str
    description: str
    required: bool = True


def runtime_components_manifest_entry(desktop_root: Path) -> BundleEntry:
    runtime_manifest_path = desktop_root / "build" / "runtime" / "components-manifest.json"
    if runtime_manifest_path.is_file():
        return BundleEntry(
            source=runtime_manifest_path,
            destination="desktop/spec",
            bundle_path="desktop/spec/components-manifest.json",
            description="Bundled runtime component catalog",
        )

    return BundleEntry(
        source=desktop_root / "spec" / "components-manifest.json",
        destination="desktop/spec",
        bundle_path="desktop/spec/components-manifest.json",
        description="Fallback runtime component catalog",
    )


def staged_component_entries(desktop_root: Path) -> tuple[BundleEntry, ...]:
    runtime_components_dir = desktop_root / "build" / "runtime" / "components"
    if not runtime_components_dir.is_dir():
        return ()

    entries: list[BundleEntry] = []
    for component_dir in sorted(runtime_components_dir.iterdir()):
        if not component_dir.is_dir():
            continue
        entries.append(
            BundleEntry(
                source=component_dir,
                destination=f"desktop_runtime/components/{component_dir.name}",
                bundle_path=f"desktop_runtime/components/{component_dir.name}",
                description=f"Bundled runtime payload for {component_dir.name}",
            )
        )
    return tuple(entries)


def bundle_data_entries(project_root: Path, desktop_root: Path) -> tuple[BundleEntry, ...]:
    return (
        BundleEntry(
            source=project_root / "frontend",
            destination="frontend",
            bundle_path="frontend",
            description="FastAPI desktop frontend",
        ),
        BundleEntry(
            source=desktop_root / "launcher" / "error_page.html",
            destination="desktop/launcher",
            bundle_path="desktop/launcher/error_page.html",
            description="Startup failure page shown by the launcher",
        ),
        runtime_components_manifest_entry(desktop_root),
    ) + staged_component_entries(desktop_root)


def staged_runtime_binary_entries(desktop_root: Path) -> tuple[BundleEntry, ...]:
    runtime_bin_dir = desktop_root / "build" / "runtime" / "bin"
    return (
        BundleEntry(
            source=runtime_bin_dir / "ffmpeg",
            destination="desktop_runtime/bin",
            bundle_path="desktop_runtime/bin/ffmpeg",
            description="Bundled ffmpeg binary",
        ),
        BundleEntry(
            source=runtime_bin_dir / "media_text_extract",
            destination="desktop_runtime/bin",
            bundle_path="desktop_runtime/bin/media_text_extract",
            description="Bundled OCR helper",
        ),
    )


def packaging_support_entries(desktop_root: Path) -> tuple[BundleEntry, ...]:
    spec_root = desktop_root / "spec"
    project_root = desktop_root.parent
    return (
        BundleEntry(
            source=spec_root / "EverythingCapture.spec",
            destination="desktop/spec",
            bundle_path="desktop/spec/EverythingCapture.spec",
            description="PyInstaller spec file",
        ),
        BundleEntry(
            source=spec_root / "Info.plist.template",
            destination="desktop/spec",
            bundle_path="desktop/spec/Info.plist.template",
            description="Info.plist template",
        ),
        BundleEntry(
            source=spec_root / "entitlements.plist",
            destination="desktop/spec",
            bundle_path="desktop/spec/entitlements.plist",
            description="Codesign entitlements",
        ),
        BundleEntry(
            source=spec_root / "bundle-manifest.md",
            destination="desktop/spec",
            bundle_path="desktop/spec/bundle-manifest.md",
            description="Human-readable bundle manifest",
        ),
        BundleEntry(
            source=project_root / "logo" / "logo-128.svg",
            destination="logo",
            bundle_path="logo/logo-128.svg",
            description="App icon source SVG used to generate the macOS .icns asset",
        ),
        BundleEntry(
            source=spec_root / "icon.icns",
            destination="desktop/spec",
            bundle_path="desktop/spec/icon.icns",
            description="Optional app icon",
            required=False,
        ),
    )


def required_source_entries(project_root: Path, desktop_root: Path) -> tuple[BundleEntry, ...]:
    return bundle_data_entries(project_root, desktop_root) + packaging_support_entries(desktop_root)


def runtime_bundle_entries(desktop_root: Path) -> tuple[BundleEntry, ...]:
    return staged_runtime_binary_entries(desktop_root)
