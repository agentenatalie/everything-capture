#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
load_dotenv(BACKEND_DIR / ".local" / "capture_service.env", override=False)
sys.path.insert(0, str(BACKEND_DIR))

from database import SessionLocal  # noqa: E402
from models import Item, Media  # noqa: E402
from paths import MEDIA_STORAGE_BACKEND  # noqa: E402
from routers.ingest import _replace_media_urls_in_blocks, _replace_media_urls_in_html  # noqa: E402
from services.media_storage import build_media_content_url, cleanup_media_local_artifacts, offload_media_file, resolve_local_media_path  # noqa: E402


logger = logging.getLogger("migrate_video_media_to_cloud")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _rewrite_item_video_urls(item: Item, url_map: dict[str, str]) -> None:
    if item.content_blocks_json:
        try:
            content_blocks = json.loads(item.content_blocks_json)
        except json.JSONDecodeError:
            content_blocks = None
        replaced_blocks = _replace_media_urls_in_blocks(content_blocks, url_map)
        if replaced_blocks is not None:
            item.content_blocks_json = replaced_blocks

    if item.canonical_html:
        replaced_html = _replace_media_urls_in_html(item.canonical_html, url_map)
        if replaced_html is not None:
            item.canonical_html = replaced_html


def migrate_item_videos(item: Item, *, dry_run: bool = False) -> tuple[int, int, list[Media]]:
    migrated_count = 0
    skipped_count = 0
    offloaded_media: list[Media] = []
    url_map: dict[str, str] = {}

    for media in sorted(item.media or [], key=lambda entry: (entry.display_order, entry.id or "")):
        if media.type != "video":
            continue
        if str(media.storage_backend or "").strip().lower() == "s3" and str(media.storage_key or "").strip():
            skipped_count += 1
            continue
        if not media.local_path:
            skipped_count += 1
            continue
        if resolve_local_media_path(media) is None:
            logger.warning("Skip missing local video for media %s (%s)", media.id, media.local_path)
            skipped_count += 1
            continue

        media_content_url = build_media_content_url(media.id)
        if media.original_url:
            url_map[media.original_url] = media_content_url
        url_map[f"/static/{media.local_path}"] = media_content_url

        if dry_run:
            migrated_count += 1
            continue

        if not offload_media_file(media):
            raise RuntimeError(
                "Video offload is disabled or unavailable. Set EC_MEDIA_STORAGE_BACKEND=s3 before running migration."
            )
        offloaded_media.append(media)
        migrated_count += 1

    if url_map:
        _rewrite_item_video_urls(item, url_map)

    return migrated_count, skipped_count, offloaded_media


def migrate_orphan_video_media(media: Media, *, dry_run: bool = False) -> tuple[int, int, list[Media]]:
    if media.type != "video":
        return 0, 1, []
    if str(media.storage_backend or "").strip().lower() == "s3" and str(media.storage_key or "").strip():
        return 0, 1, []
    if not media.local_path:
        return 0, 1, []
    if resolve_local_media_path(media) is None:
        logger.warning("Skip missing local orphan video for media %s (%s)", media.id, media.local_path)
        return 0, 1, []
    if dry_run:
        return 1, 0, []
    if not offload_media_file(media):
        raise RuntimeError(
            "Video offload is disabled or unavailable. Set EC_MEDIA_STORAGE_BACKEND=s3 before running migration."
        )
    return 1, 0, [media]


def main() -> int:
    parser = argparse.ArgumentParser(description="Offload local Everything Capture videos to cloud object storage.")
    parser.add_argument("--limit", type=int, default=0, help="Max items to process (0 = all).")
    parser.add_argument("--item-id", type=str, default="", help="Only migrate a specific item.")
    parser.add_argument("--dry-run", action="store_true", help="Preview migration without uploading or deleting local files.")
    args = parser.parse_args()

    if not args.dry_run and MEDIA_STORAGE_BACKEND != "s3":
        logger.error("EC_MEDIA_STORAGE_BACKEND must be set to 's3' before running migration.")
        return 2

    processed_items = 0
    migrated_videos = 0
    skipped_videos = 0

    with SessionLocal() as db:
        query = db.query(Item).options(selectinload(Item.media)).join(Media).filter(Media.type == "video").distinct()
        if args.item_id:
            query = query.filter(Item.id == args.item_id.strip())
        items = query.order_by(Item.created_at.asc()).all()

        if args.limit > 0:
            items = items[: args.limit]

        for item in items:
            try:
                migrated_count, skipped_count, offloaded_media = migrate_item_videos(item, dry_run=args.dry_run)
                if migrated_count and not args.dry_run:
                    db.add(item)
                    db.commit()
                    if offloaded_media:
                        cleanup_media_local_artifacts(offloaded_media)
                elif migrated_count and args.dry_run:
                    db.rollback()
                else:
                    db.rollback()

                processed_items += 1
                migrated_videos += migrated_count
                skipped_videos += skipped_count
                logger.info(
                    "Processed item %s: migrated=%d skipped=%d dry_run=%s",
                    item.id,
                    migrated_count,
                    skipped_count,
                    args.dry_run,
                )
            except Exception as exc:
                db.rollback()
                logger.exception("Failed to migrate videos for item %s: %s", item.id, exc)

        orphan_media = (
            db.query(Media)
            .outerjoin(Item, Item.id == Media.item_id)
            .filter(Media.type == "video")
            .filter(Item.id.is_(None))
            .filter(or_(Media.storage_backend.is_(None), Media.storage_backend == "", Media.storage_backend != "s3"))
            .order_by(Media.id.asc())
            .all()
        )
        for media in orphan_media:
            try:
                migrated_count, skipped_count, offloaded_media = migrate_orphan_video_media(media, dry_run=args.dry_run)
                if migrated_count and not args.dry_run:
                    db.add(media)
                    db.commit()
                    if offloaded_media:
                        cleanup_media_local_artifacts(offloaded_media)
                elif migrated_count and args.dry_run:
                    db.rollback()
                else:
                    db.rollback()

                migrated_videos += migrated_count
                skipped_videos += skipped_count
                logger.info(
                    "Processed orphan media %s: migrated=%d skipped=%d dry_run=%s",
                    media.id,
                    migrated_count,
                    skipped_count,
                    args.dry_run,
                )
            except Exception as exc:
                db.rollback()
                logger.exception("Failed to migrate orphan media %s: %s", media.id, exc)

    logger.info(
        "Video migration finished: items=%d migrated_videos=%d skipped_videos=%d dry_run=%s",
        processed_items,
        migrated_videos,
        skipped_videos,
        args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
