#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import shutil
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement


def _normalize_name(name: str) -> str:
    return name.replace("_", "-").lower()


def _iter_requirement_names(requirements: list[str] | None) -> list[str]:
    resolved: list[str] = []
    environment = default_environment()
    for raw in requirements or []:
        requirement = Requirement(raw)
        if requirement.marker and not requirement.marker.evaluate(environment):
            continue
        resolved.append(_normalize_name(requirement.name))
    return resolved


def _resolve_distributions(root_names: list[str], excluded_names: set[str]) -> list[metadata.Distribution]:
    queue = [_normalize_name(name) for name in root_names]
    seen: set[str] = set()
    ordered: list[metadata.Distribution] = []

    while queue:
        name = queue.pop(0)
        if not name or name in seen or name in excluded_names:
            continue

        distribution = metadata.distribution(name)
        seen.add(name)
        ordered.append(distribution)

        for dependency_name in _iter_requirement_names(distribution.requires):
            if dependency_name not in seen and dependency_name not in excluded_names:
                queue.append(dependency_name)

    return ordered


def _should_skip_relative_path(relative_path: Path) -> bool:
    if "__pycache__" in relative_path.parts:
        return True
    return relative_path.suffix in {".pyc", ".pyo"}


def _copy_distribution_files(distribution: metadata.Distribution, destination_root: Path) -> list[str]:
    copied: list[str] = []
    files = distribution.files or []
    if not files:
        return copied

    source_root = Path(distribution.locate_file("")).resolve()
    for file in files:
        source_path = Path(distribution.locate_file(file)).resolve()
        try:
            relative_path = source_path.relative_to(source_root)
        except ValueError:
            continue

        if _should_skip_relative_path(relative_path):
            continue

        destination_path = destination_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        copied.append(relative_path.as_posix())

    return copied


def _patch_mlx_whisper_timing(python_dir: Path) -> list[str]:
    timing_path = python_dir / "mlx_whisper" / "timing.py"
    if not timing_path.is_file():
        return []

    original = timing_path.read_text(encoding="utf-8")
    updated = (
        original
        .replace("import numba\n", "")
        .replace("@numba.jit(nopython=True)\n", "")
        .replace("@numba.jit(nopython=True, parallel=True)\n", "")
    )
    if updated == original:
        return []

    timing_path.write_text(updated, encoding="utf-8")
    return ["mlx_whisper/timing.py"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage an internal local-transcription component payload from the current Python environment."
    )
    parser.add_argument("--output-dir", required=True, help="Component payload root; python/ will be populated inside it.")
    parser.add_argument(
        "--root-dist",
        action="append",
        dest="root_dists",
        default=[],
        help="Top-level installed distribution to include. Defaults to mlx-whisper.",
    )
    parser.add_argument(
        "--exclude-dist",
        action="append",
        dest="excluded_dists",
        default=[],
        help="Installed distribution to exclude from the staged payload.",
    )
    parser.add_argument(
        "--summary-output",
        help="Optional JSON file that records the staged distributions and copied file count.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    python_dir = output_dir / "python"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    python_dir.mkdir(parents=True, exist_ok=True)

    root_dists = args.root_dists or ["mlx-whisper"]
    excluded = {_normalize_name(name) for name in (args.excluded_dists or [])}
    distributions = _resolve_distributions(root_dists, excluded)

    summary: list[dict[str, object]] = []
    total_files = 0
    for distribution in distributions:
        copied_files = _copy_distribution_files(distribution, python_dir)
        total_files += len(copied_files)
        summary.append(
            {
                "name": distribution.metadata["Name"],
                "version": distribution.version,
                "copied_files": len(copied_files),
            }
        )

    patched_files = _patch_mlx_whisper_timing(python_dir)

    summary_payload = {
        "root_distributions": [_normalize_name(name) for name in root_dists],
        "excluded_distributions": sorted(excluded),
        "staged_distributions": summary,
        "total_files": total_files,
        "python_dir": str(python_dir),
        "patched_files": patched_files,
    }

    if args.summary_output:
        summary_output = Path(args.summary_output).expanduser().resolve()
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    print(json.dumps(summary_payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
