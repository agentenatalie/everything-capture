"""
媒体文件下载服务
下载图片（小红书）和视频（抖音）到本地存储
"""

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx
from paths import MEDIA_DIR

try:
    import yt_dlp
except ImportError:  # pragma: no cover - optional dependency at runtime
    yt_dlp = None

logger = logging.getLogger(__name__)

MEDIA_ROOT = MEDIA_DIR

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)


def _looks_like_downloadable_media(content_type: str, media_type: str) -> bool:
    normalized = (content_type or "").split(";")[0].strip().lower()
    if not normalized:
        return True
    if normalized in {"text/html", "text/plain", "application/json", "application/javascript"}:
        return False
    if media_type in {"image", "cover"}:
        return normalized.startswith("image/") or normalized == "application/octet-stream"
    if media_type == "video":
        return normalized.startswith("video/") or normalized in {"application/octet-stream", "binary/octet-stream"}
    return True


def _is_ytdlp_candidate(url: str, media_type: str) -> bool:
    if media_type != "video":
        return False
    host = (urlparse(url).hostname or "").lower()
    return host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "youtu.be",
        "www.youtu.be",
        "vimeo.com",
        "www.vimeo.com",
        "player.vimeo.com",
    }


def _download_with_ytdlp_sync(url: str, save_path: Path, referer: str = "") -> tuple[Path | None, int]:
    if yt_dlp is None:
        return None, 0

    save_path.parent.mkdir(parents=True, exist_ok=True)
    outtmpl = str(save_path.with_suffix(".%(ext)s"))
    headers = {"User-Agent": _MOBILE_UA}
    if referer:
        headers["Referer"] = referer

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": True,
        "noprogress": True,
        "outtmpl": {"default": outtmpl},
        "format": "best[ext=mp4]/best",
        "http_headers": headers,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        final_path = None

        requested = info.get("requested_downloads") if isinstance(info, dict) else None
        if isinstance(requested, list):
            for item in requested:
                filepath = item.get("filepath") if isinstance(item, dict) else None
                if filepath:
                    final_path = Path(filepath)
                    break

        if final_path is None and isinstance(info, dict):
            filename = info.get("_filename")
            if filename:
                final_path = Path(filename)

        if final_path is None:
            matches = sorted(save_path.parent.glob(f"{save_path.stem}.*"))
            final_path = matches[0] if matches else None

        if not final_path or not final_path.exists():
            return None, 0

        return final_path, final_path.stat().st_size


async def _download_with_ytdlp(url: str, save_path: Path, referer: str = "") -> tuple[Path | None, int]:
    try:
        return await asyncio.to_thread(_download_with_ytdlp_sync, url, save_path, referer)
    except Exception as e:
        logger.warning("yt-dlp 下载失败 %s: %s", url[:80], e)
        for candidate in save_path.parent.glob(f"{save_path.stem}.*"):
            try:
                candidate.unlink()
            except OSError:
                pass
        return None, 0


def _probe_video_duration_with_ytdlp_sync(url: str, referer: str = "") -> int | None:
    if yt_dlp is None:
        return None

    headers = {"User-Agent": _MOBILE_UA}
    if referer:
        headers["Referer"] = referer

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "http_headers": headers,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        duration = info.get("duration") if isinstance(info, dict) else None
        try:
            return int(duration) if duration is not None else None
        except (TypeError, ValueError):
            return None


async def probe_video_duration_seconds(url: str, media_type: str, referer: str = "") -> int | None:
    if not _is_ytdlp_candidate(url, media_type):
        return None
    try:
        return await asyncio.to_thread(_probe_video_duration_with_ytdlp_sync, url, referer)
    except Exception as exc:
        logger.warning("视频时长探测失败 %s: %s", url[:80], exc)
        return None


async def download_file(url: str, save_path: Path, media_type: str, referer: str = "") -> tuple[Path | None, int]:
    """下载单个文件，返回 (实际文件路径, 文件大小)。失败返回 (None, 0)。"""
    try:
        if _is_ytdlp_candidate(url, media_type):
            ytdlp_path, ytdlp_size = await _download_with_ytdlp(url, save_path, referer=referer)
            if ytdlp_size > 0 and ytdlp_path:
                logger.info("yt-dlp 下载完成: %s (%d bytes)", ytdlp_path.name, ytdlp_size)
                return ytdlp_path, ytdlp_size

        headers = {"User-Agent": _MOBILE_UA}
        if referer:
            headers["Referer"] = referer
        async with httpx.AsyncClient(
            headers=headers, follow_redirects=True, timeout=60
        ) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if not _looks_like_downloadable_media(content_type, media_type):
                    logger.info("跳过非媒体响应: %s (%s)", url, content_type)
                    return None, 0
                save_path.parent.mkdir(parents=True, exist_ok=True)
                total = 0
                with open(save_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        total += len(chunk)
                logger.info("下载完成: %s (%d bytes)", save_path.name, total)
                return save_path, total
    except Exception as e:
        logger.warning("下载失败 %s: %s", url[:80], e)
        # 清理不完整的文件
        if save_path.exists():
            save_path.unlink()
        return None, 0


def get_extension(url: str, media_type: str) -> str:
    """从 URL 或类型推断文件扩展名"""
    url_lower = url.lower()
    
    # 1. 针对微信等带有明确格式参数的链接
    if "wx_fmt=gif" in url_lower:
        return ".gif"
    if "wx_fmt=png" in url_lower:
        return ".png"
    if "wx_fmt=jpeg" in url_lower or "wx_fmt=jpg" in url_lower:
        return ".jpg"
    if "wx_fmt=webp" in url_lower:
        return ".webp"

    # 2. 从路径匹配常见后缀名
    path_lower = url_lower.split("?")[0]
    for ext in (".mp4", ".webm", ".mov", ".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if path_lower.endswith(ext):
            return ext

    # 3. 容错匹配（路径里包含.gif 等）
    for ext in (".mp4", ".webm", ".mov", ".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if ext in url_lower:
            return ".jpg" if ext == ".jpeg" else ext

    # 4. 根据类型给默认后缀
    if media_type == "video":
        return ".mp4"
    return ".webp"


def should_keep_external_media(url: str, media_type: str) -> bool:
    if media_type not in {"video", "cover"}:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "youtu.be",
        "www.youtu.be",
        "vimeo.com",
        "www.vimeo.com",
        "player.vimeo.com",
    }


async def download_media_list(
    item_id: str,
    media_list: list[dict],
    referer: str = "",
    user_id: str | None = None,
) -> list[dict]:
    """
    批量下载媒体文件。

    media_list: [{"type": "image"|"video"|"cover", "url": "...", "order": 0}, ...]

    返回: [{"type", "original_url", "local_path", "file_size", "display_order"}, ...]
    """
    results = []
    path_parts = ["users", user_id, item_id] if user_id else [item_id]
    item_dir = MEDIA_ROOT.joinpath(*path_parts)

    for media in media_list:
        url = media.get("url", "")
        mtype = media.get("type", "image")
        order = media.get("order", 0)

        if not url:
            continue

        ext = get_extension(url, mtype)
        filename = f"{mtype}_{order:03d}{ext}"
        save_path = item_dir / filename

        final_path, file_size = await download_file(url, save_path, mtype, referer=referer)
        if file_size > 0 and final_path:
            # 存储相对于 static/ 的路径，用于 URL 访问
            relative_path = f"media/{'/'.join(path_parts)}/{final_path.name}"
            results.append({
                "type": mtype,
                "original_url": url,
                "local_path": relative_path,
                "file_size": file_size,
                "display_order": order,
                "inline_position": media.get("inline_position", -1.0),
            })
        elif should_keep_external_media(url, mtype):
            logger.info("保留外部媒体引用（无法直接下载）: %s", url)
            results.append({
                "type": mtype,
                "original_url": url,
                "local_path": "",
                "file_size": 0,
                "display_order": order,
                "inline_position": media.get("inline_position", -1.0),
            })

    return results
