import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, PROJECT_ROOT)

from models import Item, Media  # noqa: E402
from scripts.migrate_video_media_to_cloud import migrate_item_videos, migrate_orphan_video_media  # noqa: E402


class VideoMediaMigrationTests(unittest.TestCase):
    @patch("scripts.migrate_video_media_to_cloud.resolve_local_media_path", return_value=Path("/tmp/video_000.mp4"))
    @patch("scripts.migrate_video_media_to_cloud.offload_media_file", return_value=True)
    def test_migrate_item_videos_rewrites_static_urls_to_media_endpoint(self, mock_offload, mock_local_path) -> None:
        item = Item(
            id="item-migrate-1",
            content_blocks_json=json.dumps(
                [{"type": "video", "url": "/static/media/users/test-user/item-migrate-1/video_000.mp4"}]
            ),
            canonical_html='<video src="/static/media/users/test-user/item-migrate-1/video_000.mp4"></video>',
        )
        item.media = [
            Media(
                id="media-video-1",
                item_id=item.id,
                type="video",
                original_url="https://cdn.example.com/video_000.mp4",
                local_path="media/users/test-user/item-migrate-1/video_000.mp4",
                display_order=0,
            )
        ]

        migrated_count, skipped_count, offloaded_media = migrate_item_videos(item)

        self.assertEqual(migrated_count, 1)
        self.assertEqual(skipped_count, 0)
        self.assertEqual(offloaded_media, [item.media[0]])
        self.assertIn("/api/media/media-video-1/content", item.content_blocks_json or "")
        self.assertIn("/api/media/media-video-1/content", item.canonical_html or "")
        mock_local_path.assert_called_once()
        mock_offload.assert_called_once_with(item.media[0])

    @patch("scripts.migrate_video_media_to_cloud.resolve_local_media_path", return_value=Path("/tmp/video_000.mp4"))
    @patch("scripts.migrate_video_media_to_cloud.offload_media_file", return_value=False)
    def test_migrate_item_videos_raises_when_offload_is_disabled(self, mock_offload, mock_local_path) -> None:
        item = Item(id="item-migrate-2")
        item.media = [
            Media(
                id="media-video-2",
                item_id=item.id,
                type="video",
                local_path="media/users/test-user/item-migrate-2/video_000.mp4",
                display_order=0,
            )
        ]

        with self.assertRaises(RuntimeError):
            migrate_item_videos(item)

        mock_local_path.assert_called_once()
        mock_offload.assert_called_once_with(item.media[0])

    @patch("scripts.migrate_video_media_to_cloud.resolve_local_media_path", return_value=Path("/tmp/video_000.mp4"))
    @patch("scripts.migrate_video_media_to_cloud.offload_media_file", return_value=True)
    def test_migrate_orphan_video_media_uploads_directly(self, mock_offload, mock_local_path) -> None:
        media = Media(
            id="media-orphan-1",
            item_id="missing-item",
            type="video",
            local_path="media/users/test-user/missing-item/video_000.mp4",
            display_order=0,
        )

        migrated_count, skipped_count, offloaded_media = migrate_orphan_video_media(media)

        self.assertEqual(migrated_count, 1)
        self.assertEqual(skipped_count, 0)
        self.assertEqual(offloaded_media, [media])
        mock_local_path.assert_called_once_with(media)
        mock_offload.assert_called_once_with(media)
