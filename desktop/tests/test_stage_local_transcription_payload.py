import importlib.util
import sys
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


stage_payload = load_module(
    "desktop_stage_local_transcription_payload_test",
    SCRIPTS_DIR / "stage_local_transcription_payload.py",
)


class StageLocalTranscriptionPayloadTests(unittest.TestCase):
    def test_should_skip_bytecode_and_pycache_entries(self) -> None:
        self.assertTrue(stage_payload._should_skip_relative_path(Path("numpy/__pycache__/foo.cpython-311.pyc")))
        self.assertTrue(stage_payload._should_skip_relative_path(Path("numpy/core/foo.pyc")))
        self.assertTrue(stage_payload._should_skip_relative_path(Path("numpy/core/foo.pyo")))
        self.assertFalse(stage_payload._should_skip_relative_path(Path("numpy/core/foo.py")))


if __name__ == "__main__":
    unittest.main()
