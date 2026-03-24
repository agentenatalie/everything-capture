#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def replace_resource_symlinks(app_path: Path) -> int:
    resources_root = app_path / "Contents" / "Resources" / "desktop_runtime" / "components"
    if not resources_root.is_dir():
        return 0

    replaced = 0
    for dylib_path in resources_root.rglob("*.dylib"):
        if not dylib_path.is_symlink():
            continue

        sibling_metallib = dylib_path.with_name("mlx.metallib")
        if not sibling_metallib.exists():
            continue

        target_path = dylib_path.resolve(strict=False)
        if not target_path.exists():
            continue

        dylib_path.unlink()
        shutil.copy2(target_path, dylib_path)
        replaced += 1

    return replaced


def _parse_rpaths(otool_output: str) -> list[str]:
    rpaths: list[str] = []
    lines = otool_output.splitlines()
    for index, line in enumerate(lines):
        if "cmd LC_RPATH" not in line:
            continue
        for next_line in lines[index + 1 : index + 4]:
            stripped = next_line.strip()
            if not stripped.startswith("path "):
                continue
            rpath = stripped.split("path ", 1)[1].split(" (offset", 1)[0]
            rpaths.append(rpath)
            break
    return rpaths


def _run_command(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def iter_framework_mlx_core_paths(app_path: Path) -> tuple[Path, ...]:
    frameworks_root = app_path / "Contents" / "Frameworks"
    if not frameworks_root.is_dir():
        return ()

    core_paths: list[Path] = []
    seen_paths: set[Path] = set()
    for core_path in frameworks_root.rglob("core*.so"):
        if "python/mlx/" not in core_path.as_posix():
            continue

        resolved_path = core_path.resolve(strict=False)
        if resolved_path in seen_paths:
            continue

        seen_paths.add(resolved_path)
        core_paths.append(resolved_path)

    return tuple(sorted(core_paths))


def read_rpaths(binary_path: Path) -> list[str]:
    output = _run_command(["otool", "-l", str(binary_path)])
    return _parse_rpaths(output)


def patch_framework_mlx_rpaths(app_path: Path) -> int:
    patched = 0
    obsolete_rpath = "@loader_path/../../../../../.."
    expected_rpath = "@loader_path/lib"

    for core_path in iter_framework_mlx_core_paths(app_path):
        current_rpaths = read_rpaths(core_path)
        changed = False

        if obsolete_rpath in current_rpaths:
            subprocess.run(
                ["install_name_tool", "-delete_rpath", obsolete_rpath, str(core_path)],
                check=True,
            )
            changed = True

        if expected_rpath not in current_rpaths:
            subprocess.run(
                ["install_name_tool", "-add_rpath", expected_rpath, str(core_path)],
                check=True,
            )
            changed = True

        if not changed:
            continue

        subprocess.run(
            ["codesign", "--force", "--sign", "-", str(core_path)],
            check=True,
        )
        patched += 1

    return patched


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fix bundled component binaries after PyInstaller packaging."
    )
    parser.add_argument("--app", required=True, help="Path to the built .app bundle.")
    args = parser.parse_args()

    app_path = Path(args.app).expanduser().resolve()
    replaced = replace_resource_symlinks(app_path)
    patched = patch_framework_mlx_rpaths(app_path)
    print(f"replaced={replaced} patched={patched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
