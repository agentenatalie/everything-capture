from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from paths import STATIC_DIR

logger = logging.getLogger(__name__)

_ffmpeg_path: str | None = None

_TRADITIONAL_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("融資融券", "融资融券"),
    ("證券交易所", "证券交易所"),
    ("收盤價", "收盘价"),
    ("開盤價", "开盘价"),
    ("漲跌幅", "涨跌幅"),
    ("漲跌", "涨跌"),
    ("換手率", "换手率"),
    ("總股本", "总股本"),
    ("總手", "总手"),
    ("總共", "总共"),
    ("自由流通股", "自由流通股"),
    ("流通股", "流通股"),
    ("科創板", "科创板"),
    ("創業板", "创业板"),
    ("新三板", "新三板"),
    ("滬股通", "沪股通"),
    ("深股通", "深股通"),
    ("港股通", "港股通"),
)
_TRADITIONAL_CHAR_TRANSLATION = str.maketrans(
    {
        "萬": "万",
        "與": "与",
        "專": "专",
        "業": "业",
        "東": "东",
        "創": "创",
        "絲": "丝",
        "兩": "两",
        "嚴": "严",
        "優": "优",
        "喚": "唤",
        "嗎": "吗",
        "國": "国",
        "圖": "图",
        "圍": "围",
        "場": "场",
        "塊": "块",
        "異": "异",
        "處": "处",
        "備": "备",
        "夠": "够",
        "學": "学",
        "實": "实",
        "寫": "写",
        "對": "对",
        "導": "导",
        "將": "将",
        "屆": "届",
        "層": "层",
        "屬": "属",
        "島": "岛",
        "帶": "带",
        "幣": "币",
        "庫": "库",
        "應": "应",
        "廣": "广",
        "張": "张",
        "強": "强",
        "彙": "汇",
        "後": "后",
        "從": "从",
        "徑": "径",
        "恆": "恒",
        "愛": "爱",
        "慮": "虑",
        "懷": "怀",
        "態": "态",
        "戶": "户",
        "拋": "抛",
        "掛": "挂",
        "採": "采",
        "擇": "择",
        "擔": "担",
        "據": "据",
        "擴": "扩",
        "擺": "摆",
        "數": "数",
        "斷": "断",
        "無": "无",
        "時": "时",
        "會": "会",
        "條": "条",
        "來": "来",
        "樣": "样",
        "機": "机",
        "標": "标",
        "權": "权",
        "歸": "归",
        "歲": "岁",
        "氣": "气",
        "內": "内",
        "沒": "没",
        "況": "况",
        "決": "决",
        "灣": "湾",
        "測": "测",
        "準": "准",
        "濟": "济",
        "為": "为",
        "營": "营",
        "獨": "独",
        "獲": "获",
        "畫": "画",
        "當": "当",
        "療": "疗",
        "發": "发",
        "盡": "尽",
        "監": "监",
        "盤": "盘",
        "眾": "众",
        "著": "着",
        "礎": "础",
        "禮": "礼",
        "離": "离",
        "種": "种",
        "稱": "称",
        "穩": "稳",
        "積": "积",
        "競": "竞",
        "筆": "笔",
        "簡": "简",
        "類": "类",
        "級": "级",
        "約": "约",
        "細": "细",
        "終": "终",
        "組": "组",
        "經": "经",
        "結": "结",
        "給": "给",
        "統": "统",
        "絕": "绝",
        "續": "续",
        "總": "总",
        "維": "维",
        "綱": "纲",
        "網": "网",
        "綠": "绿",
        "綜": "综",
        "緊": "紧",
        "線": "线",
        "練": "练",
        "縣": "县",
        "縱": "纵",
        "織": "织",
        "聽": "听",
        "職": "职",
        "聯": "联",
        "聲": "声",
        "聞": "闻",
        "腳": "脚",
        "腦": "脑",
        "臉": "脸",
        "臺": "台",
        "舉": "举",
        "舊": "旧",
        "藝": "艺",
        "節": "节",
        "華": "华",
        "葉": "叶",
        "術": "术",
        "號": "号",
        "雖": "虽",
        "衛": "卫",
        "補": "补",
        "裝": "装",
        "襲": "袭",
        "覺": "觉",
        "覽": "览",
        "觀": "观",
        "規": "规",
        "視": "视",
        "觸": "触",
        "訂": "订",
        "計": "计",
        "訊": "讯",
        "討": "讨",
        "訓": "训",
        "記": "记",
        "講": "讲",
        "註": "注",
        "設": "设",
        "許": "许",
        "論": "论",
        "證": "证",
        "評": "评",
        "詞": "词",
        "試": "试",
        "該": "该",
        "詳": "详",
        "語": "语",
        "誤": "误",
        "說": "说",
        "讀": "读",
        "課": "课",
        "調": "调",
        "談": "谈",
        "請": "请",
        "諸": "诸",
        "識": "识",
        "譜": "谱",
        "護": "护",
        "變": "变",
        "讓": "让",
        "貝": "贝",
        "財": "财",
        "責": "责",
        "貴": "贵",
        "貸": "贷",
        "費": "费",
        "資": "资",
        "賣": "卖",
        "賬": "账",
        "賠": "赔",
        "質": "质",
        "購": "购",
        "贏": "赢",
        "趨": "趋",
        "車": "车",
        "軟": "软",
        "轉": "转",
        "輪": "轮",
        "辦": "办",
        "這": "这",
        "進": "进",
        "遠": "远",
        "連": "连",
        "還": "还",
        "邊": "边",
        "達": "达",
        "遞": "递",
        "選": "选",
        "遺": "遗",
        "郵": "邮",
        "醫": "医",
        "釋": "释",
        "鈔": "钞",
        "錢": "钱",
        "錄": "录",
        "鐘": "钟",
        "鐵": "铁",
        "鑒": "鉴",
        "長": "长",
        "門": "门",
        "閉": "闭",
        "開": "开",
        "問": "问",
        "關": "关",
        "隊": "队",
        "際": "际",
        "陽": "阳",
        "陰": "阴",
        "階": "阶",
        "險": "险",
        "隨": "随",
        "難": "难",
        "雜": "杂",
        "雙": "双",
        "電": "电",
        "靈": "灵",
        "靜": "静",
        "響": "响",
        "頁": "页",
        "頂": "顶",
        "項": "项",
        "順": "顺",
        "預": "预",
        "領": "领",
        "頭": "头",
        "頻": "频",
        "顆": "颗",
        "題": "题",
        "顏": "颜",
        "願": "愿",
        "顯": "显",
        "風": "风",
        "飛": "飞",
        "飯": "饭",
        "飲": "饮",
        "館": "馆",
        "驗": "验",
        "體": "体",
        "點": "点",
        "齊": "齐",
        "個": "个",
        "麼": "么",
        "們": "们",
        "裡": "里",
        "價": "价",
        "額": "额",
        "綫": "线",
        "囉": "啰",
        "剛": "刚",
        "則": "则",
        "刪": "删",
        "剝": "剥",
        "區": "区",
        "協": "协",
        "單": "单",
        "卻": "却",
        "壓": "压",
        "壞": "坏",
        "壽": "寿",
        "奪": "夺",
        "婦": "妇",
        "寶": "宝",
        "審": "审",
        "尷": "尴",
        "屆": "届",
        "嶄": "崭",
        "幾": "几",
        "廳": "厅",
        "彌": "弥",
        "徵": "征",
        "懇": "恳",
        "懸": "悬",
        "扮": "扮",
        "挾": "挟",
        "摺": "折",
        "敵": "敌",
        "暫": "暂",
        "櫃": "柜",
        "殘": "残",
        "殼": "壳",
        "毀": "毁",
        "滾": "滚",
        "滿": "满",
        "滬": "沪",
        "漢": "汉",
        "潔": "洁",
        "燈": "灯",
        "爛": "烂",
        "狀": "状",
        "獎": "奖",
        "環": "环",
        "瑪": "玛",
        "畢": "毕",
        "癥": "症",
        "皺": "皱",
        "盞": "盏",
        "睏": "困",
        "矚": "瞩",
        "礙": "碍",
        "禍": "祸",
        "禦": "御",
        "竄": "窜",
        "籤": "签",
        "糧": "粮",
        "績": "绩",
        "纔": "才",
        "罷": "罢",
        "聖": "圣",
        "臨": "临",
        "蘇": "苏",
        "蝦": "虾",
        "術": "术",
        "藍": "蓝",
        "虧": "亏",
        "號": "号",
        "貯": "贮",
        "賦": "赋",
        "趕": "赶",
        "蹤": "踪",
        "遷": "迁",
        "醜": "丑",
        "針": "针",
        "鍋": "锅",
        "鑽": "钻",
        "陸": "陆",
        "雞": "鸡",
        "黃": "黄",
    }
)
_PARAGRAPH_BREAK_MARKERS = (
    "首先",
    "其次",
    "然后",
    "接下来",
    "另外",
    "最后",
    "再往下",
    "再看",
    "反过来",
    "总之",
    "下面",
    "这个时候",
    "那接下来",
    "那我们",
    "我们来看",
    "大家要注意",
)
_QUESTION_ENDINGS = ("吗", "呢", "吧", "是不是", "对不对", "行不行", "可不可以")
_SOFT_ENDINGS = ("因为", "所以", "但是", "不过", "然后", "以及", "还有", "而且", "如果", "比如", "例如")
_CJK_CHAR_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_CJK_SPACE_PATTERN = re.compile(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff])\s+(?=[\u3400-\u4dbf\u4e00-\u9fff])")
_LONG_CHUNK_BREAK_PATTERN = re.compile(
    r"(?<=[\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9])"
    r"(?=(?:首先|其次|然后|接下来|另外|最后|再往下|再看|反过来|总之|下面|这个时候|那接下来|那我们|我们来看|大家要注意))"
)


def _find_ffmpeg() -> str:
    """Locate ffmpeg binary once, checking PATH then common Homebrew locations."""
    global _ffmpeg_path
    if _ffmpeg_path is not None:
        return _ffmpeg_path
    import shutil

    path = shutil.which("ffmpeg")
    if not path:
        for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
            if Path(candidate).is_file():
                path = candidate
                break
    _ffmpeg_path = path or "ffmpeg"  # fall back to bare name, let subprocess raise if missing
    return _ffmpeg_path

HTTP_URL_PATTERN = re.compile(r"https?://[^\s<>'\"`]+", re.IGNORECASE)
SWIFT_SCRIPT_PATH = Path(__file__).with_name("media_text_extract.swift")
SWIFT_MODULE_CACHE_PATH = "/tmp/everything-capture-swift-module-cache"
SWIFT_CLANG_CACHE_PATH = "/tmp/everything-capture-swift-clang-cache"
DEFAULT_PARSE_STATUS = "idle"
SOURCE_TYPE_TEXT = "text"
SOURCE_TYPE_IMAGE = "image"
SOURCE_TYPE_VIDEO = "video"
SOURCE_TYPE_MIXED = "mixed"


class ContentExtractionError(RuntimeError):
    pass


@dataclass
class ContentParseResult:
    extracted_text: str
    ocr_text: str
    frame_texts: list[dict[str, Any]]
    urls: list[str]
    qr_links: list[str]
    detected_title: str
    source_type: str
    parse_status: str
    parsed_at: datetime
    parse_error: str | None = None


def _normalize_http_url(candidate: str | None) -> str | None:
    value = str(candidate or "").strip()
    if not value:
        return None
    trimmed = re.sub(r"[)\]}>.,!?;:'\"。，！？；：]+$", "", value)
    if not re.match(r"^https?://", trimmed, re.IGNORECASE):
        return None
    return trimmed


def _unique_preserve_order(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value or "").strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _normalize_text_block(value: str | None) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _to_simplified_chinese(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return ""
    for source, target in _TRADITIONAL_PHRASE_REPLACEMENTS:
        text = text.replace(source, target)
    return text.translate(_TRADITIONAL_CHAR_TRANSLATION)


def _normalize_video_fragment(value: str | None) -> str:
    text = _to_simplified_chinese(value)
    text = text.replace("\u3000", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = _CJK_SPACE_PATTERN.sub("", text)
    text = re.sub(r"\s+([，。！？；：、])", r"\1", text)
    text = re.sub(r"([（(])\s+", r"\1", text)
    text = re.sub(r"\s+([）)])", r"\1", text)
    text = re.sub(r"\bOK\b(?=\s*[\u3400-\u4dbf\u4e00-\u9fff])", "OK，", text)
    text = re.sub(r"([，。！？；：、]){2,}", lambda match: match.group(1), text)
    return text.strip()


def _split_long_video_chunk(value: str) -> list[str]:
    text = _normalize_video_fragment(value)
    if not text:
        return []
    if len(text) < 80:
        return [text]
    parts = [part.strip(" ，。") for part in _LONG_CHUNK_BREAK_PATTERN.split(text) if part.strip(" ，。")]
    return parts or [text]


def _ensure_sentence_punctuation(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if re.search(r"[。！？!?；;：:，,、]$", text):
        return text
    if re.search(r"[”\"')）\]]$", text) and re.search(r"[。！？!?；;：:，,、][”\"')）\]]$", text):
        return text
    if any(text.endswith(ending) for ending in _QUESTION_ENDINGS):
        return text + "？"
    if any(text.endswith(ending) for ending in _SOFT_ENDINGS):
        return text + "，"
    return text + "。"


def _paragraphize_video_sentences(sentences: list[str], *, source: str) -> str:
    if not sentences:
        return ""

    paragraphs: list[str] = []
    current: list[str] = []
    current_length = 0
    target_length = 120 if source == "transcript" else 90
    max_sentences = 4 if source == "transcript" else 3

    for sentence in sentences:
        normalized = sentence.strip()
        if not normalized:
            continue
        starts_new_paragraph = any(normalized.startswith(marker) for marker in _PARAGRAPH_BREAK_MARKERS)
        if current and (
            starts_new_paragraph
            or current_length + len(normalized) > target_length
            or len(current) >= max_sentences
        ):
            paragraphs.append("".join(current).strip())
            current = []
            current_length = 0
        current.append(normalized)
        current_length += len(normalized)

    if current:
        paragraphs.append("".join(current).strip())

    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


def _format_video_text_block(
    value: str | None,
    *,
    source: str,
    segments: list[str] | None = None,
) -> str:
    raw_segments = segments if segments is not None else str(value or "").splitlines()
    sentence_candidates: list[str] = []

    for segment in raw_segments:
        for chunk in _split_long_video_chunk(segment):
            if not chunk:
                continue
            sentence_candidates.append(_ensure_sentence_punctuation(chunk))

    if not sentence_candidates and value:
        fallback = _normalize_video_fragment(value)
        if fallback:
            sentence_candidates = [_ensure_sentence_punctuation(fallback)]

    formatted = _paragraphize_video_sentences(sentence_candidates, source=source)
    return _normalize_text_block(formatted)


def _extract_urls_from_text(value: str | None) -> list[str]:
    matches = HTTP_URL_PATTERN.findall(str(value or ""))
    return _unique_preserve_order(
        [normalized for normalized in (_normalize_http_url(match) for match in matches) if normalized]
    )


def _first_meaningful_line(value: str | None) -> str:
    for raw_line in str(value or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            return line[:200]
    return ""


def _render_extracted_text(
    *,
    detected_title: str,
    urls: list[str],
    qr_links: list[str],
    ocr_text: str,
    subtitle_text: str = "",
    transcript_text: str = "",
) -> str:
    sections: list[str] = []

    if detected_title:
        sections.append(f"[detected_title]\n{detected_title}")
    if urls:
        sections.append("[urls]\n" + "\n".join(urls))
    if qr_links:
        sections.append("[qr_links]\n" + "\n".join(qr_links))
    if ocr_text:
        sections.append("[ocr_text]\n" + ocr_text)
    if subtitle_text:
        sections.append("[subtitle_text]\n" + subtitle_text)
    if transcript_text:
        sections.append("[transcript_text]\n" + transcript_text)

    return "\n\n".join(section for section in sections if section.strip()).strip()


def _find_video_companion_text(video_path: Path) -> tuple[str, str]:
    """Look for a subtitle or transcript companion file next to the video.

    Returns (text, source) where source is 'subtitle' or 'transcript'.
    """
    stem = video_path.stem
    parent = video_path.parent
    for filename, source in [
        (f"{stem}.subtitle.txt", "subtitle"),
        (f"{stem}.transcript.txt", "transcript"),
    ]:
        candidate = parent / filename
        if candidate.exists():
            text = _format_video_text_block(
                candidate.read_text(encoding="utf-8", errors="ignore"),
                source=source,
            )
            if text:
                return text, source
    return "", ""


def parse_subtitle_lines(raw: str) -> str:
    """Parse SRT/VTT subtitle content into plain text.

    Strips cue numbers, timestamps, VTT headers, and inline tags.
    Deduplicates consecutive identical lines.
    """
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip VTT headers, SRT cue numbers, and timestamp lines
        if stripped.startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        if "-->" in stripped:
            continue
        if re.match(r"^\d+$", stripped):
            continue
        cleaned = re.sub(r"<[^>]+>", "", stripped).strip()
        if cleaned:
            lines.append(cleaned)
    # Deduplicate consecutive identical lines (common in auto-generated subs)
    deduped: list[str] = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped)


def _extract_embedded_subtitles(video_path: Path) -> str:
    """Extract the first embedded subtitle track from a video file using ffmpeg.

    Returns plain text with timestamps and markup stripped, or '' if no subtitle
    track exists or ffmpeg is unavailable.
    """
    srt_path = video_path.with_suffix(".tmp_sub.srt")
    try:
        subprocess.run(
            [_find_ffmpeg(), "-y", "-i", str(video_path), "-map", "0:s:0", str(srt_path)],
            capture_output=True,
            check=True,
            timeout=60,
        )
        if not srt_path.exists():
            return ""
        return _format_video_text_block(
            parse_subtitle_lines(srt_path.read_text(encoding="utf-8", errors="ignore")),
            source="subtitle",
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.debug("Embedded subtitle extraction failed for %s: %s", video_path.name, exc)
        return ""
    finally:
        try:
            srt_path.unlink(missing_ok=True)
        except OSError:
            pass


def _transcribe_video_with_mlx_whisper(video_path: Path) -> str:
    """Transcribe video audio using mlx-whisper (Apple Silicon, free, local).

    Requires: pip install mlx-whisper
    Model is downloaded on first use (~244 MB for small).
    """
    try:
        import mlx_whisper  # type: ignore[import]
    except ImportError:
        return ""
    # mlx-whisper shells out to ffmpeg internally; ensure it can be found.
    ffmpeg = _find_ffmpeg()
    ffmpeg_dir = str(Path(ffmpeg).parent)
    if ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + ":" + os.environ.get("PATH", "")
    try:
        result = mlx_whisper.transcribe(
            str(video_path),
            path_or_hf_repo="mlx-community/whisper-small-mlx",
            language="zh",
            condition_on_previous_text=False,
            initial_prompt="以下是普通话视频内容，请使用简体中文输出，并补充自然的中文标点。",
        )
        segments = [
            str(entry.get("text", "")).strip()
            for entry in (result.get("segments") or [])
            if str(entry.get("text", "")).strip()
        ]
        return _format_video_text_block(
            str(result.get("text", "")).strip(),
            source="transcript",
            segments=segments or None,
        )
    except Exception as exc:
        logger.debug("mlx-whisper transcription failed for %s: %s", video_path.name, exc)
        return ""


def _resolve_media_inputs(item) -> dict[str, list[dict[str, str]]]:
    images: list[dict[str, str]] = []
    videos: list[dict[str, str]] = []

    for media in sorted(item.media or [], key=lambda entry: (entry.display_order, entry.original_url or "")):
        local_path = str(getattr(media, "local_path", "") or "").strip()
        if not local_path:
            continue
        absolute_path = (STATIC_DIR / local_path).resolve()
        if not absolute_path.exists():
            continue

        media_type = str(getattr(media, "type", "") or "").lower()
        media_input = {
            "path": str(absolute_path),
            "type": media_type,
            "relative_path": local_path,
        }
        if media_type in {"image", "cover"}:
            images.append(media_input)
        elif media_type == "video":
            videos.append(media_input)

    return {"images": images, "videos": videos}


def _swift_available() -> bool:
    return bool(SWIFT_SCRIPT_PATH.exists() and Path("/usr/bin/swift").exists())


def _summarize_swift_failure(stderr: str | None, stdout: str | None) -> str:
    lines = []
    for raw_line in (stderr or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "warning:" in line:
            continue
        if re.match(r"^\d+\s+\|", line):
            continue
        if re.match(r"^[|`-]+\s*", line) and "error:" not in line:
            continue
        lines.append(line)

    if lines:
        for line in reversed(lines):
            if "error:" in line or not line.startswith("/"):
                return line
        return lines[-1]

    fallback = (stdout or stderr or "Swift extractor failed").strip()
    return fallback or "Swift extractor failed"


def _run_swift_media_extractor(*, images: list[dict[str, str]], videos: list[dict[str, str]]) -> dict[str, Any]:
    if not _swift_available():
        raise ContentExtractionError("No local media text extractor is available.")

    os.makedirs(SWIFT_MODULE_CACHE_PATH, exist_ok=True)
    os.makedirs(SWIFT_CLANG_CACHE_PATH, exist_ok=True)

    payload = {
        "images": [{"path": entry["path"]} for entry in images],
        "videos": [{"path": entry["path"]} for entry in videos],
    }

    request_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as request_file:
            request_path = request_file.name
            json.dump(payload, request_file, ensure_ascii=False)

        env = os.environ.copy()
        env["SWIFT_MODULECACHE_PATH"] = SWIFT_MODULE_CACHE_PATH
        env["CLANG_MODULE_CACHE_PATH"] = SWIFT_CLANG_CACHE_PATH

        completed = subprocess.run(
            ["/usr/bin/swift", "-suppress-warnings", str(SWIFT_SCRIPT_PATH), request_path],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if completed.returncode != 0:
            raise ContentExtractionError(_summarize_swift_failure(completed.stderr, completed.stdout))

        output = (completed.stdout or "").strip()
        if not output:
            return {"images": [], "videos": []}
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise ContentExtractionError("Swift extractor returned invalid JSON.") from exc
    finally:
        if request_path:
            try:
                os.unlink(request_path)
            except OSError:
                pass


def _build_source_type(has_images: bool, has_videos: bool) -> str:
    if has_images and has_videos:
        return SOURCE_TYPE_MIXED
    if has_videos:
        return SOURCE_TYPE_VIDEO
    if has_images:
        return SOURCE_TYPE_IMAGE
    return SOURCE_TYPE_TEXT


def parse_item_content(item) -> ContentParseResult:
    title = str(getattr(item, "title", "") or "").strip()
    canonical_text = _normalize_text_block(getattr(item, "canonical_text", None))
    urls = _extract_urls_from_text(canonical_text)
    detected_title = title or _first_meaningful_line(canonical_text)

    media_inputs = _resolve_media_inputs(item)
    has_images = bool(media_inputs["images"])
    has_videos = bool(media_inputs["videos"])

    ocr_sections: list[str] = []
    qr_links: list[str] = []
    subtitle_sections: list[str] = []
    transcript_sections: list[str] = []

    # Images: Swift OCR (unchanged)
    if has_images:
        try:
            extractor_output = _run_swift_media_extractor(
                images=media_inputs["images"],
                videos=[],
            )
        except ContentExtractionError as exc:
            if not has_videos and not canonical_text:
                raise
            logger.warning("图片 OCR 已跳过，Swift 提取器失败: %s", exc)
            extractor_output = {"images": []}
        image_results = extractor_output.get("images", []) if isinstance(extractor_output, dict) else []
        for image_result in image_results:
            ocr_text = _normalize_text_block(image_result.get("ocr_text"))
            if ocr_text:
                ocr_sections.append(ocr_text)
                urls.extend(_extract_urls_from_text(ocr_text))
            urls.extend(_extract_urls_from_text("\n".join(image_result.get("urls") or [])))
            qr_links.extend(image_result.get("qr_links") or [])

    # Videos: subtitle companion → embedded track → whisper transcription (no frame OCR, no QR)
    for video in media_inputs["videos"]:
        video_path = Path(video["path"])
        text, source = _find_video_companion_text(video_path)
        if text:
            logger.info("视频字幕来源: 伴生文件 (%s) %s", source, video_path.name)
        if not text:
            text = _extract_embedded_subtitles(video_path)
            if text:
                companion = video_path.parent / f"{video_path.stem}.subtitle.txt"
                try:
                    companion.write_text(text, encoding="utf-8")
                    logger.info("视频字幕来源: 嵌入字幕轨 → 缓存至 %s", companion.name)
                except OSError:
                    pass
                source = "subtitle"
        if not text:
            logger.info("无字幕，启动音频转录: %s", video_path.name)
            text = _transcribe_video_with_mlx_whisper(video_path)
            if text:
                transcript_path = video_path.parent / f"{video_path.stem}.transcript.txt"
                try:
                    transcript_path.write_text(text, encoding="utf-8")
                    logger.info("转录完成，缓存至 %s", transcript_path.name)
                except OSError:
                    pass
                source = "transcript"
        if text:
            text = _format_video_text_block(text, source=source or "transcript")
            if source == "subtitle":
                subtitle_sections.append(text)
            else:
                transcript_sections.append(text)

    # For video items the OCR comes from cover thumbnails only — discard it
    ocr_text = "" if has_videos else "\n\n".join(_unique_preserve_order(ocr_sections))
    subtitle_text = "\n\n".join(_unique_preserve_order(subtitle_sections))
    transcript_text = "\n\n".join(_unique_preserve_order(transcript_sections))
    urls = _unique_preserve_order([value for value in urls if value])
    qr_links = _unique_preserve_order(
        [normalized for normalized in (_normalize_http_url(value) for value in qr_links) if normalized]
    )

    extracted_text = _render_extracted_text(
        detected_title=detected_title,
        urls=urls,
        qr_links=qr_links,
        ocr_text=ocr_text,
        subtitle_text=subtitle_text,
        transcript_text=transcript_text,
    )

    return ContentParseResult(
        extracted_text=extracted_text,
        ocr_text=ocr_text,
        frame_texts=[],
        urls=urls,
        qr_links=qr_links,
        detected_title=detected_title,
        source_type=_build_source_type(has_images, has_videos),
        parse_status="completed",
        parsed_at=datetime.utcnow(),
    )
