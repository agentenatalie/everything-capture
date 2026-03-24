import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


DESKTOP_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = DESKTOP_DIR / "scripts"


def load_module(module_name: str, module_path: Path):
    if str(module_path.parent) not in sys.path:
        sys.path.insert(0, str(module_path.parent))

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


component_postprocess = load_module(
    "desktop_component_postprocess_test",
    SCRIPTS_DIR / "fix_component_resource_links.py",
)


class ComponentPostprocessTests(unittest.TestCase):
    def test_replace_resource_symlinks_copies_dylib_next_to_metallib(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_path = Path(temp_dir) / "Everything Capture.app"
            source_dylib = Path(temp_dir) / "source" / "libmlx.dylib"
            source_dylib.parent.mkdir(parents=True, exist_ok=True)
            source_dylib.write_text("mlx-dylib", encoding="utf-8")

            dylib_path = (
                app_path
                / "Contents"
                / "Resources"
                / "desktop_runtime"
                / "components"
                / "local-transcription"
                / "0__dot__1__dot__0"
                / "python"
                / "mlx"
                / "lib"
                / "libmlx.dylib"
            )
            dylib_path.parent.mkdir(parents=True, exist_ok=True)
            dylib_path.symlink_to(source_dylib)
            dylib_path.with_name("mlx.metallib").write_text("metal", encoding="utf-8")

            replaced = component_postprocess.replace_resource_symlinks(app_path)

            self.assertEqual(replaced, 1)
            self.assertFalse(dylib_path.is_symlink())
            self.assertEqual(dylib_path.read_text(encoding="utf-8"), "mlx-dylib")

    def test_iter_framework_mlx_core_paths_resolves_unique_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_path = Path(temp_dir) / "Everything Capture.app"
            core_path = (
                app_path
                / "Contents"
                / "Frameworks"
                / "desktop_runtime"
                / "components"
                / "local-transcription"
                / "0__dot__1__dot__0"
                / "python"
                / "mlx"
                / "core.cpython-311-darwin.so"
            )
            core_path.parent.mkdir(parents=True, exist_ok=True)
            core_path.write_text("core", encoding="utf-8")

            duplicate_symlink = (
                app_path
                / "Contents"
                / "Frameworks"
                / "alias"
                / "python"
                / "mlx"
                / "core.cpython-311-darwin.so"
            )
            duplicate_symlink.parent.mkdir(parents=True, exist_ok=True)
            duplicate_symlink.symlink_to(core_path)

            discovered = component_postprocess.iter_framework_mlx_core_paths(app_path)

            self.assertEqual(discovered, (core_path.resolve(),))

    def test_parse_rpaths_extracts_all_rpath_entries(self) -> None:
        sample_output = """
Load command 12
          cmd LC_RPATH
      cmdsize 48
         path @loader_path/../../../../../.. (offset 12)
Load command 13
          cmd LC_RPATH
      cmdsize 32
         path @loader_path/lib (offset 12)
"""
        rpaths = component_postprocess._parse_rpaths(sample_output)
        self.assertEqual(
            rpaths,
            ["@loader_path/../../../../../..", "@loader_path/lib"],
        )


if __name__ == "__main__":
    unittest.main()
