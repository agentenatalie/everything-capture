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
SWIFT_MODULE_CACHE_PATH = "/tmp/everything-grabber-swift-module-cache"
SWIFT_CLANG_CACHE_PATH = "/tmp/everything-grabber-swift-clang-cache"
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
            text = _normalize_text_block(candidate.read_text(encoding="utf-8", errors="ignore"))
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
        return parse_subtitle_lines(srt_path.read_text(encoding="utf-8", errors="ignore"))
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
        )
        return str(result.get("text", "")).strip()
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
            ["/usr/bin/swift", str(SWIFT_SCRIPT_PATH), request_path],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if completed.returncode != 0:
            raise ContentExtractionError((completed.stderr or completed.stdout or "Swift extractor failed").strip())

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
        extractor_output = _run_swift_media_extractor(
            images=media_inputs["images"],
            videos=[],
        )
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
            if source == "subtitle":
                subtitle_sections.append(text)
            else:
                transcript_sections.append(text)

    ocr_text = "\n\n".join(_unique_preserve_order(ocr_sections))
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

