"""
全平台内容提取服务
支持：小红书、抖音、X/Twitter、通用网站
"""

import asyncio
import os
import re
import json
import logging
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse, unquote

import httpx
from bs4 import BeautifulSoup

try:
    import trafilatura
except ImportError:
    trafilatura = None

try:
    import yt_dlp
except ImportError:  # pragma: no cover - optional dependency at runtime
    yt_dlp = None

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

_X_DEFAULT_BEARER_TOKEN = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
_X_ARTICLE_QUERY_FALLBACK_ID = "id8pHQbQi7eZ6P9mA1th1Q"
_X_ARTICLE_FEATURE_SWITCHES = [
    "profile_label_improvements_pcf_label_in_post_enabled",
    "responsive_web_profile_redirect_enabled",
    "rweb_tipjar_consumption_enabled",
    "verified_phone_label_enabled",
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
    "responsive_web_graphql_timeline_navigation_enabled",
]
_X_ARTICLE_FIELD_TOGGLES = ["withPayments", "withAuxiliaryUserLabels"]


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


_XHS_GENERIC_TITLES = {"小红书", "小红书 - 你的生活兴趣社区"}


def _normalize_xhs_title_candidate(value: str | None) -> str:
    candidate = re.sub(r"\s+", " ", str(value or "")).strip()
    if not candidate or candidate in _XHS_GENERIC_TITLES:
        return ""
    return candidate[:200]


def _first_meaningful_text_line(text: str | None) -> str:
    for raw_line in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if re.fullmatch(r"(#.+?\[话题\]#\s*)+", line):
            continue
        return line[:200]
    return ""


def _compose_title_and_desc(title: str, desc: str) -> str:
    normalized_title = _normalize_xhs_title_candidate(title)
    normalized_desc = str(desc or "").strip()
    if not normalized_desc:
        return normalized_title
    if not normalized_title:
        return normalized_desc

    compact_title = re.sub(r"\s+", " ", normalized_title)
    compact_desc = re.sub(r"\s+", " ", normalized_desc)
    if compact_desc.startswith(compact_title):
        return normalized_desc
    return f"{normalized_title}\n\n{normalized_desc}"


def _resolve_xhs_title(title: str | None, desc: str | None = None, fallback_text: str | None = None) -> str:
    return (
        _normalize_xhs_title_candidate(title)
        or _first_meaningful_text_line(desc)
        or _first_meaningful_text_line(fallback_text)
    )


def _normalize_media_url(src: str, base_url: str = "") -> str:
    if not src:
        return ""
    src = src.strip()
    if not src or src.startswith(("data:", "blob:")):
        return ""
    if src.startswith("//"):
        return "https:" + src
    if src.startswith(("http://", "https://")):
        return src
    if base_url:
        return urljoin(base_url, src)
    return ""


def _normalize_douyin_video_url(src: str) -> str:
    normalized = _normalize_media_url(src)
    if not normalized:
        return ""

    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    if host.endswith("snssdk.com") and parsed.path == "/aweme/v1/playwm/":
        return normalized.replace("/aweme/v1/playwm/", "/aweme/v1/play/", 1)
    return normalized


def _extract_douyin_aweme_id(url: str) -> str:
    path = urlparse(url).path or ""
    match = re.search(r"/(?:share/(?:video|slides)|note)/(\d+)", path)
    return match.group(1) if match else ""


def _build_douyin_page_media_reference(page_url: str) -> list[dict] | None:
    normalized = _normalize_media_url(page_url)
    if not normalized:
        return None
    return [{"type": "video", "url": normalized, "order": 0}]


def _ensure_douyin_video_candidate(media_urls: list[dict] | None, page_url: str) -> list[dict] | None:
    existing_media = [dict(entry) for entry in (media_urls or []) if isinstance(entry, dict)]
    if any((entry.get("type") or "").lower() == "video" and entry.get("url") for entry in existing_media):
        return existing_media or None

    page_media = _build_douyin_page_media_reference(page_url) or []
    if not page_media:
        return existing_media or None
    return page_media + existing_media


def _has_video_media(media_urls: list[dict] | None) -> bool:
    return any((entry.get("type") or "").lower() == "video" and entry.get("url") for entry in (media_urls or []) if isinstance(entry, dict))


def _extract_douyin_with_ytdlp_sync(url: str) -> dict | None:
    if yt_dlp is None:
        return None

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "http_headers": {"User-Agent": _MOBILE_UA},
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    if not isinstance(info, dict):
        return None

    page_url = (
        _normalize_media_url(str(info.get("webpage_url") or ""))
        or _normalize_media_url(str(info.get("original_url") or ""))
        or _normalize_media_url(url)
    )
    if not page_url:
        return None

    title = str(info.get("title") or "").strip()
    description = str(info.get("description") or "").strip()
    thumbnail = _normalize_media_url(str(info.get("thumbnail") or ""))
    if not thumbnail:
        thumbnails = info.get("thumbnails") or []
        if isinstance(thumbnails, list):
            for candidate in reversed(thumbnails):
                if not isinstance(candidate, dict):
                    continue
                thumbnail = _normalize_media_url(str(candidate.get("url") or ""))
                if thumbnail:
                    break

    media_urls = [{"type": "video", "url": page_url, "order": 0}]
    if thumbnail:
        media_urls.append({"type": "cover", "url": thumbnail, "order": 0})

    text_parts = []
    if title:
        text_parts.append(title)
    if description and description != title:
        text_parts.append(description)

    return {
        "title": title,
        "text": _clean_text("\n\n".join(text_parts)) if text_parts else "",
        "media_urls": media_urls,
        "final_url": page_url,
    }


async def _extract_douyin_with_ytdlp(url: str) -> dict | None:
    if yt_dlp is None:
        return None
    try:
        return await asyncio.to_thread(_extract_douyin_with_ytdlp_sync, url)
    except Exception as exc:
        logger.debug("抖音 yt-dlp metadata 解析失败: %s", exc)
        return None


def _canonicalize_video_embed_url(src: str, base_url: str = "") -> str:
    """Normalize embeddable video URLs so downstream rendering can treat them consistently."""
    normalized = _normalize_media_url(src, base_url=base_url)
    if not normalized:
        return ""

    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query)

    youtube_hosts = {"youtu.be", "www.youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}
    if host in youtube_hosts:
        video_id = ""
        if host.endswith("youtu.be"):
            video_id = path.strip("/").split("/")[0]
        elif "/embed/" in path:
            video_id = path.split("/embed/", 1)[1].split("/", 1)[0]
        elif path.startswith("/shorts/"):
            video_id = path.split("/shorts/", 1)[1].split("/", 1)[0]
        elif path == "/watch":
            video_id = (query.get("v") or [""])[0]
        if video_id:
            return f"https://www.youtube.com/embed/{video_id}"

    if host in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}:
        match = re.search(r"/(?:video/)?(\d+)", path)
        if match:
            return f"https://player.vimeo.com/video/{match.group(1)}"

    return normalized


def _extract_tweet_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    match = re.search(r"/status/(\d+)", parsed.path or "")
    return match.group(1) if match else None


def _extract_twitter_article_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    match = re.search(r"/(?:i/)?article/(\d+)", parsed.path or "")
    return match.group(1) if match else None


def _is_embed_video_url(url: str) -> bool:
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


def _extract_twitter_media(payload: dict) -> list[dict]:
    media_urls: list[dict] = []
    seen: set[str] = set()

    def add_media(url: str, media_type: str, order: int) -> None:
        normalized = _normalize_media_url(url)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        media_urls.append({"type": media_type, "url": normalized, "order": order, "inline_position": -1.0})

    candidates = []
    for key in ("media", "media_extended", "photos", "videos"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))

    for index, media in enumerate(candidates):
        media_type = str(media.get("type", "")).lower()
        if media_type in {"photo", "image", "animated_gif"}:
            add_media(
                media.get("url", "")
                or media.get("media_url_https", "")
                or media.get("media_url", "")
                or media.get("image_url", ""),
                "image",
                index,
            )
            continue

        video_sources = []
        if isinstance(media.get("video"), dict):
            variants = media["video"].get("variants") or []
            if isinstance(variants, list):
                video_sources.extend(v for v in variants if isinstance(v, dict))
        if isinstance(media.get("video_info"), dict):
            variants = media["video_info"].get("variants") or []
            if isinstance(variants, list):
                video_sources.extend(v for v in variants if isinstance(v, dict))

        best_variant = ""
        best_bitrate = -1
        for variant in video_sources:
            variant_url = variant.get("url", "")
            content_type = str(variant.get("content_type", "")).lower()
            bitrate = int(variant.get("bitrate", -1) or -1)
            if variant_url and ("mp4" in content_type or variant_url.lower().split("?")[0].endswith(".mp4")):
                if bitrate >= best_bitrate:
                    best_variant = variant_url
                    best_bitrate = bitrate

        if best_variant:
            add_media(best_variant, "video", index)
        else:
            add_media(
                media.get("url", "")
                or media.get("media_url_https", "")
                or media.get("media_url", "")
                or media.get("thumbnail_url", ""),
                "image" if media_type not in {"video"} else "video",
                index,
            )

    return media_urls


def _parse_twitter_oembed_html(author_name: str, html: str) -> ExtractResult | None:
    soup = BeautifulSoup(html, "lxml")
    quote = soup.find("blockquote")
    if not quote:
        return None

    text_tag = quote.find("p")
    text = text_tag.get_text(" ", strip=True) if text_tag else ""
    date_tag = quote.find("a", href=re.compile(r"/status/\d+"))
    created_at = date_tag.get_text(" ", strip=True) if date_tag else ""

    full_text = ""
    if author_name:
        full_text += author_name.strip()
    if text:
        full_text = f"{full_text}\n\n{text}" if full_text else text
    if created_at:
        full_text = f"{full_text}\n\n{created_at}" if full_text else created_at

    if not full_text.strip():
        return None

    title_source = text or author_name or "Tweet"
    title = f"{author_name}: {title_source[:60]}..." if author_name and text else title_source[:80]
    return ExtractResult(
        title=title,
        text=_clean_text(full_text),
        platform="twitter",
        final_url="",
    )


def _parse_cookie_header(cookie_header: str) -> dict[str, str]:
    cookie_map: dict[str, str] = {}
    for chunk in cookie_header.split(";"):
        if "=" not in chunk:
            continue
        name, value = chunk.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name and value:
            cookie_map[name] = value
    return cookie_map


def _load_x_cookie_map() -> dict[str, str]:
    cookie_map: dict[str, str] = {}

    header = os.getenv("X_COOKIE_HEADER", "").strip()
    if header:
        cookie_map.update(_parse_cookie_header(header))

    env_pairs = {
        "auth_token": os.getenv("X_AUTH_TOKEN", "").strip(),
        "ct0": os.getenv("X_CT0", "").strip(),
        "gt": os.getenv("X_GUEST_TOKEN", "").strip(),
        "twid": os.getenv("X_TWID", "").strip(),
    }
    for name, value in env_pairs.items():
        if value:
            cookie_map[name] = value

    return cookie_map


def _build_x_request_headers(cookie_map: dict[str, str]) -> dict[str, str]:
    headers = {
        "authorization": os.getenv("X_BEARER_TOKEN", "").strip() or _X_DEFAULT_BEARER_TOKEN,
        "user-agent": os.getenv("X_USER_AGENT", "").strip() or _DESKTOP_UA,
        "accept": "application/json",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "accept-language": "en",
    }

    guest_token = cookie_map.get("gt")
    if guest_token:
        headers["x-guest-token"] = guest_token

    if cookie_map:
        headers["cookie"] = "; ".join(f"{key}={value}" for key, value in cookie_map.items() if value)

    if cookie_map.get("auth_token"):
        headers["x-twitter-auth-type"] = "OAuth2Session"
    if cookie_map.get("ct0"):
        headers["x-csrf-token"] = cookie_map["ct0"]

    return headers


def _resolve_feature_value(html: str, key: str) -> bool | None:
    key_pattern = re.escape(key)
    match = re.search(rf'"{key_pattern}"\s*:\s*\{{"value"\s*:\s*(true|false)', html)
    if match:
        return match.group(1) == "true"
    escaped = re.search(rf'\\"{key_pattern}\\"\s*:\s*\\\{{\\"value\\"\s*:\s*(true|false)', html)
    if escaped:
        return escaped.group(1) == "true"
    return None


def _build_x_feature_map(html: str, keys: list[str]) -> dict[str, bool]:
    feature_map: dict[str, bool] = {}
    for key in keys:
        value = _resolve_feature_value(html, key)
        feature_map[key] = True if value is None else value
    feature_map.setdefault("responsive_web_graphql_exclude_directive_enabled", True)
    return feature_map


async def _resolve_x_home_html(client: httpx.AsyncClient) -> str:
    resp = await client.get("https://x.com")
    resp.raise_for_status()
    return resp.text


async def _resolve_x_article_query_info(client: httpx.AsyncClient) -> tuple[str, list[str], list[str], str]:
    html = await _resolve_x_home_html(client)
    bundle_match = re.search(r'"bundle\.TwitterArticles":"([a-z0-9]+)"', html)
    if not bundle_match:
        return _X_ARTICLE_QUERY_FALLBACK_ID, _X_ARTICLE_FEATURE_SWITCHES, _X_ARTICLE_FIELD_TOGGLES, html

    chunk_url = f"https://abs.twimg.com/responsive-web/client-web/bundle.TwitterArticles.{bundle_match.group(1)}a.js"
    try:
        chunk_resp = await client.get(chunk_url)
        chunk_resp.raise_for_status()
        chunk = chunk_resp.text
    except Exception as e:
        logger.debug("加载 X article chunk 失败: %s", e)
        return _X_ARTICLE_QUERY_FALLBACK_ID, _X_ARTICLE_FEATURE_SWITCHES, _X_ARTICLE_FIELD_TOGGLES, html

    query_id = _X_ARTICLE_QUERY_FALLBACK_ID
    feature_switches = _X_ARTICLE_FEATURE_SWITCHES
    field_toggles = _X_ARTICLE_FIELD_TOGGLES

    query_match = re.search(r'queryId:"([^"]+)",operationName:"ArticleEntityResultByRestId"', chunk)
    if query_match:
        query_id = query_match.group(1)

    feature_match = re.search(
        r'operationName:"ArticleEntityResultByRestId"[\s\S]*?featureSwitches:\[(.*?)\]',
        chunk,
    )
    if feature_match:
        parsed = [item.strip().strip('"') for item in feature_match.group(1).split(",") if item.strip()]
        if parsed:
            feature_switches = parsed

    field_match = re.search(
        r'operationName:"ArticleEntityResultByRestId"[\s\S]*?fieldToggles:\[(.*?)\]',
        chunk,
    )
    if field_match:
        parsed = [item.strip().strip('"') for item in field_match.group(1).split(",") if item.strip()]
        if parsed:
            field_toggles = parsed

    return query_id, feature_switches, field_toggles, html


def _pick_best_x_video_variant(media_info: dict) -> str:
    best_url = ""
    best_bitrate = -1
    for variant in media_info.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        variant_url = variant.get("url", "")
        content_type = str(variant.get("content_type", "")).lower()
        bit_rate = int(variant.get("bit_rate", -1) or -1)
        if variant_url and ("mp4" in content_type or variant_url.lower().split("?")[0].endswith(".mp4")):
            if bit_rate >= best_bitrate:
                best_url = variant_url
                best_bitrate = bit_rate
    return best_url


def _extract_x_media_url(media_info: dict) -> tuple[str, str]:
    if not isinstance(media_info, dict):
        return "", "image"
    video_url = _pick_best_x_video_variant(media_info)
    if video_url:
        return video_url, "video"
    image_url = (
        media_info.get("original_img_url")
        or ((media_info.get("preview_image") or {}).get("original_img_url"))
        or ""
    )
    return image_url, "image"


def _extract_x_article_text(article: dict) -> str:
    plain_text = str(article.get("plain_text") or "").strip()
    if plain_text:
        return plain_text

    preview_text = str(article.get("preview_text") or "").strip()
    if preview_text:
        return preview_text

    blocks = ((article.get("content_state") or {}).get("blocks") or [])
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if text:
            parts.append(text)
    return _clean_text("\n\n".join(parts))


def _parse_x_article_result(article: dict, final_url: str) -> ExtractResult | None:
    if not isinstance(article, dict):
        return None

    title = str(article.get("title") or "X Article").strip() or "X Article"
    text = _extract_x_article_text(article)
    media_urls: list[dict] = []
    seen: set[str] = set()

    def add_media(url: str, media_type: str, order: int) -> None:
        normalized = _normalize_media_url(url)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        media_urls.append({
            "type": media_type,
            "url": normalized,
            "order": order,
            "inline_position": -1.0,
        })

    cover_media = article.get("cover_media") or {}
    cover_info = cover_media.get("media_info") if isinstance(cover_media, dict) else {}
    cover_url, cover_type = _extract_x_media_url(cover_info or {})
    if cover_url:
        add_media(cover_url, "cover" if cover_type == "image" else cover_type, 0)

    for index, entity in enumerate(article.get("media_entities") or [], start=1):
        if not isinstance(entity, dict):
            continue
        media_url, media_type = _extract_x_media_url(entity.get("media_info") or {})
        if media_url:
            add_media(media_url, media_type, index)

    if not text and not media_urls:
        return None

    canonical_text = text or title
    return ExtractResult(
        title=title,
        text=_clean_text(canonical_text),
        platform="twitter",
        final_url=final_url,
        media_urls=media_urls or None,
    )


async def _extract_twitter_article(url: str, article_id: str) -> ExtractResult | None:
    cookie_map = _load_x_cookie_map()
    if not cookie_map.get("gt"):
        try:
            async with _build_client() as guest_client:
                home_html = await _resolve_x_home_html(guest_client)
            guest_match = re.search(r'document.cookie="gt=([^;]+);', home_html)
            if guest_match:
                cookie_map["gt"] = guest_match.group(1)
        except Exception as e:
            logger.debug("获取 X guest token 失败: %s", e)

    headers = _build_x_request_headers(cookie_map)
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30) as client:
        try:
            query_id, feature_switches, field_toggles, home_html = await _resolve_x_article_query_info(client)
            params = {
                "variables": json.dumps({"articleEntityId": article_id}, ensure_ascii=False),
                "features": json.dumps(_build_x_feature_map(home_html, feature_switches), ensure_ascii=False),
                "fieldToggles": json.dumps({key: True for key in field_toggles}, ensure_ascii=False),
            }
            resp = await client.get(
                f"https://x.com/i/api/graphql/{query_id}/ArticleEntityResultByRestId",
                params=params,
            )
            if resp.status_code == 404 and cookie_map.get("auth_token"):
                logger.info("X article GraphQL 404，当前账户可能无访问权限: %s", url)
                return None
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            logger.debug("X article GraphQL 失败: %s", e)
            return None

    root = payload.get("data", payload)
    article = (
        ((root.get("article_result_by_rest_id") or {}).get("result"))
        or root.get("article_result_by_rest_id")
        or ((root.get("article_entity_result") or {}).get("result"))
    )
    return _parse_x_article_result(article, url)


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
    page_title = soup.title.string.strip() if soup.title and soup.title.string else ""
    desc = _html_meta(soup, "og:description") or ""
    title = _resolve_xhs_title(_html_meta(soup, "og:title") or page_title, desc)
    if desc and len(desc) > 10:
        full = _compose_title_and_desc(title, desc)
        return ExtractResult(
            title=title or "Unknown",
            text=_clean_text(full),
            platform="xiaohongshu",
            final_url=final_url,
        )

    # 策略 3: DOM 文本
    body_text = _extract_visible_text(soup)
    if body_text and len(body_text) > 30:
        body_title = _resolve_xhs_title(title or page_title, desc, body_text)
        return ExtractResult(
            title=body_title or "Unknown",
            text=_clean_text(body_text),
            platform="xiaohongshu",
            final_url=final_url,
        )

    return None


def _extract_xhs_video_url(note: dict) -> str:
    video = note.get("video")
    if not isinstance(video, dict):
        return ""

    media = video.get("media")
    stream = media.get("stream") if isinstance(media, dict) else None
    if not isinstance(stream, dict):
        stream = video.get("stream")
    if not isinstance(stream, dict):
        return ""

    best_url = ""
    best_score = -1
    for codec_name in ("h264", "h265", "av1", "h266"):
        variants = stream.get(codec_name) or []
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            candidate = _normalize_media_url(str(variant.get("masterUrl") or variant.get("master_url") or ""))
            if not candidate:
                backup_urls = variant.get("backupUrls") or variant.get("backup_urls") or []
                if isinstance(backup_urls, list):
                    for backup in backup_urls:
                        candidate = _normalize_media_url(str(backup or ""))
                        if candidate:
                            break
            if not candidate:
                continue
            score = 0
            for key in ("avgBitrate", "videoBitrate", "size", "weight"):
                try:
                    score += int(variant.get(key) or 0)
                except (TypeError, ValueError):
                    continue
            if score >= best_score:
                best_url = candidate
                best_score = score
    return best_url


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
    raw_title = note.get("title", "")
    desc = str(note.get("desc", "") or "")
    title = _resolve_xhs_title(raw_title, desc)
    tags = ""
    tag_list = note.get("tagList", [])
    if tag_list:
        names = [t.get("name") or t.get("tagName", "") for t in tag_list if isinstance(t, dict)]
        tags = " ".join(f"#{n}" for n in names if n)

    full = _compose_title_and_desc(title, desc)
    if tags:
        full = f"{full}\n\n{tags}" if full else tags

    full = full.strip()
    if len(full) <= 20:
        return None

    media_urls = []
    video_url = _extract_xhs_video_url(note)
    if video_url:
        media_urls.append({"type": "video", "url": video_url, "order": 0})

    image_urls: list[str] = []
    image_list = note.get("imageList", []) or note.get("image_list", [])
    for img in image_list:
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
            image_urls.append(img_url)

    if video_url and len(image_urls) == 1:
        media_urls.append({"type": "cover", "url": image_urls[0], "order": 0})
    else:
        for i, img_url in enumerate(image_urls):
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

    ytdlp_result: dict | None = None

    async def get_ytdlp_result() -> dict | None:
        nonlocal ytdlp_result
        if ytdlp_result is None:
            ytdlp_result = await _extract_douyin_with_ytdlp(final_url or url)
        return ytdlp_result

    # 策略 1: window._ROUTER_DATA（iesdouyin.com 分享页最完整的数据源）
    router_result = _parse_douyin_router_data(html, title)
    if router_result:
        media_urls = router_result.get("media_urls")
        if not _has_video_media(media_urls):
            ytdlp_media = await get_ytdlp_result()
            if ytdlp_media and ytdlp_media.get("media_urls"):
                media_urls = ytdlp_media["media_urls"] + [entry for entry in (media_urls or []) if (entry.get("type") or "").lower() != "cover"]
            else:
                media_urls = _ensure_douyin_video_candidate(media_urls, final_url)
        return ExtractResult(
            title=router_result["title"],
            text=router_result["text"],
            platform="douyin",
            final_url=final_url,
            media_urls=media_urls,
        )

    slides_result = await _extract_douyin_slides_info(
        final_url,
        fallback_title=title,
    )
    if slides_result:
        return ExtractResult(
            title=slides_result["title"],
            text=slides_result["text"],
            platform="douyin",
            final_url=final_url,
            media_urls=slides_result.get("media_urls"),
        )

    # 策略 2: <meta name="description"> (抖音经常在这里放完整描述)
    desc = _html_meta(soup, "description") or ""
    if not desc:
        desc = _html_meta(soup, "og:description") or ""

    if desc and len(desc) > 10:
        full = f"{title}\n\n{desc}" if title else desc
        ytdlp_media = await get_ytdlp_result()
        return ExtractResult(
            title=(ytdlp_media or {}).get("title") or title or "Unknown",
            text=_clean_text((ytdlp_media or {}).get("text") or full),
            platform="douyin",
            final_url=final_url,
            media_urls=(ytdlp_media or {}).get("media_urls") or _ensure_douyin_video_candidate(None, final_url),
        )

    # 策略 3: 提取 RENDER_DATA（抖音页面的 SSR 数据）
    render_script = soup.find("script", id="RENDER_DATA")
    if render_script and render_script.string:
        try:
            decoded = unquote(render_script.string)
            data = json.loads(decoded)
            result = _parse_douyin_render_data(data)
            if result:
                ytdlp_media = await get_ytdlp_result()
                return ExtractResult(
                    title=(ytdlp_media or {}).get("title") or result["title"] or title or "Unknown",
                    text=(ytdlp_media or {}).get("text") or result["text"],
                    platform="douyin",
                    final_url=final_url,
                    media_urls=(ytdlp_media or {}).get("media_urls") or _ensure_douyin_video_candidate(None, final_url),
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
                    ytdlp_media = await get_ytdlp_result()
                    return ExtractResult(
                        title=(ytdlp_media or {}).get("title") or ld_title or title or "Unknown",
                        text=_clean_text((ytdlp_media or {}).get("text") or full),
                        platform="douyin",
                        final_url=final_url,
                        media_urls=(ytdlp_media or {}).get("media_urls") or _ensure_douyin_video_candidate(None, final_url),
                    )
        except Exception:
            continue

    # 策略 5: 仅有标题时也返回
    if title and len(title) > 5:
        ytdlp_media = await get_ytdlp_result()
        return ExtractResult(
            title=(ytdlp_media or {}).get("title") or title,
            text=(ytdlp_media or {}).get("text") or title,
            platform="douyin",
            final_url=final_url,
            media_urls=(ytdlp_media or {}).get("media_urls") or _ensure_douyin_video_candidate(None, final_url),
        )

    return None


async def _extract_douyin_slides_info(url: str, fallback_title: str = "") -> dict | None:
    aweme_id = _extract_douyin_aweme_id(url)
    if not aweme_id:
        return None

    path = urlparse(url).path or ""
    if "/share/slides/" not in path and "/note/" not in path:
        return None

    query = parse_qs(urlparse(url).query or "")
    params = {
        "aweme_ids": f"[{aweme_id}]",
        "request_source": 200,
    }
    aweme_type = (query.get("aweme_type") or [""])[0]
    if aweme_type:
        params["aweme_type"] = aweme_type

    async with _build_client(ua=_MOBILE_UA) as client:
        client.headers["Referer"] = url
        try:
            resp = await client.get("https://www.douyin.com/web/api/v2/aweme/slidesinfo/", params=params)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.debug("抖音 slidesinfo API 解析失败: %s", exc)
            return None

    return _parse_douyin_slides_response(payload, fallback_title=fallback_title)


def _parse_douyin_slides_response(payload: dict, fallback_title: str = "") -> dict | None:
    aweme_details = payload.get("aweme_details") or ((payload.get("data") or {}).get("aweme_details")) or []
    if not isinstance(aweme_details, list) or not aweme_details:
        return None

    item = aweme_details[0]
    if not isinstance(item, dict):
        return None

    images = item.get("images") or item.get("image_infos") or []
    media_urls = []
    if isinstance(images, list):
        for index, image in enumerate(images):
            if not isinstance(image, dict):
                continue
            candidate_lists = [
                image.get("url_list"),
                image.get("download_url_list"),
            ]
            image_url = ""
            for url_list in candidate_lists:
                if not isinstance(url_list, list):
                    continue
                for candidate in url_list:
                    image_url = _normalize_media_url(str(candidate or ""))
                    if image_url:
                        break
                if image_url:
                    break
            if image_url:
                media_urls.append({"type": "image", "url": image_url, "order": index})

    desc = str(item.get("desc") or "").strip()
    preview_title = str(item.get("preview_title") or "").strip()
    normalized_fallback_title = str(fallback_title or "").strip()
    if normalized_fallback_title in {"抖音", "Douyin"}:
        normalized_fallback_title = ""
    title = preview_title or normalized_fallback_title or desc.split("\n")[0][:60]

    author = item.get("author") or {}
    nickname = str(author.get("nickname") or "").strip()
    signature = str(author.get("signature") or "").strip()
    hashtags = [
        f"#{extra.get('hashtag_name', '')}"
        for extra in (item.get("text_extra") or [])
        if isinstance(extra, dict) and extra.get("hashtag_name")
    ]

    parts = []
    if title:
        parts.append(title)
    if nickname:
        parts.append(f"作者：{nickname}")
    if desc:
        if parts:
            parts.append("")
        parts.append(desc)
    if signature:
        parts.append(f"\n作者简介：{signature}")
    if hashtags:
        parts.append("\n" + " ".join(hashtags))

    text = _clean_text("\n".join(parts))
    if not text and media_urls:
        text = title or desc or "Douyin image note"
    if not text and not media_urls:
        return None

    return {
        "title": title or "Unknown",
        "text": text,
        "media_urls": media_urls or None,
    }


def _parse_douyin_router_data(html: str, fallback_title: str = "") -> dict | None:
    """解析抖音 iesdouyin.com 页面中的 window._ROUTER_DATA

    该数据包含完整的视频信息：描述、作者名、作者简介、标签等。
    """
    marker = "window._ROUTER_DATA"
    idx = html.find(marker)
    if idx == -1:
        return None

    eq_idx = html.find("=", idx + len(marker))
    if eq_idx == -1:
        return None

    json_start = eq_idx + 1
    while json_start < len(html) and html[json_start] in " \t\n\r":
        json_start += 1
    if json_start >= len(html) or html[json_start] != "{":
        return None

    raw = _extract_balanced_json(html, json_start)
    if not raw:
        return None

    # 抖音用 \u002F 代替 /
    raw = raw.replace(r"\u002F", "/").replace("undefined", "null")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    def _first_media_url(source: dict | None) -> str:
        if not isinstance(source, dict):
            return ""
        for candidate in source.get("url_list") or []:
            normalized = _normalize_media_url(str(candidate or ""))
            if normalized:
                return normalized
        return ""

    def _best_video_url(video_data: dict) -> str:
        best_url = ""
        best_bitrate = -1

        for variant in video_data.get("bit_rate") or []:
            if not isinstance(variant, dict):
                continue
            bitrate = variant.get("bit_rate", -1)
            try:
                bitrate_value = int(bitrate if bitrate is not None else -1)
            except (TypeError, ValueError):
                bitrate_value = -1

            for key in ("play_addr", "play_addr_h264", "play_addr_265", "download_addr"):
                candidate = _first_media_url(variant.get(key))
                if candidate and bitrate_value >= best_bitrate:
                    best_url = _normalize_douyin_video_url(candidate)
                    best_bitrate = bitrate_value

        if best_url:
            return best_url

        for key in ("play_addr", "play_addr_h264", "play_addr_265", "download_addr"):
            candidate = _first_media_url(video_data.get(key))
            if candidate:
                return _normalize_douyin_video_url(candidate)

        return ""

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
            video_url = _best_video_url(video_data)
            if video_url:
                media_urls.append({"type": "video", "url": video_url, "order": 0})

            cover_url = ""
            for key in ("origin_cover", "dynamic_cover", "cover"):
                cover_url = _first_media_url(video_data.get(key))
                if cover_url:
                    break
            if cover_url:
                media_urls.append({"type": "cover", "url": cover_url, "order": 0})

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
    """X/Twitter：优先公共 API，失败时回退到官方 oEmbed 与页面 meta。"""
    parsed = urlparse(url)
    path = parsed.path
    article_id = _extract_twitter_article_id(url)

    if parsed.hostname == "t.co":
        async with _build_client() as client:
            try:
                resp = await client.get(url)
                url = str(resp.url)
                parsed = urlparse(url)
                path = parsed.path
                article_id = _extract_twitter_article_id(url)
            except Exception as e:
                logger.warning("t.co 重定向跟踪失败: %s", e)
                return None

    if article_id:
        article_result = await _extract_twitter_article(url, article_id)
        if article_result and (len(article_result.text) > 20 or article_result.media_urls):
            return article_result

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
                media_urls = _extract_twitter_media(tweet)

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
                        media_urls=media_urls or None,
                    )
        except Exception as e:
            logger.debug("fxtwitter API 失败: %s", e)

    vx_url = f"https://api.vxtwitter.com{path}"
    async with _build_client() as client:
        try:
            resp = await client.get(vx_url)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("text", "")
                user = data.get("user_name", "")
                handle = data.get("user_screen_name", "")
                media_urls = _extract_twitter_media(data)
                if not media_urls:
                    media_urls = [
                        {
                            "type": "image",
                            "url": normalized,
                            "order": index,
                            "inline_position": -1.0,
                        }
                        for index, media_url in enumerate(data.get("mediaURLs", []) or [])
                        if (normalized := _normalize_media_url(media_url))
                    ]

                if text:
                    header = f"{user} (@{handle})" if user else ""
                    full_text = f"{header}\n\n{text}" if header else text
                    title = f"{user}: {text[:60]}..." if user else text[:80]
                    return ExtractResult(
                        title=title,
                        text=_clean_text(full_text),
                        platform="twitter",
                        final_url=url,
                        media_urls=media_urls or None,
                    )
        except Exception as e:
            logger.debug("vxtwitter API 失败: %s", e)

    tweet_id = _extract_tweet_id(url)
    if tweet_id:
        async with _build_client() as client:
            try:
                oembed_resp = await client.get(
                    "https://publish.x.com/oembed",
                    params={"url": url},
                )
                if oembed_resp.status_code == 200:
                    data = oembed_resp.json()
                    parsed_oembed = _parse_twitter_oembed_html(
                        data.get("author_name", ""),
                        data.get("html", ""),
                    )
                    if parsed_oembed:
                        parsed_oembed.final_url = url
                        return parsed_oembed
            except Exception as e:
                logger.debug("X oEmbed 失败: %s", e)

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
            url = _normalize_media_url(val, base_url=base_url)
            if url and url not in seen_urls:
                seen_urls.add(url)
                media.append({"type": "image", "url": url, "order": img_order, "inline_position": -1.0})
                img_order += 1

    for prop in ("og:video", "og:video:url", "twitter:player:stream"):
        val = _html_meta(soup, prop)
        if val:
            url = _normalize_media_url(val, base_url=base_url)
            if url and url not in seen_urls:
                seen_urls.add(url)
                media.append({"type": "video", "url": url, "order": vid_order, "inline_position": -1.0})
                vid_order += 1

    # 2. <img> 标签 —— 计算真实的 inline_position
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "") or img.get("data-original", "")
        url = _normalize_media_url(src, base_url=base_url)
        if url and url not in seen_urls and _is_meaningful_image(url, img):
            seen_urls.add(url)
            media.append({"type": "image", "url": url, "order": img_order, "inline_position": _inline_position(url)})
            img_order += 1
        # srcset 中的高分辨率图
        srcset = img.get("srcset", "")
        if srcset:
            parts = [s.strip().split()[0] for s in srcset.split(",") if s.strip()]
            if parts:
                best = _normalize_media_url(parts[-1], base_url=base_url)  # 取最后一个（通常最大）
                if best and best not in seen_urls and _is_meaningful_image(best):
                    seen_urls.add(best)
                    media.append({"type": "image", "url": best, "order": img_order, "inline_position": _inline_position(best)})
                    img_order += 1

    # 3. <video> 和 <source> 标签
    for video in soup.find_all("video"):
        src = video.get("src", "")
        url = _normalize_media_url(src, base_url=base_url)
        if url and url not in seen_urls:
            seen_urls.add(url)
            media.append({"type": "video", "url": url, "order": vid_order, "inline_position": -1.0})
            vid_order += 1
        # poster 作为封面
        poster = video.get("poster", "")
        poster_url = _normalize_media_url(poster, base_url=base_url)
        if poster_url and poster_url not in seen_urls:
            seen_urls.add(poster_url)
            media.append({"type": "cover", "url": poster_url, "order": 0, "inline_position": -1.0})

    for source in soup.find_all("source"):
        src = source.get("src", "")
        stype = source.get("type", "")
        url = _normalize_media_url(src, base_url=base_url)
        if url and url not in seen_urls and ("video" in stype or url.lower().split("?")[0].endswith((".mp4", ".webm", ".mov"))):
            seen_urls.add(url)
            media.append({"type": "video", "url": url, "order": vid_order, "inline_position": -1.0})
            vid_order += 1

    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "") or iframe.get("data-src", "")
        url = _canonicalize_video_embed_url(src, base_url=base_url)
        if url and url not in seen_urls and _is_embed_video_url(url):
            seen_urls.add(url)
            media.append({"type": "video", "url": url, "order": vid_order, "inline_position": _inline_position(src or url)})
            vid_order += 1

    return media


# ---------------------------------------------------------------------------
# 文章内容块提取（通用）— 保留图文相对顺序
# ---------------------------------------------------------------------------

_BLOCK_LEVEL_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "li",
                     "td", "th", "dt", "dd", "figcaption", "caption"}
_SKIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript",
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
    def _img_url(tag) -> str:
        src = tag.get("src", "") or tag.get("data-src", "") or tag.get("data-original", "") or tag.get("data-lazy-src", "")
        url = _normalize_media_url(src, base_url=base_url)
        if not url:
            # Try srcset — take the largest
            srcset = tag.get("srcset", "")
            if srcset:
                parts = [s.strip().split()[0] for s in srcset.split(",") if s.strip()]
                if parts:
                    url = _normalize_media_url(parts[-1], base_url=base_url)
        return url

    def _video_url(tag) -> str:
        if tag.name == "iframe":
            src = tag.get("src", "") or tag.get("data-src", "")
            return _canonicalize_video_embed_url(src, base_url=base_url)

        src = tag.get("src", "")
        url = _normalize_media_url(src, base_url=base_url)
        if url:
            return url

        for source in tag.find_all("source"):
            source_url = _normalize_media_url(source.get("src", ""), base_url=base_url)
            if source_url:
                return source_url
        return ""

    article_root = _find_article_root(soup) or soup.find("body")
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

        if tag_name in {"video", "iframe"}:
            url = _video_url(node)
            if url and (tag_name == "video" or _is_embed_video_url(url)):
                flush()
                blocks.append({"type": "video", "url": url})
            return

        if tag_name in _BLOCK_LEVEL_TAGS:
            # Collect the text of the entire block — but check for nested images first
            has_media = bool(node.find(["img", "video", "iframe"]))
            if has_media:
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

        if node.find(["img", "picture", "figure", "video", "iframe"], recursive=True):
            for child in node.children:
                walk(child)
            return

        # div / section / span / etc. — recurse into children
        for child in node.children:
            walk(child)

    walk(article_root)
    flush()

    # Deduplicate consecutive identical media URLs
    deduped = []
    last_media_key = None
    for b in blocks:
        if b["type"] in {"image", "video"}:
            media_key = f"{b['type']}::{b['url']}"
            if media_key == last_media_key:
                continue
            last_media_key = media_key
        else:
            last_media_key = None
        deduped.append(b)

    return deduped


# ---------------------------------------------------------------------------
# 文章 HTML 提取（保留图片位置）
# ---------------------------------------------------------------------------

_SAFE_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "img", "figure", "figcaption", "picture", "source",
    "video", "audio", "iframe",
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
    "iframe": {"src", "title", "width", "height", "allow", "allowfullscreen", "frameborder", "loading", "referrerpolicy"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

_ARTICLE_ROOT_SELECTORS = [
    "#content1",
    ".newContent",
    "#js_content",
    ".rich_media_content",
    "article",
    "[role='article']",
    ".article-content",
    ".post-content",
    ".entry-content",
    ".article-body",
    ".articleBody",
    ".content",
    "#content",
    "main",
    ".story-body",
]


def _find_article_root(soup: BeautifulSoup):
    """Pick the most likely article container while avoiding site shell containers."""
    best_node = None
    best_len = 0
    high_confidence_selectors = {
        "#content1",
        ".newContent",
        "#js_content",
        ".rich_media_content",
        "article",
        "[role='article']",
    }

    for selector in _ARTICLE_ROOT_SELECTORS:
        for node in soup.select(selector):
            text = node.get_text(" ", strip=True)
            text_len = len(text)
            minimum_text_len = 1 if selector in high_confidence_selectors else 20
            if text_len < minimum_text_len:
                continue
            if best_node is None:
                best_node = node
                best_len = text_len
            if selector in high_confidence_selectors:
                return node
            if text_len > best_len:
                best_node = node
                best_len = text_len

    return best_node


def _extract_article_html(soup: BeautifulSoup, base_url: str = "") -> str | None:
    """从 HTML 中提取文章区域, 保留 <img> 位置和丰富的格式, 返回清洁 HTML"""
    from copy import deepcopy

    source_container = _find_article_root(soup)
    container = deepcopy(source_container) if source_container else None

    if not container:
        return None

    # 移除不需要的标签
    for tag in container.find_all(["script", "style", "nav", "footer", "header",
                                    "noscript", "form", "button",
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

    # 处理 img 标签: 规范化 URL
    for img in container.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "") or img.get("data-original", "")
        if src:
            img["src"] = _normalize_media_url(src, base_url=base_url)
            # 移除 data-* 属性
            for attr in list(img.attrs):
                if attr.startswith("data-"):
                    del img[attr]
        else:
            img.decompose()

    for video in container.find_all("video"):
        src = video.get("src", "")
        normalized = _normalize_media_url(src, base_url=base_url)
        if normalized:
            video["src"] = normalized
            video["controls"] = "controls"
        else:
            source = video.find("source")
            if not source:
                video.decompose()
                continue
            source_src = _normalize_media_url(source.get("src", ""), base_url=base_url)
            if not source_src:
                video.decompose()
                continue
            source["src"] = source_src
            video["controls"] = "controls"

    for iframe in container.find_all("iframe"):
        normalized = _canonicalize_video_embed_url(
            iframe.get("src", "") or iframe.get("data-src", ""),
            base_url=base_url,
        )
        if not normalized or not _is_embed_video_url(normalized):
            iframe.decompose()
            continue
        iframe["src"] = normalized
        iframe["loading"] = "lazy"
        iframe["referrerpolicy"] = "strict-origin-when-cross-origin"
        iframe["allowfullscreen"] = "allowfullscreen"

    # 移除空的 div/span/section（避免页面顶部大量空白）
    changed = True
    while changed:
        changed = False
        for tag in container.find_all(["div", "span", "section"]):
            if not tag.get_text(strip=True) and not tag.find(["img", "video", "iframe"]):
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

    # 从 blocks 中提取媒体列表（用于下载/渲染）
    block_media = [
        {
            "type": b["type"],
            "url": b["url"],
            "order": i,
            "inline_position": -1.0,
        }
        for i, b in enumerate(b for b in content_blocks if b["type"] in {"image", "video"})
    ]

    # 提取非内容图片（OG meta、视频等）
    page_media = _extract_page_media(soup, base_url=final_url)
    # 合并：优先用 block_media（有正文顺序），再加 OG 图和其它媒体
    block_urls = {m["url"] for m in block_media}
    extra_media = [m for m in page_media if m["url"] not in block_urls]
    media_urls = block_media + extra_media if (block_media or extra_media) else None

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
    fallback_root = _find_article_root(soup)
    if fallback_root:
        text = fallback_root.get_text(separator="\n", strip=True)
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

    if media_urls:
        fallback_text = _clean_text(blocks_text or _html_meta(soup, "og:description") or title.strip())
        return ExtractResult(
            title=title.strip(),
            text=fallback_text,
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
        if result and (len(result.text) > 20 or result.media_urls):
            return result
        logger.info("平台 %s 提取失败，回退到通用提取器", platform)

    # 通用提取器
    result = await extract_generic(url)
    if result and (len(result.text) > 20 or result.media_urls):
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
