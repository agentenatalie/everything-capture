"""
媒体文件下载服务
下载图片（小红书）和视频（抖音）到本地存储
"""

import os
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MEDIA_ROOT = Path("static/media")

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)


async def download_file(url: str, save_path: Path, referer: str = "") -> int:
    """下载单个文件，返回文件大小（bytes）。失败返回 0。"""
    try:
        headers = {"User-Agent": _MOBILE_UA}
        if referer:
            headers["Referer"] = referer
        async with httpx.AsyncClient(
            headers=headers, follow_redirects=True, timeout=60
        ) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                save_path.parent.mkdir(parents=True, exist_ok=True)
                total = 0
                with open(save_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        total += len(chunk)
                logger.info("下载完成: %s (%d bytes)", save_path.name, total)
                return total
    except Exception as e:
        logger.warning("下载失败 %s: %s", url[:80], e)
        # 清理不完整的文件
        if save_path.exists():
            save_path.unlink()
        return 0


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


async def download_media_list(
    item_id: str,
    media_list: list[dict],
    referer: str = "",
) -> list[dict]:
    """
    批量下载媒体文件。

    media_list: [{"type": "image"|"video"|"cover", "url": "...", "order": 0}, ...]

    返回: [{"type", "original_url", "local_path", "file_size", "display_order"}, ...]
    """
    results = []
    item_dir = MEDIA_ROOT / item_id

    for media in media_list:
        url = media.get("url", "")
        mtype = media.get("type", "image")
        order = media.get("order", 0)

        if not url:
            continue

        ext = get_extension(url, mtype)
        filename = f"{mtype}_{order:03d}{ext}"
        save_path = item_dir / filename

        file_size = await download_file(url, save_path, referer=referer)
        if file_size > 0:
            # 存储相对于 static/ 的路径，用于 URL 访问
            relative_path = f"media/{item_id}/{filename}"
            results.append({
                "type": mtype,
                "original_url": url,
                "local_path": relative_path,
                "file_size": file_size,
                "display_order": order,
                "inline_position": media.get("inline_position", -1.0),
            })

    return results
