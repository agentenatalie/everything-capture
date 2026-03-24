#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a bundled desktop components manifest.")
    parser.add_argument("--output", required=True, help="Manifest JSON file to write.")
    parser.add_argument("--version", required=True, help="Bundled component version.")
    parser.add_argument("--component-root", required=True, help="Bundled component directory to validate.")
    parser.add_argument("--platform", default="macos-arm64")
    parser.add_argument("--component-id", default="local-transcription")
    parser.add_argument("--title", default="Local Transcription")
    parser.add_argument(
        "--description",
        default="为视频启用本地音频转录。该能力已随桌面应用内置，无需单独安装。",
    )
    parser.add_argument(
        "--entry-python-path",
        action="append",
        dest="entry_python_paths",
        default=[],
    )
    parser.add_argument(
        "--entry-bin-path",
        action="append",
        dest="entry_bin_paths",
        default=[],
    )
    args = parser.parse_args()

    component_root = Path(args.component_root).expanduser().resolve()
    if not component_root.is_dir():
        raise SystemExit(f"Bundled component directory not found: {component_root}")

    entry_python_paths = [path.strip() for path in args.entry_python_paths if path.strip()] or ["python"]
    entry_bin_paths = [path.strip() for path in args.entry_bin_paths if path.strip()]

    missing_paths = [
        path
        for path in entry_python_paths + entry_bin_paths
        if not (component_root / path).exists()
    ]
    if missing_paths:
        raise SystemExit(
            f"Bundled component directory is missing required paths: {', '.join(sorted(missing_paths))}"
        )

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "components": [
                    {
                        "id": args.component_id,
                        "title": args.title,
                        "description": args.description,
                        "version": args.version,
                        "download_url": "",
                        "sha256": "",
                        "size_bytes": 0,
                        "requires_restart": False,
                        "entry_python_paths": entry_python_paths,
                        "entry_bin_paths": entry_bin_paths,
                        "platforms": [args.platform],
                        "unavailable_reason": "",
                        "bundled": True,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
