from __future__ import annotations

import logging
import mimetypes
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from paths import (
    MEDIA_OFFLOAD_TYPES,
    MEDIA_S3_ACCESS_KEY_ID,
    MEDIA_S3_BUCKET,
    MEDIA_S3_ENDPOINT,
    MEDIA_S3_REGION,
    MEDIA_S3_SECRET_ACCESS_KEY,
    MEDIA_SIGNED_URL_TTL_SECONDS,
    MEDIA_STORAGE_BACKEND,
    STATIC_DIR,
    TEMP_DIR,
)

logger = logging.getLogger(__name__)

try:
    import boto3
    from botocore.client import Config
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - optional dependency for local-only users
    boto3 = None
    Config = None
    BotoCoreError = ClientError = Exception


@dataclass(frozen=True)
class StorageMetadata:
    storage_backend: str
    storage_key: str
    storage_etag: str | None = None
    storage_uploaded_at: datetime | None = None


def build_media_content_url(media_id: str) -> str:
    return f"/api/media/{media_id}/content"


def _normalize_media_type(media_or_type: object) -> str:
    if isinstance(media_or_type, str):
        return media_or_type.strip().lower()
    return str(getattr(media_or_type, "type", "") or "").strip().lower()


def _get_local_path_value(media: object) -> str:
    return str(getattr(media, "local_path", "") or "").strip()


def _relative_artifact_paths(relative_path: str) -> list[str]:
    value = str(relative_path or "").strip()
    if not value:
        return []

    artifact_paths = [value]
    absolute_path = STATIC_DIR / value
    if absolute_path.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"}:
        stem = absolute_path.stem
        for suffix in (".subtitle.txt", ".transcript.txt"):
            artifact_relative = str(Path(value).with_name(f"{stem}{suffix}"))
            if artifact_relative not in artifact_paths:
                artifact_paths.append(artifact_relative)
    return artifact_paths


def cleanup_relative_paths(relative_paths: list[str]) -> None:
    candidate_dirs: set[Path] = set()
    for relative_path in {path for path in relative_paths if path}:
        absolute_path = STATIC_DIR / relative_path
        if absolute_path.exists():
            try:
                absolute_path.unlink()
            except OSError:
                continue
        current_dir = absolute_path.parent
        while current_dir != STATIC_DIR:
            candidate_dirs.add(current_dir)
            current_dir = current_dir.parent

    for current_dir in sorted(candidate_dirs, key=lambda path: len(path.parts), reverse=True):
        if not current_dir.exists():
            continue
        try:
            current_dir.rmdir()
        except OSError:
            continue


def cleanup_media_local_artifacts(media_entries: list[object]) -> None:
    relative_paths: list[str] = []
    for media in media_entries:
        relative_paths.extend(_relative_artifact_paths(_get_local_path_value(media)))
    cleanup_relative_paths(relative_paths)


def resolve_local_media_path(media: object) -> Path | None:
    local_path = _get_local_path_value(media)
    if not local_path:
        return None
    absolute_path = (STATIC_DIR / local_path).resolve()
    if not absolute_path.exists():
        return None
    return absolute_path


def build_storage_key(local_path: str, media: object | None = None) -> str:
    value = str(local_path or "").strip().lstrip("/")
    if value:
        return value

    item_id = str(getattr(media, "item_id", "") or "").strip()
    user_id = str(getattr(media, "user_id", "") or "").strip()
    media_id = str(getattr(media, "id", "") or "").strip()
    extension = Path(str(getattr(media, "original_url", "") or "")).suffix or ".bin"
    return f"media/users/{user_id or 'unknown-user'}/{item_id or 'unknown-item'}/{media_id or 'media'}{extension}"


def should_offload_media(media: object) -> bool:
    return MEDIA_STORAGE_BACKEND == "s3" and _normalize_media_type(media) in MEDIA_OFFLOAD_TYPES


class MediaStorage:
    def upload_file(self, local_path: Path, media: object) -> StorageMetadata:
        raise NotImplementedError

    def generate_read_url(self, media: object) -> str:
        raise NotImplementedError

    def download_to_temp(self, media: object) -> Path:
        raise NotImplementedError

    def delete_object(self, media: object) -> None:
        raise NotImplementedError

    def has_remote_object(self, media: object) -> bool:
        raise NotImplementedError


class LocalMediaStorage(MediaStorage):
    def upload_file(self, local_path: Path, media: object) -> StorageMetadata:
        return StorageMetadata(storage_backend="local", storage_key=build_storage_key(str(local_path), media))

    def generate_read_url(self, media: object) -> str:
        return ""

    def download_to_temp(self, media: object) -> Path:
        local_path = resolve_local_media_path(media)
        if local_path is None:
            raise FileNotFoundError("Media is not available locally.")
        return local_path

    def delete_object(self, media: object) -> None:
        return None

    def has_remote_object(self, media: object) -> bool:
        return False


class S3CompatibleMediaStorage(MediaStorage):
    def __init__(self) -> None:
        if boto3 is None or Config is None:
            raise RuntimeError("boto3 is required for S3-compatible media storage.")
        missing = [
            name
            for name, value in (
                ("EC_MEDIA_S3_BUCKET", MEDIA_S3_BUCKET),
                ("EC_MEDIA_S3_ENDPOINT", MEDIA_S3_ENDPOINT),
                ("EC_MEDIA_S3_ACCESS_KEY_ID", MEDIA_S3_ACCESS_KEY_ID),
                ("EC_MEDIA_S3_SECRET_ACCESS_KEY", MEDIA_S3_SECRET_ACCESS_KEY),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing S3 media storage config: {', '.join(missing)}")
        self._client = boto3.client(
            "s3",
            endpoint_url=MEDIA_S3_ENDPOINT,
            region_name=MEDIA_S3_REGION,
            aws_access_key_id=MEDIA_S3_ACCESS_KEY_ID,
            aws_secret_access_key=MEDIA_S3_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
        )

    def upload_file(self, local_path: Path, media: object) -> StorageMetadata:
        key = build_storage_key(_get_local_path_value(media), media)
        extra_args = {}
        content_type = mimetypes.guess_type(local_path.name)[0]
        if content_type:
            extra_args["ContentType"] = content_type
        self._client.upload_file(str(local_path), MEDIA_S3_BUCKET, key, ExtraArgs=extra_args or None)
        head = self._client.head_object(Bucket=MEDIA_S3_BUCKET, Key=key)
        etag = str(head.get("ETag") or "").strip('"') or None
        return StorageMetadata(
            storage_backend="s3",
            storage_key=key,
            storage_etag=etag,
            storage_uploaded_at=datetime.utcnow(),
        )

    def generate_read_url(self, media: object) -> str:
        storage_key = str(getattr(media, "storage_key", "") or "").strip()
        if not storage_key:
            raise FileNotFoundError("Media has no remote storage key.")
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": MEDIA_S3_BUCKET, "Key": storage_key},
            ExpiresIn=MEDIA_SIGNED_URL_TTL_SECONDS,
        )

    def download_to_temp(self, media: object) -> Path:
        storage_key = str(getattr(media, "storage_key", "") or "").strip()
        if not storage_key:
            raise FileNotFoundError("Media has no remote storage key.")

        suffix = Path(storage_key).suffix
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        temp_file = tempfile.NamedTemporaryFile(
            prefix="media-download-",
            suffix=suffix,
            dir=str(TEMP_DIR),
            delete=False,
        )
        temp_file.close()
        target_path = Path(temp_file.name)
        self._client.download_file(MEDIA_S3_BUCKET, storage_key, str(target_path))
        return target_path

    def delete_object(self, media: object) -> None:
        storage_key = str(getattr(media, "storage_key", "") or "").strip()
        if not storage_key:
            return
        self._client.delete_object(Bucket=MEDIA_S3_BUCKET, Key=storage_key)

    def has_remote_object(self, media: object) -> bool:
        storage_key = str(getattr(media, "storage_key", "") or "").strip()
        if not storage_key:
            return False
        try:
            self._client.head_object(Bucket=MEDIA_S3_BUCKET, Key=storage_key)
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code") or "")
            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True


_media_storage: MediaStorage | None = None


def get_media_storage() -> MediaStorage:
    global _media_storage
    if _media_storage is None:
        _media_storage = S3CompatibleMediaStorage() if MEDIA_STORAGE_BACKEND == "s3" else LocalMediaStorage()
    return _media_storage


@contextmanager
def materialize_media_file(media: object) -> Iterator[Path]:
    local_path = resolve_local_media_path(media)
    if local_path is not None:
        yield local_path
        return

    storage = get_media_storage()
    temp_path: Path | None = None
    try:
        temp_path = storage.download_to_temp(media)
        yield temp_path
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def offload_media_file(media: object) -> bool:
    if not should_offload_media(media):
        return False

    local_path = resolve_local_media_path(media)
    if local_path is None:
        return False

    storage = get_media_storage()
    metadata = storage.upload_file(local_path, media)
    media.storage_backend = metadata.storage_backend
    media.storage_key = metadata.storage_key
    media.storage_etag = metadata.storage_etag
    media.storage_uploaded_at = metadata.storage_uploaded_at
    return True


def delete_remote_media(media: object) -> None:
    if str(getattr(media, "storage_backend", "") or "").strip().lower() != "s3":
        return
    try:
        get_media_storage().delete_object(media)
    except (BotoCoreError, ClientError, RuntimeError) as exc:
        logger.warning("Failed to delete remote media %s: %s", getattr(media, "id", "unknown"), exc)


def media_has_remote_object(media: object) -> bool:
    if str(getattr(media, "storage_backend", "") or "").strip().lower() != "s3":
        return False
    try:
        return get_media_storage().has_remote_object(media)
    except (BotoCoreError, ClientError, RuntimeError) as exc:
        logger.warning("Failed to inspect remote media %s: %s", getattr(media, "id", "unknown"), exc)
        return False


def media_read_redirect_url(media: object) -> str:
    if media_has_remote_object(media):
        return get_media_storage().generate_read_url(media)

    original_url = str(getattr(media, "original_url", "") or "").strip()
    if original_url:
        return original_url
    raise FileNotFoundError("Media is unavailable.")
