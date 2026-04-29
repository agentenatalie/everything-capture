"""URL extraction from email parts (subject, text/plain, text/html).

This software is licensed under Elastic License 2.0; see the LICENSE file.
"""
from __future__ import annotations

import re
from email.message import Message

from bs4 import BeautifulSoup

_URL_RE = re.compile(r'https?://[^\s<>"\'\)\]]+', re.IGNORECASE)
_TRAILING_PUNCT = ".,;:!?)]}>'\""


def _strip_trailing_punct(url: str) -> str:
    while url and url[-1] in _TRAILING_PUNCT:
        url = url[:-1]
    return url


def _find_in_text(text: str) -> list[str]:
    if not text:
        return []
    return [_strip_trailing_punct(m) for m in _URL_RE.findall(text)]


def _find_in_html(html: str) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if href.lower().startswith(("http://", "https://")):
            found.append(_strip_trailing_punct(href))
    found.extend(_find_in_text(soup.get_text(" ", strip=True)))
    return found


def extract_bodies(msg: Message) -> tuple[str, str]:
    """Return (plain_text, html) bodies, concatenating all matching parts."""
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = (part.get_content_type() or "").lower()
            if ctype == "text/plain":
                plain_parts.append(_decode_part(part))
            elif ctype == "text/html":
                html_parts.append(_decode_part(part))
    else:
        ctype = (msg.get_content_type() or "").lower()
        body = _decode_part(msg)
        if ctype == "text/html":
            html_parts.append(body)
        else:
            plain_parts.append(body)

    return ("\n".join(p for p in plain_parts if p), "\n".join(p for p in html_parts if p))


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def extract_urls(*, subject: str, plain: str, html: str) -> list[str]:
    """Collect URLs from subject + plain + html, dedup preserving first occurrence."""
    candidates: list[str] = []
    candidates.extend(_find_in_text(subject))
    candidates.extend(_find_in_text(plain))
    candidates.extend(_find_in_html(html))
    cleaned = [u for u in (s.strip() for s in candidates) if u]
    return list(dict.fromkeys(cleaned))
