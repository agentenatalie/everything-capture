"""
媒体文件下载服务
下载图片（小红书）和视频（抖音）到本地存储
"""

import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from paths import MEDIA_DIR
from tenant import DEFAULT_USER_ID

try:
    import yt_dlp
except ImportError:  # pragma: no cover - optional dependency at runtime
    yt_dlp = None

logger = logging.getLogger(__name__)

MEDIA_ROOT = MEDIA_DIR
_RESUMABLE_DOWNLOAD_ERRORS = (
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)
_MAX_RESUME_ATTEMPTS = 8

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
        "douyin.com",
        "www.douyin.com",
        "m.douyin.com",
        "v.douyin.com",
        "iesdouyin.com",
        "www.iesdouyin.com",
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


def _should_retry_video_via_referer_page(url: str, media_type: str, referer: str) -> bool:
    if media_type != "video" or not referer or not _is_ytdlp_candidate(referer, "video"):
        return False

    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False

    return (
        host.endswith("snssdk.com")
        or host.endswith("zjcdn.com")
        or host.endswith("douyinvod.com")
        or host.endswith("idouyinvod.com")
    )


async def _resolve_video_redirect_url(
    client: httpx.AsyncClient,
    url: str,
    media_type: str,
    referer: str,
) -> str:
    if not _should_retry_video_via_referer_page(url, media_type, referer):
        return url

    try:
        response = await client.get(url, follow_redirects=False)
    except Exception as exc:
        logger.debug("视频跳转预解析失败 %s: %s", url[:80], exc)
        return url

    if 300 <= response.status_code < 400:
        location = response.headers.get("location", "")
        if location:
            return str(response.url.join(location))
    return url


def _expected_total_size(headers: httpx.Headers, downloaded: int, current_total: int | None = None) -> int | None:
    content_range = headers.get("content-range", "")
    if "/" in content_range:
        total_str = content_range.rsplit("/", 1)[1].strip()
        if total_str.isdigit():
            return int(total_str)

    content_length = headers.get("content-length", "")
    if content_length.isdigit():
        length = int(content_length)
        return downloaded + length if downloaded > 0 else length

    return current_total


def _parse_vtt_text(vtt_path: Path) -> str:
    """Parse a WebVTT subtitle file into plain text, stripping timestamps and inline tags."""
    from services.content_extraction import parse_subtitle_lines

    try:
        content = vtt_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return parse_subtitle_lines(content)


def _save_subtitle_companion(video_path: Path) -> None:
    """Convert any downloaded VTT subtitle files into a plain-text companion file."""
    stem = video_path.stem
    parent = video_path.parent
    companion = parent / f"{stem}.subtitle.txt"
    if companion.exists():
        return
    vtt_files = sorted(parent.glob(f"{stem}*.vtt"))
    if not vtt_files:
        return
    text = _parse_vtt_text(vtt_files[0])
    if text:
        try:
            companion.write_text(text, encoding="utf-8")
            logger.info("字幕已保存: %s", companion.name)
        except OSError as exc:
            logger.debug("字幕伴生文件写入失败: %s", exc)
    for vtt in vtt_files:
        try:
            vtt.unlink()
        except OSError:
            pass


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
        # Subtitle extraction (priority over audio OCR)
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["all", "-live_chat"],
        "subtitlesformat": "vtt",
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

        _save_subtitle_companion(final_path)
        return final_path, final_path.stat().st_size


def _fetch_subtitles_only_sync(url: str, video_path: Path, referer: str = "") -> None:
    """Fetch subtitles only (skip video download) using yt-dlp from a share page URL."""
    if yt_dlp is None:
        return

    companion = video_path.parent / f"{video_path.stem}.subtitle.txt"
    if companion.exists():
        return

    headers = {"User-Agent": _MOBILE_UA}
    if referer:
        headers["Referer"] = referer

    outtmpl = str(video_path.with_suffix(".%(ext)s"))
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["all", "-live_chat"],
        "subtitlesformat": "vtt",
        "outtmpl": {"default": outtmpl},
        "http_headers": headers,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.extract_info(url, download=True)
        _save_subtitle_companion(video_path)
    except Exception as exc:
        logger.debug("字幕单独抓取失败 %s: %s", url[:80], exc)


async def _fetch_subtitles_only(url: str, video_path: Path, referer: str = "") -> None:
    """Async wrapper for subtitle-only fetch."""
    try:
        await asyncio.to_thread(_fetch_subtitles_only_sync, url, video_path, referer)
    except Exception as exc:
        logger.debug("字幕单独抓取失败 %s: %s", url[:80], exc)


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
    async def fallback_to_referer_page() -> tuple[Path | None, int]:
        if not _should_retry_video_via_referer_page(url, media_type, referer):
            return None, 0

        if save_path.exists():
            save_path.unlink()

        logger.info("直接视频下载失败，回退到分享页 yt-dlp: %s via %s", url[:80], referer[:80])
        return await _download_with_ytdlp(referer, save_path, referer=referer)

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
            save_path.parent.mkdir(parents=True, exist_ok=True)
            total = 0
            expected_total = None
            resume_attempts = 0

            while True:
                request_headers = {}
                if total > 0:
                    request_headers["Range"] = f"bytes={total}-"

                try:
                    stream_url = url
                    stream_url = await _resolve_video_redirect_url(client, url, media_type, referer)

                    async with client.stream("GET", stream_url, headers=request_headers or None) as resp:
                        resp.raise_for_status()
                        content_type = resp.headers.get("content-type", "")
                        if total == 0 and not _looks_like_downloadable_media(content_type, media_type):
                            fallback_path, fallback_size = await fallback_to_referer_page()
                            if fallback_size > 0 and fallback_path:
                                return fallback_path, fallback_size
                            logger.info("跳过非媒体响应: %s (%s)", url, content_type)
                            return None, 0

                        expected_total = _expected_total_size(resp.headers, total, expected_total)
                        mode = "ab" if total > 0 else "wb"
                        with open(save_path, mode) as f:
                            async for chunk in resp.aiter_bytes(chunk_size=65536):
                                f.write(chunk)
                                total += len(chunk)
                except _RESUMABLE_DOWNLOAD_ERRORS as e:
                    if total > 0 and expected_total and total < expected_total and resume_attempts < _MAX_RESUME_ATTEMPTS:
                        resume_attempts += 1
                        logger.warning(
                            "下载中断，准备续传 %s (%d/%d, attempt %d)",
                            url[:80],
                            total,
                            expected_total,
                            resume_attempts,
                        )
                        continue
                    raise e

                if not expected_total or total >= expected_total:
                    logger.info("下载完成: %s (%d bytes)", save_path.name, total)
                    # Video downloaded via direct HTTP — try to grab subtitles separately
                    if media_type == "video" and referer and _is_ytdlp_candidate(referer, "video"):
                        await _fetch_subtitles_only(referer, save_path, referer)
                    return save_path, total

                if resume_attempts >= _MAX_RESUME_ATTEMPTS:
                    raise httpx.ReadError(
                        f"incomplete download after {resume_attempts} resume attempts: {total}/{expected_total}",
                    )

                resume_attempts += 1
                logger.warning(
                    "下载提前结束，准备续传 %s (%d/%d, attempt %d)",
                    url[:80],
                    total,
                    expected_total,
                    resume_attempts,
                )
    except Exception as e:
        logger.warning("下载失败 %s: %s", url[:80], e)
        fallback_path, fallback_size = await fallback_to_referer_page()
        if fallback_size > 0 and fallback_path:
            logger.info("分享页 yt-dlp 回退成功: %s (%d bytes)", fallback_path.name, fallback_size)
            return fallback_path, fallback_size
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
    if not user_id:
        user_id = DEFAULT_USER_ID
    path_parts = ["users", user_id, item_id]
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
