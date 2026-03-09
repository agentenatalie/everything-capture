import os
import sys
import unittest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from routers.items import _cleanup_item_media_files  # noqa: E402
from paths import STATIC_DIR  # noqa: E402


class ItemStorageTests(unittest.TestCase):
    def test_cleanup_item_media_files_removes_empty_parent_directories(self) -> None:
        relative_path = "media/users/test-user/test-item/image_000.webp"
        absolute_path = STATIC_DIR / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(b"image-data")

        self.assertTrue(absolute_path.exists())

        _cleanup_item_media_files([relative_path])

        self.assertFalse(absolute_path.exists())
        self.assertFalse((STATIC_DIR / "media" / "users" / "test-user" / "test-item").exists())


if __name__ == "__main__":
    unittest.main()
