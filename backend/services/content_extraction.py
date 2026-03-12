from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from paths import STATIC_DIR


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


def _format_timestamp(seconds: float) -> str:
    rounded = max(int(round(float(seconds))), 0)
    hours = rounded // 3600
    minutes = (rounded % 3600) // 60
    remaining_seconds = rounded % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _render_extracted_text(
    *,
    detected_title: str,
    urls: list[str],
    qr_links: list[str],
    ocr_text: str,
    frame_texts: list[dict[str, Any]],
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
    if frame_texts:
        sections.append(
            "[frame_texts]\n"
            + "\n\n".join(
                f"{_format_timestamp(entry.get('timestamp_seconds', 0))}\n{entry.get('text', '')}".strip()
                for entry in frame_texts
                if str(entry.get("text", "")).strip()
            )
        )

    return "\n\n".join(section for section in sections if section.strip()).strip()


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
    frame_texts: list[dict[str, Any]] = []
    qr_links: list[str] = []

    if has_images or has_videos:
        extractor_output = _run_swift_media_extractor(
            images=media_inputs["images"],
            videos=media_inputs["videos"],
        )

        image_results = extractor_output.get("images", []) if isinstance(extractor_output, dict) else []
        for image_result in image_results:
            ocr_text = _normalize_text_block(image_result.get("ocr_text"))
            if ocr_text:
                ocr_sections.append(ocr_text)
                urls.extend(_extract_urls_from_text(ocr_text))
            urls.extend(_extract_urls_from_text("\n".join(image_result.get("urls") or [])))
            qr_links.extend(image_result.get("qr_links") or [])

        video_results = extractor_output.get("videos", []) if isinstance(extractor_output, dict) else []
        for video_result in video_results:
            qr_links.extend(video_result.get("qr_links") or [])
            urls.extend(_extract_urls_from_text("\n".join(video_result.get("urls") or [])))
            for frame in video_result.get("frame_texts") or []:
                text = _normalize_text_block(frame.get("text"))
                if not text:
                    continue
                frame_entry = {
                    "timestamp_seconds": float(frame.get("timestamp_seconds") or 0),
                    "text": text,
                }
                frame_texts.append(frame_entry)
                urls.extend(_extract_urls_from_text(text))

    ocr_text = "\n\n".join(_unique_preserve_order(ocr_sections))
    frame_texts = [
        entry
        for entry in sorted(frame_texts, key=lambda value: (float(value.get("timestamp_seconds") or 0), value.get("text") or ""))
        if entry.get("text")
    ]
    urls = _unique_preserve_order([value for value in urls if value])
    qr_links = _unique_preserve_order(
        [normalized for normalized in (_normalize_http_url(value) for value in qr_links) if normalized]
    )

    extracted_text = _render_extracted_text(
        detected_title=detected_title,
        urls=urls,
        qr_links=qr_links,
        ocr_text=ocr_text,
        frame_texts=frame_texts,
    )

    return ContentParseResult(
        extracted_text=extracted_text,
        ocr_text=ocr_text,
        frame_texts=frame_texts,
        urls=urls,
        qr_links=qr_links,
        detected_title=detected_title,
        source_type=_build_source_type(has_images, has_videos),
        parse_status="completed",
        parsed_at=datetime.utcnow(),
    )

