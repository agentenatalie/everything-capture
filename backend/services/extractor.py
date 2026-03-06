"""
全平台内容提取服务
支持：小红书、抖音、X/Twitter、通用网站
"""

import re
import json
import logging
from dataclasses import dataclass
from urllib.parse import urlparse, unquote

import httpx
from bs4 import BeautifulSoup

try:
    import trafilatura
except ImportError:
    trafilatura = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class ExtractResult:
    title: str
    text: str
    platform: str
    final_url: str
    media_urls: list[dict] | None = None  # [{type, url, order, inline_position}, ...]
    content_blocks: list[dict] | None = None  # [{type:text|image, content|url}, ...]
    content_html: str | None = None  # Sanitized structural HTML preserving rich text


# ---------------------------------------------------------------------------
# HTTP 客户端工厂
# ---------------------------------------------------------------------------

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)

_DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _build_client(ua: str = _DESKTOP_UA, timeout: float = 20) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": ua},
        timeout=timeout,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=10),
    )


# ---------------------------------------------------------------------------
# 平台检测
# ---------------------------------------------------------------------------

_PLATFORM_RULES: list[tuple[str, list[str]]] = [
    ("xiaohongshu", ["xiaohongshu.com", "xhslink.com", "xhs.cn"]),
    ("douyin", ["douyin.com", "iesdouyin.com"]),
    ("wechat", ["mp.weixin.qq.com", "weixin.qq.com"]),
    ("twitter", ["twitter.com", "x.com", "t.co"]),
]


def detect_platform(url: str) -> str:
    """根据 URL 域名识别平台，未知则返回 'generic'"""
    try:
        host = urlparse(url).hostname or ""
        host = host.lower()
    except Exception:
        return "generic"

    for platform, domains in _PLATFORM_RULES:
        for d in domains:
            if host == d or host.endswith("." + d):
                return platform
    return "generic"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _html_meta(soup: BeautifulSoup, prop: str) -> str | None:
    """从 <meta> 标签中提取 og / name 属性的内容"""
    tag = soup.find("meta", attrs={"property": prop})
    if not tag:
        tag = soup.find("meta", attrs={"name": prop})
    if tag:
        content = tag.get("content", "")
        if isinstance(content, list):
            content = content[0] if content else ""
        return content.strip() if content else None
    return None


def _clean_text(text: str) -> str:
    """去除多余空白"""
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# 小红书提取器
# ---------------------------------------------------------------------------

async def extract_xiaohongshu(url: str) -> ExtractResult | None:
    """小红书：HTTP + SSR JSON 解析，OG meta 兜底"""
    async with _build_client(ua=_MOBILE_UA) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("小红书 HTTP 请求失败: %s", e)
            return None

        html = resp.text
        final_url = str(resp.url)

    # 策略 1: __INITIAL_STATE__ SSR JSON
    result = _parse_xhs_initial_state(html)
    if result:
        return ExtractResult(
            title=result["title"],
            text=result["text"],
            platform="xiaohongshu",
            final_url=final_url,
            media_urls=result.get("media_urls"),
        )

    # 策略 2: OG meta 标签
    soup = BeautifulSoup(html, "lxml")
    title = _html_meta(soup, "og:title") or soup.title.string if soup.title else ""
    desc = _html_meta(soup, "og:description") or ""
    if desc and len(desc) > 10:
        full = f"{title}\n\n{desc}" if title else desc
        return ExtractResult(
            title=title or "Unknown",
            text=_clean_text(full),
            platform="xiaohongshu",
            final_url=final_url,
        )

    # 策略 3: DOM 文本
    body_text = _extract_visible_text(soup)
    if body_text and len(body_text) > 30:
        return ExtractResult(
            title=title or "Unknown",
            text=_clean_text(body_text),
            platform="xiaohongshu",
            final_url=final_url,
        )

    return None


def _parse_xhs_initial_state(html: str) -> dict | None:
    """解析小红书 SSR JSON: window.__INITIAL_STATE__ = {...}"""
    for marker in ("window.__INITIAL_STATE__", "window.__INITIAL_SSR_STATE__"):
        idx = html.find(marker)
        if idx == -1:
            continue

        # 找到 '=' 号后面的 JSON
        eq_idx = html.find("=", idx + len(marker))
        if eq_idx == -1:
            continue

        json_start = eq_idx + 1
        # 跳过空白
        while json_start < len(html) and html[json_start] in " \t\n\r":
            json_start += 1
        if json_start >= len(html) or html[json_start] != "{":
            continue

        # 用括号平衡法提取完整 JSON
        json_str = _extract_balanced_json(html, json_start)
        if not json_str:
            continue

        json_str = json_str.replace("undefined", "null")
        try:
            state = json.loads(json_str)
        except json.JSONDecodeError:
            continue

        # 路径 1: note.noteDetailMap
        note_section = state.get("note", {})
        detail_map = note_section.get("noteDetailMap", {})
        for val in detail_map.values():
            note_obj = val.get("note", val) if isinstance(val, dict) else {}
            r = _extract_xhs_note(note_obj)
            if r:
                return r

        # 路径 2: noteData.data
        note_data = state.get("noteData", {})
        data_map = note_data.get("data", {})
        for val in data_map.values():
            if isinstance(val, dict):
                note_obj = val.get("note", val)
                r = _extract_xhs_note(note_obj)
                if r:
                    return r

    return None


def _extract_xhs_note(note: dict) -> dict | None:
    title = note.get("title", "")
    desc = note.get("desc", "")
    tags = ""
    tag_list = note.get("tagList", [])
    if tag_list:
        names = [t.get("name") or t.get("tagName", "") for t in tag_list if isinstance(t, dict)]
        tags = " ".join(f"#{n}" for n in names if n)

    full = ""
    if title:
        full += title + "\n\n"
    if desc:
        full += desc
    if tags:
        full += "\n\n" + tags

    full = full.strip()
    if len(full) <= 20:
        return None

    # 提取图片 URL
    media_urls = []
    image_list = note.get("imageList", []) or note.get("image_list", [])
    for i, img in enumerate(image_list):
        if not isinstance(img, dict):
            continue
        # 优先用 urlDefault > url > infoList 中最大尺寸
        img_url = img.get("urlDefault", "") or img.get("url", "")
        if not img_url:
            info_list = img.get("infoList", []) or img.get("info_list", [])
            if info_list and isinstance(info_list, list):
                # 取最后一个（通常分辨率最高）
                last = info_list[-1] if info_list else {}
                img_url = last.get("url", "") if isinstance(last, dict) else ""
        if img_url:
            # 补全协议
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            media_urls.append({"type": "image", "url": img_url, "order": i})

    return {"title": title or "Unknown", "text": full, "media_urls": media_urls or None}


def _extract_balanced_json(html: str, start: int) -> str | None:
    depth = 0
    in_str = False
    prev = " "
    end = start
    for i in range(start, min(start + 500_000, len(html))):
        ch = html[i]
        if ch == '"' and prev != "\\":
            in_str = not in_str
        elif not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        prev = ch
    if depth != 0:
        return None
    return html[start:end]


# ---------------------------------------------------------------------------
# 抖音提取器
# ---------------------------------------------------------------------------

async def extract_douyin(url: str) -> ExtractResult | None:
    """抖音：跟踪分享链接重定向 + _ROUTER_DATA / meta 解析"""
    async with _build_client(ua=_MOBILE_UA) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("抖音 HTTP 请求失败: %s", e)
            return None

        html = resp.text
        final_url = str(resp.url)

    soup = BeautifulSoup(html, "lxml")

    # 获取标题（title 标签通常包含视频标题）
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        # 去除平台后缀 "- 抖音"
        title = re.sub(r"\s*-\s*抖音$", "", title)

    # 策略 1: window._ROUTER_DATA（iesdouyin.com 分享页最完整的数据源）
    router_result = _parse_douyin_router_data(html, title)
    if router_result:
        return ExtractResult(
            title=router_result["title"],
            text=router_result["text"],
            platform="douyin",
            final_url=final_url,
            media_urls=router_result.get("media_urls"),
        )

    # 策略 2: <meta name="description"> (抖音经常在这里放完整描述)
    desc = _html_meta(soup, "description") or ""
    if not desc:
        desc = _html_meta(soup, "og:description") or ""

    if desc and len(desc) > 10:
        full = f"{title}\n\n{desc}" if title else desc
        return ExtractResult(
            title=title or "Unknown",
            text=_clean_text(full),
            platform="douyin",
            final_url=final_url,
        )

    # 策略 3: 提取 RENDER_DATA（抖音页面的 SSR 数据）
    render_script = soup.find("script", id="RENDER_DATA")
    if render_script and render_script.string:
        try:
            decoded = unquote(render_script.string)
            data = json.loads(decoded)
            result = _parse_douyin_render_data(data)
            if result:
                return ExtractResult(
                    title=result["title"] or title or "Unknown",
                    text=result["text"],
                    platform="douyin",
                    final_url=final_url,
                )
        except (json.JSONDecodeError, Exception) as e:
            logger.debug("抖音 RENDER_DATA 解析失败: %s", e)

    # 策略 4: 从嵌入的 JSON-LD / script 标签中提取
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "")
            if isinstance(ld, dict) and ld.get("description"):
                ld_title = ld.get("name", "") or ld.get("headline", "")
                ld_desc = ld.get("description", "")
                if len(ld_desc) > 10:
                    full = f"{ld_title}\n\n{ld_desc}" if ld_title else ld_desc
                    return ExtractResult(
                        title=ld_title or title or "Unknown",
                        text=_clean_text(full),
                        platform="douyin",
                        final_url=final_url,
                    )
        except Exception:
            continue

    # 策略 5: 仅有标题时也返回
    if title and len(title) > 5:
        return ExtractResult(
            title=title,
            text=title,
            platform="douyin",
            final_url=final_url,
        )

    return None


def _parse_douyin_router_data(html: str, fallback_title: str = "") -> dict | None:
    """解析抖音 iesdouyin.com 页面中的 window._ROUTER_DATA

    该数据包含完整的视频信息：描述、作者名、作者简介、标签等。
    """
    match = re.search(
        r'window\._ROUTER_DATA\s*=\s*(\{.+?\})\s*;?\s*</script>',
        html, re.DOTALL
    )
    if not match:
        return None

    raw = match.group(1)
    # 抖音用 \u002F 代替 /
    raw = raw.replace(r'\u002F', '/')
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    loader = data.get("loaderData", {})
    for key, page in loader.items():
        if not isinstance(page, dict):
            continue
        video_info = page.get("videoInfoRes", {})
        items = video_info.get("item_list", [])
        if not items:
            continue

        item = items[0]
        desc = item.get("desc", "")
        if not desc:
            continue

        # 提取作者信息
        author = item.get("author", {})
        nickname = author.get("nickname", "")
        signature = author.get("signature", "")

        # 提取标签
        text_extra = item.get("text_extra", [])
        hashtags = [
            f"#{te.get('hashtag_name', '')}"
            for te in text_extra
            if isinstance(te, dict) and te.get("hashtag_name")
        ]

        # 提取视频/封面媒体 URL
        media_urls = []
        video_data = item.get("video", {})
        if isinstance(video_data, dict):
            # 视频播放地址
            play_addr = video_data.get("play_addr", {})
            if isinstance(play_addr, dict):
                url_list = play_addr.get("url_list", [])
                if url_list:
                    media_urls.append({"type": "video", "url": url_list[0], "order": 0})
            # 封面图
            cover = video_data.get("cover", {}) or video_data.get("origin_cover", {})
            if isinstance(cover, dict):
                cover_urls = cover.get("url_list", [])
                if cover_urls:
                    media_urls.append({"type": "cover", "url": cover_urls[0], "order": 0})

        # 组装完整文本
        parts = []
        video_title = fallback_title or desc.split("\n")[0][:60]
        parts.append(video_title)
        if nickname:
            parts.append(f"作者：{nickname}")
        parts.append("")
        parts.append(desc)
        if signature:
            parts.append(f"\n作者简介：{signature}")
        if hashtags:
            parts.append("\n" + " ".join(hashtags))

        full_text = "\n".join(parts)
        return {
            "title": video_title,
            "text": _clean_text(full_text),
            "media_urls": media_urls or None,
        }

    return None


def _parse_douyin_render_data(data: dict) -> dict | None:
    """递归搜索抖音 RENDER_DATA 中的视频描述信息"""
    def _search(obj, depth=0):
        if depth > 8 or not isinstance(obj, dict):
            return None
        desc = obj.get("desc", "") or obj.get("description", "") or obj.get("share_desc", "")
        title = obj.get("title", "") or obj.get("nickname", "") or obj.get("share_title", "")

        if desc and len(str(desc)) > 10:
            return {"title": str(title), "text": _clean_text(f"{title}\n\n{desc}" if title else str(desc))}

        for v in obj.values():
            if isinstance(v, dict):
                r = _search(v, depth + 1)
                if r:
                    return r
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        r = _search(item, depth + 1)
                        if r:
                            return r
        return None

    return _search(data)


# ---------------------------------------------------------------------------
# X / Twitter 提取器
# ---------------------------------------------------------------------------

async def extract_twitter(url: str) -> ExtractResult | None:
    """X/Twitter：通过 fxtwitter / vxtwitter 公共 API 获取推文内容（无需 API key）"""
    # 将 x.com / twitter.com URL 转为 api.fxtwitter.com
    parsed = urlparse(url)
    path = parsed.path  # 形如 /username/status/1234567890

    # 处理 t.co 短链接：先跟踪重定向拿到真实 URL
    if parsed.hostname == "t.co":
        async with _build_client() as client:
            try:
                resp = await client.get(url)
                url = str(resp.url)
                parsed = urlparse(url)
                path = parsed.path
            except Exception as e:
                logger.warning("t.co 重定向跟踪失败: %s", e)
                return None

    # 先尝试 fxtwitter JSON API
    api_url = f"https://api.fxtwitter.com{path}"
    async with _build_client() as client:
        try:
            resp = await client.get(api_url)
            if resp.status_code == 200:
                data = resp.json()
                tweet = data.get("tweet", {})
                author_name = tweet.get("author", {}).get("name", "")
                author_handle = tweet.get("author", {}).get("screen_name", "")
                text = tweet.get("text", "")
                created = tweet.get("created_at", "")

                if text:
                    header = f"@{author_handle}" if author_handle else ""
                    if author_name:
                        header = f"{author_name} ({header})" if header else author_name

                    full_text = ""
                    if header:
                        full_text += header + "\n\n"
                    full_text += text
                    if created:
                        full_text += f"\n\n{created}"

                    title = f"{author_name}: {text[:60]}..." if author_name else text[:80]
                    return ExtractResult(
                        title=title,
                        text=_clean_text(full_text),
                        platform="twitter",
                        final_url=url,
                    )
        except Exception as e:
            logger.debug("fxtwitter API 失败: %s", e)

    # Fallback：尝试 vxtwitter
    vx_url = f"https://api.vxtwitter.com{path}"
    async with _build_client() as client:
        try:
            resp = await client.get(vx_url)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("text", "")
                user = data.get("user_name", "")
                handle = data.get("user_screen_name", "")

                if text:
                    header = f"{user} (@{handle})" if user else ""
                    full_text = f"{header}\n\n{text}" if header else text
                    title = f"{user}: {text[:60]}..." if user else text[:80]
                    return ExtractResult(
                        title=title,
                        text=_clean_text(full_text),
                        platform="twitter",
                        final_url=url,
                    )
        except Exception as e:
            logger.debug("vxtwitter API 失败: %s", e)

    # 最终 fallback：直接抓取页面 + OG meta
    return await _extract_twitter_fallback(url)


async def _extract_twitter_fallback(url: str) -> ExtractResult | None:
    """当 API 都不可用时，尝试抓取页面 OG meta"""
    async with _build_client(ua=_DESKTOP_UA) as client:
        try:
            resp = await client.get(url)
            html = resp.text
        except Exception:
            return None

    soup = BeautifulSoup(html, "lxml")
    title = _html_meta(soup, "og:title") or ""
    desc = _html_meta(soup, "og:description") or ""
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    if desc and len(desc) > 5:
        full = f"{title}\n\n{desc}" if title else desc
        return ExtractResult(
            title=title or "Tweet",
            text=_clean_text(full),
            platform="twitter",
            final_url=url,
        )

    # 即使没有 desc，有 title 也返回
    if title and len(title) > 5:
        return ExtractResult(
            title=title,
            text=title,
            platform="twitter",
            final_url=url,
        )
    return None


# ---------------------------------------------------------------------------
# 页面媒体提取（通用）
# ---------------------------------------------------------------------------

_IGNORED_IMAGE_PATTERNS = {
    "logo", "icon", "favicon", "avatar", "emoji", "badge", "button",
    "pixel", "tracker", "spacer", "blank", "1x1", "loading", "spinner",
    "ads", "banner", "sprite", "arrow", ".svg",
}


def _is_meaningful_image(url: str, tag=None) -> bool:
    """过滤掉图标、追踪像素、装饰图等"""
    url_lower = url.lower()
    for pat in _IGNORED_IMAGE_PATTERNS:
        if pat in url_lower:
            return False
    # 检查尺寸属性（过滤小于 50px 的图片）
    if tag:
        w = tag.get("width", "") or ""
        h = tag.get("height", "") or ""
        try:
            if w and int(str(w).replace("px", "")) < 50:
                return False
            if h and int(str(h).replace("px", "")) < 50:
                return False
        except (ValueError, TypeError):
            pass
    return True


def _extract_page_media(soup: BeautifulSoup, base_url: str = "") -> list[dict]:
    """从任意 HTML 页面提取有意义的图片和视频 URL，并计算每张图在正文中的相对位置"""
    media = []
    seen_urls = set()
    img_order = 0
    vid_order = 0

    def _normalize_url(src: str) -> str:
        if not src:
            return ""
        src = src.strip()
        if src.startswith("data:") or src.startswith("blob:"):
            return ""
        if src.startswith("//"):
            return "https:" + src
        if src.startswith("/") and base_url:
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}{src}"
        if not src.startswith("http"):
            return ""
        return src

    # 找到 article body 节点，用于计算图片在正文中的相对位置
    # 优先级: article > main > .rich_media_content > #js_content > body
    _body_node = (
        soup.find("article")
        or soup.find("main")
        or soup.select_one(".rich_media_content")
        or soup.select_one("#js_content")
        or soup.find("body")
    )
    _body_html = str(_body_node) if _body_node else ""
    _body_len = len(_body_html) if _body_html else 1  # 避免除零

    def _inline_position(url: str) -> float:
        """在正文 HTML 中搜索该图片 URL 的位置，返回 0.0-1.0；找不到则返回 -1"""
        if not _body_html or not url:
            return -1.0
        # 只搜索 URL 的主要部分（去掉查询参数，因为 srcset / data-src 可能有差异）
        url_key = url.split("?")[0].split("/")[-1]  # 取最后一段路径
        if len(url_key) < 8:  # 太短的 key 容易误匹配
            url_key = url.split("?")[0]
        idx = _body_html.find(url_key)
        if idx == -1:
            # 尝试更宽泛的搜索（取 URL 末尾 40 字符）
            url_key_long = url.split("?")[0][-40:]
            idx = _body_html.find(url_key_long)
        if idx == -1:
            return -1.0
        return round(idx / _body_len, 4)

    # 1. OG/meta 图片（这些不在正文内，inline_position = -1）
    for prop in ("og:image", "og:image:url", "twitter:image"):
        val = _html_meta(soup, prop)
        if val:
            url = _normalize_url(val)
            if url and url not in seen_urls:
                seen_urls.add(url)
                media.append({"type": "image", "url": url, "order": img_order, "inline_position": -1.0})
                img_order += 1

    for prop in ("og:video", "og:video:url", "twitter:player:stream"):
        val = _html_meta(soup, prop)
        if val:
            url = _normalize_url(val)
            if url and url not in seen_urls:
                seen_urls.add(url)
                media.append({"type": "video", "url": url, "order": vid_order, "inline_position": -1.0})
                vid_order += 1

    # 2. <img> 标签 —— 计算真实的 inline_position
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "") or img.get("data-original", "")
        url = _normalize_url(src)
        if url and url not in seen_urls and _is_meaningful_image(url, img):
            seen_urls.add(url)
            media.append({"type": "image", "url": url, "order": img_order, "inline_position": _inline_position(url)})
            img_order += 1
        # srcset 中的高分辨率图
        srcset = img.get("srcset", "")
        if srcset:
            parts = [s.strip().split()[0] for s in srcset.split(",") if s.strip()]
            if parts:
                best = _normalize_url(parts[-1])  # 取最后一个（通常最大）
                if best and best not in seen_urls and _is_meaningful_image(best):
                    seen_urls.add(best)
                    media.append({"type": "image", "url": best, "order": img_order, "inline_position": _inline_position(best)})
                    img_order += 1

    # 3. <video> 和 <source> 标签
    for video in soup.find_all("video"):
        src = video.get("src", "")
        url = _normalize_url(src)
        if url and url not in seen_urls:
            seen_urls.add(url)
            media.append({"type": "video", "url": url, "order": vid_order, "inline_position": -1.0})
            vid_order += 1
        # poster 作为封面
        poster = video.get("poster", "")
        poster_url = _normalize_url(poster)
        if poster_url and poster_url not in seen_urls:
            seen_urls.add(poster_url)
            media.append({"type": "cover", "url": poster_url, "order": 0, "inline_position": -1.0})

    for source in soup.find_all("source"):
        src = source.get("src", "")
        stype = source.get("type", "")
        url = _normalize_url(src)
        if url and url not in seen_urls and ("video" in stype or url.lower().split("?")[0].endswith((".mp4", ".webm", ".mov"))):
            seen_urls.add(url)
            media.append({"type": "video", "url": url, "order": vid_order, "inline_position": -1.0})
            vid_order += 1

    return media


# ---------------------------------------------------------------------------
# 文章内容块提取（通用）— 保留图文相对顺序
# ---------------------------------------------------------------------------

_BLOCK_LEVEL_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "li",
                     "td", "th", "dt", "dd", "figcaption", "caption"}
_SKIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "iframe",
              "button", "form", "aside", "figure"}
_RECURSIVE_CONTAINER_TAGS = {"div", "section", "article", "main", "picture", "a", "span"}


def _extract_article_blocks(soup: BeautifulSoup, base_url: str = "") -> list[dict]:
    """
    遍历文章 DOM，返回有序的内容块列表：
    [
        {"type": "text",  "content": "段落文字..."},
        {"type": "image", "url": "https://..."},
        ...
    ]
    图片出现的位置与原网页完全一致。
    """
    from urllib.parse import urlparse as _urlparse

    def _norm(src: str) -> str:
        if not src:
            return ""
        src = src.strip()
        if src.startswith(("data:", "blob:")):
            return ""
        if src.startswith("//"):
            return "https:" + src
        if src.startswith("/") and base_url:
            p = _urlparse(base_url)
            return f"{p.scheme}://{p.netloc}{src}"
        if not src.startswith("http"):
            return ""
        return src

    def _img_url(tag) -> str:
        src = tag.get("src", "") or tag.get("data-src", "") or tag.get("data-original", "") or tag.get("data-lazy-src", "")
        url = _norm(src)
        if not url:
            # Try srcset — take the largest
            srcset = tag.get("srcset", "")
            if srcset:
                parts = [s.strip().split()[0] for s in srcset.split(",") if s.strip()]
                if parts:
                    url = _norm(parts[-1])
        return url

    # Locate article root — prefer semantic containers over generic body
    article_root = (
        soup.find("article")
        or soup.select_one("[role='article']")
        or soup.select_one(".rich_media_content")   # WeChat
        or soup.select_one("#js_content")            # WeChat
        or soup.select_one(".post-content")
        or soup.select_one(".article-content")
        or soup.select_one(".entry-content")
        or soup.select_one(".story-body")
        or soup.find("main")
        or soup.find("body")
    )
    if not article_root:
        return []

    blocks: list[dict] = []
    pending_text: list[str] = []

    def flush():
        combined = "\n\n".join(t.strip() for t in pending_text if t.strip())
        if combined:
            blocks.append({"type": "text", "content": combined})
        pending_text.clear()

    def walk(node):
        from bs4 import NavigableString, Tag
        if isinstance(node, NavigableString):
            txt = str(node)
            if txt.strip():
                pending_text.append(txt.strip())
            return

        if not isinstance(node, Tag):
            return

        tag_name = (node.name or "").lower()

        if tag_name in _SKIP_TAGS:
            return

        if tag_name == "img":
            url = _img_url(node)
            if url and _is_meaningful_image(url, node):
                flush()
                blocks.append({"type": "image", "url": url})
            return

        if tag_name in _BLOCK_LEVEL_TAGS:
            # Collect the text of the entire block — but check for nested images first
            has_img = bool(node.find("img"))
            if has_img:
                # Recurse to preserve image ordering within complex blocks
                for child in node.children:
                    walk(child)
                flush()
            else:
                text = node.get_text(separator=" ", strip=True)
                if text:
                    flush()
                    blocks.append({"type": "text", "content": text})
            return

        if tag_name in _RECURSIVE_CONTAINER_TAGS:
            for child in node.children:
                walk(child)
            return

        if node.find(["img", "picture", "figure"], recursive=True):
            for child in node.children:
                walk(child)
            return

        # div / section / span / etc. — recurse into children
        for child in node.children:
            walk(child)

    walk(article_root)
    flush()

    # Deduplicate consecutive identical image URLs
    deduped = []
    last_img_url = None
    for b in blocks:
        if b["type"] == "image":
            if b["url"] == last_img_url:
                continue
            last_img_url = b["url"]
        else:
            last_img_url = None
        deduped.append(b)

    return deduped


# ---------------------------------------------------------------------------
# 文章 HTML 提取（保留图片位置）
# ---------------------------------------------------------------------------

_SAFE_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "img", "figure", "figcaption", "picture", "source",
    "video", "audio",
    "ul", "ol", "li",
    "blockquote", "pre", "code",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "strong", "b", "em", "i", "u", "s",
    "br", "hr", "div", "span", "section",
}

_SAFE_ATTRS = {
    "img": {"src", "data-src", "data-original", "alt", "width", "height", "srcset"},
    "a": {"href"},
    "video": {"src", "poster", "controls"},
    "source": {"src", "type"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}


def _extract_article_html(soup: BeautifulSoup, base_url: str = "") -> str | None:
    """从 HTML 中提取文章区域, 保留 <img> 位置和丰富的格式, 返回清洁 HTML"""
    from copy import deepcopy

    # 找到文章容器
    selectors = [
        "#js_content",           # 微信公众号
        ".rich_media_content",   # 微信公众号
        "article",
        "[role='article']",
        ".article-content",
        ".post-content",
        ".entry-content",
        ".content",
        "#content",
        "main",
        ".story-body",
    ]

    container = None
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            text = node.get_text(strip=True)
            if len(text) > 30:
                container = deepcopy(node)
                break

    if not container:
        return None

    # 移除不需要的标签
    for tag in container.find_all(["script", "style", "nav", "footer", "header",
                                    "noscript", "iframe", "form", "button",
                                    "aside", "svg", "input", "textarea"]):
        tag.decompose()

    # 清洁容器自身的属性（移除 style="visibility:hidden" 等）
    container.attrs = {}

    # 清洁标签和属性
    for tag in container.find_all(True):
        tag_name = tag.name.lower()
        if tag_name not in _SAFE_TAGS:
            tag.unwrap()  # 保留子节点, 移除标签
            continue
        # 清理属性 — 只保留安全属性
        allowed = _SAFE_ATTRS.get(tag_name, set())
        attrs_to_remove = [k for k in tag.attrs if k not in allowed]
        for attr in attrs_to_remove:
            del tag[attr]

    from urllib.parse import urlparse as _urlparse
    # 处理 img 标签: 规范化 URL
    for img in container.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "") or img.get("data-original", "")
        if src:
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/") and base_url:
                parsed = _urlparse(base_url)
                src = f"{parsed.scheme}://{parsed.netloc}{src}"
            img["src"] = src
            # 移除 data-* 属性
            for attr in list(img.attrs):
                if attr.startswith("data-"):
                    del img[attr]
        else:
            img.decompose()

    # 移除空的 div/span/section（避免页面顶部大量空白）
    changed = True
    while changed:
        changed = False
        for tag in container.find_all(["div", "span", "section"]):
            if not tag.get_text(strip=True) and not tag.find(["img", "video"]):
                tag.decompose()
                changed = True

    result = str(container)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip() if len(result) > 50 else None


# ---------------------------------------------------------------------------
# 通用网站提取器
# ---------------------------------------------------------------------------

async def extract_generic(url: str) -> ExtractResult | None:
    """通用网站：DOM 块提取保留图文顺序，trafilatura 作为文本质量兜底"""
    async with _build_client(ua=_DESKTOP_UA) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("通用提取 HTTP 请求失败: %s", e)
            return None

        html = resp.text
        final_url = str(resp.url)

    soup = BeautifulSoup(html, "lxml")
    title = _html_meta(soup, "og:title") or (soup.title.string if soup.title else "") or "Unknown"

    # ── 主路径：DOM 遍历，保留图文顺序 ──────────────────────────────────
    content_blocks = _extract_article_blocks(soup, base_url=final_url)

    # 从 blocks 中拼接出 canonical_text（不再依赖 trafilatura，避免坐标错位）
    blocks_text = "\n\n".join(
        b["content"] for b in content_blocks if b["type"] == "text" and b.get("content", "").strip()
    )

    # 从 blocks 中提取图片列表（用于下载）
    block_images = [
        {"type": "image", "url": b["url"], "order": i, "inline_position": -1.0}
        for i, b in enumerate(b for b in content_blocks if b["type"] == "image")
    ]

    # 提取非内容图片（OG meta、视频等）
    page_media = _extract_page_media(soup, base_url=final_url)
    # 合并：优先用 block_images（有真实位置），再加 OG 图和视频
    block_urls = {m["url"] for m in block_images}
    extra_media = [m for m in page_media if m["url"] not in block_urls]
    media_urls = block_images + extra_media if (block_images or extra_media) else None

    # ── 如果 DOM 解析到了足够文字，直接返回 ────────────────────────────
    if len(blocks_text.strip()) > 50:
        return ExtractResult(
            title=title.strip(),
            text=_clean_text(blocks_text),
            platform="generic",
            final_url=final_url,
            media_urls=media_urls,
            content_blocks=content_blocks if content_blocks else None,
            content_html=_extract_article_html(soup, base_url=final_url),
        )

    # ── 兜底 1：trafilatura ─────────────────────────────────────────────
    if trafilatura:
        try:
            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
                favor_recall=True,
            )
            if text and len(text.strip()) > 50:
                return ExtractResult(
                    title=title.strip(),
                    text=_clean_text(text),
                    platform="generic",
                    final_url=final_url,
                    media_urls=media_urls,
                    content_blocks=content_blocks if content_blocks else None,
                    content_html=_extract_article_html(soup, base_url=final_url),
                )
        except Exception as e:
            logger.debug("trafilatura 提取失败: %s", e)

    # ── 兜底 2: BeautifulSoup 手动提取 ─────────────────────────────────
    selectors = [
        "article", "[role='article']", ".article-content", ".post-content",
        ".entry-content", ".content", "#content", "main", ".story-body",
        "#js_content", ".rich_media_content",
    ]

    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            text = node.get_text(separator="\n", strip=True)
            if len(text) > 50:
                return ExtractResult(
                    title=title.strip(),
                    text=_clean_text(text),
                    platform="generic",
                    final_url=final_url,
                    media_urls=media_urls,
                    content_blocks=content_blocks if content_blocks else None,
                    content_html=_extract_article_html(soup, base_url=final_url),
                )

    # 策略 3: 收集所有段落
    paragraphs = soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"])
    all_text = "\n\n".join(
        p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True) and len(p.get_text(strip=True)) > 5
    )
    if len(all_text) > 50:
        return ExtractResult(
            title=title.strip(),
            text=_clean_text(all_text),
            platform="generic",
            final_url=final_url,
            media_urls=media_urls,
        )

    # 策略 4: body 全文
    body = soup.find("body")
    if body:
        text = body.get_text(separator="\n", strip=True)
        if len(text) > 30:
            return ExtractResult(
                title=title.strip(),
                text=_clean_text(text),
                platform="generic",
                final_url=final_url,
                media_urls=media_urls,
            )

    return None


# ---------------------------------------------------------------------------
# 可见文本提取（辅助）
# ---------------------------------------------------------------------------

def _extract_visible_text(soup: BeautifulSoup) -> str:
    """从 soup 中提取可见文本，排除 script/style/nav 等无关标签"""
    # 移除无关标签
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()

    # 尝试正文容器
    for sel in ["article", "main", ".content", "#content"]:
        node = soup.select_one(sel)
        if node:
            text = node.get_text(separator="\n", strip=True)
            if len(text) > 30:
                return text

    body = soup.find("body")
    if body:
        return body.get_text(separator="\n", strip=True)
    return ""


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

_EXTRACTORS = {
    "xiaohongshu": extract_xiaohongshu,
    "douyin": extract_douyin,
    "twitter": extract_twitter,
    "generic": extract_generic,
}


async def extract_content(url: str) -> ExtractResult:
    """
    统一入口：检测平台 → 调用对应提取器 → 失败则回退通用提取器
    """
    platform = detect_platform(url)
    logger.info("提取 URL: %s (平台: %s)", url, platform)

    # 尝试平台专用提取器
    extractor = _EXTRACTORS.get(platform)
    if extractor and platform != "generic":
        result = await extractor(url)
        if result and len(result.text) > 20:
            return result
        logger.info("平台 %s 提取失败，回退到通用提取器", platform)

    # 通用提取器
    result = await extract_generic(url)
    if result and len(result.text) > 20:
        if platform != "generic":
            result.platform = platform  # 保留原始平台标识
        return result

    # 全部失败
    return ExtractResult(
        title="提取失败",
        text="",
        platform=platform,
        final_url=url,
    )
