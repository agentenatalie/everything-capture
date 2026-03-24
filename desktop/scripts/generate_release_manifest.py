#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_component_metadata(paths: list[Path]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        components.append(payload)
    return components


def build_app_payload(*, dmg_path: Path, version: str, download_url: str, platform: str = "macos-arm64") -> dict[str, Any]:
    return {
        "platform": platform,
        "version": version,
        "download_url": download_url,
        "filename": dmg_path.name,
        "size_bytes": dmg_path.stat().st_size,
        "sha256": sha256sum(dmg_path),
    }


def build_release_manifest_payload(
    *,
    dmg_path: Path,
    version: str,
    download_url: str,
    components: list[dict[str, Any]],
    platform: str = "macos-arm64",
) -> dict[str, Any]:
    return {
        "generated_at": utcnow_iso(),
        "app": build_app_payload(
            dmg_path=dmg_path,
            version=version,
            download_url=download_url,
            platform=platform,
        ),
        "components": components,
    }


def build_components_manifest_payload(components: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "generated_at": utcnow_iso(),
        "components": components,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate release metadata for the desktop DMG and hosted components.")
    parser.add_argument("dmg_path", help="Path to the notarized desktop DMG.")
    parser.add_argument("output_path", help="Release manifest JSON file to write.")
    parser.add_argument("--version", required=True, help="Desktop app version.")
    parser.add_argument("--download-url", required=True, help="Public CDN URL for the DMG.")
    parser.add_argument("--platform", default="macos-arm64", help="Platform label written to the app manifest.")
    parser.add_argument(
        "--component-json",
        action="append",
        default=[],
        help="Path to a component metadata JSON file produced by package_component.py. Repeatable.",
    )
    parser.add_argument(
        "--components-manifest-output",
        help="Optional hosted components-manifest.json output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    dmg_path = Path(args.dmg_path).resolve()
    output_path = Path(args.output_path).resolve()
    component_paths = [Path(path).expanduser().resolve() for path in args.component_json]
    components = load_component_metadata(component_paths)

    release_payload = build_release_manifest_payload(
        dmg_path=dmg_path,
        version=args.version,
        download_url=args.download_url,
        components=components,
        platform=args.platform,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(release_payload, indent=2), encoding="utf-8")

    if args.components_manifest_output:
        components_manifest_output = Path(args.components_manifest_output).expanduser().resolve()
        components_manifest_output.parent.mkdir(parents=True, exist_ok=True)
        components_manifest_output.write_text(
            json.dumps(build_components_manifest_payload(components), indent=2),
            encoding="utf-8",
        )

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
