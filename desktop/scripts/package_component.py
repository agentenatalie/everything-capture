#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_repeated(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [value.strip() for value in values if value and value.strip()]


def create_component_archive(
    *,
    component_id: str,
    version: str,
    source_dir: Path,
    archive_path: Path,
) -> None:
    root_prefix = f"{component_id}-{version}"
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            archive_name = Path(root_prefix) / path.relative_to(source_dir)
            archive.write(path, archive_name.as_posix())


def build_component_metadata(
    *,
    component_id: str,
    title: str,
    description: str,
    version: str,
    archive_path: Path,
    download_url: str,
    requires_restart: bool,
    entry_python_paths: list[str],
    entry_bin_paths: list[str],
    platforms: list[str],
    unavailable_reason: str | None = None,
) -> dict[str, object]:
    return {
        "id": component_id,
        "title": title,
        "description": description,
        "version": version,
        "download_url": download_url,
        "filename": archive_path.name,
        "sha256": sha256sum(archive_path),
        "size_bytes": archive_path.stat().st_size,
        "requires_restart": requires_restart,
        "entry_python_paths": entry_python_paths,
        "entry_bin_paths": entry_bin_paths,
        "platforms": platforms,
        "unavailable_reason": unavailable_reason or "",
    }


def default_archive_name(component_id: str, version: str, platforms: list[str]) -> str:
    platform_suffix = platforms[0] if len(platforms) == 1 else "multi"
    return f"{component_id}-{version}-{platform_suffix}.zip"


def main() -> int:
    parser = argparse.ArgumentParser(description="Package a hosted desktop component bundle and emit metadata JSON.")
    parser.add_argument("--component-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-dir", required=True, help="Directory whose contents become the component payload")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--archive-name")
    parser.add_argument("--download-url", default="")
    parser.add_argument("--metadata-output", required=True)
    parser.add_argument("--platform", action="append", dest="platforms", default=[])
    parser.add_argument("--entry-python-path", action="append", dest="entry_python_paths", default=[])
    parser.add_argument("--entry-bin-path", action="append", dest="entry_bin_paths", default=[])
    parser.add_argument("--requires-restart", action="store_true")
    parser.add_argument("--unavailable-reason", default="")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser().resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"Component source directory not found: {source_dir}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    metadata_output = Path(args.metadata_output).expanduser().resolve()
    platforms = _normalize_repeated(args.platforms) or ["macos-arm64"]
    entry_python_paths = _normalize_repeated(args.entry_python_paths)
    entry_bin_paths = _normalize_repeated(args.entry_bin_paths)
    archive_name = args.archive_name or default_archive_name(args.component_id, args.version, platforms)
    archive_path = output_dir / archive_name

    create_component_archive(
        component_id=args.component_id,
        version=args.version,
        source_dir=source_dir,
        archive_path=archive_path,
    )

    metadata = build_component_metadata(
        component_id=args.component_id,
        title=args.title,
        description=args.description,
        version=args.version,
        archive_path=archive_path,
        download_url=args.download_url.strip(),
        requires_restart=bool(args.requires_restart),
        entry_python_paths=entry_python_paths,
        entry_bin_paths=entry_bin_paths,
        platforms=platforms,
        unavailable_reason=args.unavailable_reason.strip() or None,
    )

    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(metadata_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
