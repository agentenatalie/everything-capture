"""Shared ranking utilities for the AI knowledge base.

Live AI retrieval indexes database `Item` snapshots from Everything Capture's own
`app.db`. The Markdown-note discovery/parsing helpers in this module are legacy
compatibility utilities and are not the default runtime retrieval source.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

_OBSIDIAN_APP_CONFIG_PATH = Path.home() / "Library/Application Support/obsidian/obsidian.json"
_DEFAULT_KNOWLEDGE_BASE_DIR = "Sources.base"
_INDEX_NOTE_NAMES = {"知识库目录.md"}
_SUMMARY_KEYS = ("summary", "摘要", "abstract")
_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9+#._/-]*|[\u4e00-\u9fff]+", re.IGNORECASE)
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
_H1_PATTERN = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
_TEXT_CODE_BLOCK_PATTERN = re.compile(r"```text\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_IMAGE_EMBED_PATTERN = re.compile(r"!\[\[[^\]]+\]\]")
_SOURCE_LINK_PATTERN = re.compile(r"\[Source\]\([^)]+\)")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")
_CHECKBOX_PATTERN = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+", re.MULTILINE)
_RECENT_QUERY_PATTERN = re.compile(r"(最近|近期|最新|recent|latest)", re.IGNORECASE)


@dataclass
class KnowledgeBaseNote:
    note_id: str
    title: str
    summary: str
    body: str
    excerpt: str
    extracted_text: str
    tags: list[str]
    folder: str
    source: str | None
    created_at: datetime | None
    relative_path: str
    item_id: str | None = None
    note_type: str | None = None
    term_weights: dict[str, float] = field(default_factory=dict, repr=False)
    vector_norm: float = field(default=0.0, repr=False)


@dataclass
class KnowledgeBaseSnapshot:
    root_path: str | None
    notes: list[KnowledgeBaseNote]
    loaded_at: datetime

    @property
    def note_count(self) -> int:
        return len(self.notes)

    @property
    def notes_by_item_id(self) -> dict[str, KnowledgeBaseNote]:
        return {
            note.item_id: note
            for note in self.notes
            if note.item_id
        }


_SNAPSHOT_CACHE: dict[str, tuple[int, float, KnowledgeBaseSnapshot]] = {}


def _clean_optional_string(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _strip_quotes(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped.startswith('"') and stripped.endswith('"'):
        try:
            return str(json.loads(stripped))
        except json.JSONDecodeError:
            return stripped[1:-1]
    if stripped.startswith("'") and stripped.endswith("'"):
        return stripped[1:-1]
    return stripped


def _parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}, text

    metadata: dict[str, object] = {}
    current_list_key: str | None = None
    for raw_line in lines[1:end_index]:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if current_list_key and re.match(r"^\s*-\s+", line):
            values = metadata.setdefault(current_list_key, [])
            if isinstance(values, list):
                values.append(_strip_quotes(re.sub(r"^\s*-\s+", "", line)))
            continue
        if ":" not in line:
            current_list_key = None
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            current_list_key = None
            continue
        if value:
            metadata[key] = _strip_quotes(value)
            current_list_key = None
        else:
            metadata[key] = []
            current_list_key = key

    body = "\n".join(lines[end_index + 1 :]).lstrip("\n")
    return metadata, body


def _parse_note_datetime(frontmatter_value: object | None, fallback_path: Path) -> datetime | None:
    value = _clean_optional_string(frontmatter_value)
    if value:
        now = datetime.now()
        for pattern in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%m/%d %H:%M",
            "%m/%d",
        ):
            try:
                parsed = datetime.strptime(value, pattern)
                if pattern in {"%m/%d %H:%M", "%m/%d"}:
                    year = now.year
                    hour = parsed.hour if "%H:%M" in pattern else 0
                    minute = parsed.minute if "%H:%M" in pattern else 0
                    return datetime(year, parsed.month, parsed.day, hour, minute)
                return parsed
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(fallback_path.stat().st_mtime)
    except OSError:
        return None


def _extract_h1_title(body: str) -> str | None:
    match = _H1_PATTERN.search(body or "")
    if not match:
        return None
    return _clean_optional_string(match.group(1))


def _filename_title(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"-[0-9a-f]{8}$", "", stem, flags=re.IGNORECASE)
    return stem.strip() or path.name


def _extract_summary(frontmatter: dict[str, object], body: str) -> str:
    for key in _SUMMARY_KEYS:
        value = frontmatter.get(key)
        if isinstance(value, list):
            joined = " ".join(_clean_optional_string(entry) or "" for entry in value).strip()
            if joined:
                return joined
        cleaned = _clean_optional_string(value)
        if cleaned:
            return cleaned

    cleaned_body = _clean_markdown(body)
    paragraphs = [line.strip() for line in cleaned_body.splitlines() if line.strip()]
    filtered = [
        paragraph
        for paragraph in paragraphs
        if not paragraph.startswith("#")
        and not paragraph.startswith("[Source]")
    ]
    for paragraph in filtered:
        if len(paragraph) >= 16:
            return paragraph[:280]
    return filtered[0][:280] if filtered else ""


def _extract_tags(frontmatter: dict[str, object]) -> list[str]:
    raw_tags = frontmatter.get("tags")
    if isinstance(raw_tags, list):
        return [tag for tag in (_clean_optional_string(value) for value in raw_tags) if tag]
    single = _clean_optional_string(raw_tags)
    if not single:
        return []
    if "," in single:
        return [part.strip() for part in single.split(",") if part.strip()]
    return [single]


def _extract_text_block(body: str) -> str:
    matches = [
        match.group(1).strip()
        for match in _TEXT_CODE_BLOCK_PATTERN.finditer(body or "")
        if match.group(1).strip()
    ]
    return "\n\n".join(matches).strip()


def _clean_markdown(body: str) -> str:
    cleaned = body or ""
    cleaned = _TEXT_CODE_BLOCK_PATTERN.sub(" ", cleaned)
    cleaned = _IMAGE_EMBED_PATTERN.sub(" ", cleaned)
    cleaned = _SOURCE_LINK_PATTERN.sub(" ", cleaned)
    cleaned = _CHECKBOX_PATTERN.sub("- ", cleaned)
    cleaned = _MARKDOWN_LINK_PATTERN.sub(r"\1", cleaned)
    cleaned = _INLINE_CODE_PATTERN.sub(r"\1", cleaned)
    cleaned = re.sub(r"^>\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _excerpt_from_body(body: str, limit: int = 320) -> str:
    text = _clean_markdown(body)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _expand_terms(token: str) -> list[str]:
    normalized = token.strip().lower()
    if not normalized:
        return []
    if _CJK_PATTERN.fullmatch(normalized):
        if len(normalized) <= 2:
            return [normalized]
        bigrams = [normalized[index : index + 2] for index in range(len(normalized) - 1)]
        return [normalized, *bigrams]
    return [normalized]


def extract_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in _TOKEN_PATTERN.finditer((text or "").lower()):
        terms.extend(_expand_terms(match.group(0)))
    return terms


def _add_weighted_terms(bucket: dict[str, float], text: str, weight: float) -> None:
    for term in extract_terms(text):
        bucket[term] = bucket.get(term, 0.0) + weight


def _build_note_term_weights(note: KnowledgeBaseNote) -> dict[str, float]:
    weights: dict[str, float] = {}
    _add_weighted_terms(weights, note.title, 3.2)
    _add_weighted_terms(weights, note.summary, 5.4)
    _add_weighted_terms(weights, " ".join(note.tags), 2.8)
    _add_weighted_terms(weights, note.folder, 1.7)
    _add_weighted_terms(weights, note.excerpt, 1.4)
    _add_weighted_terms(weights, note.extracted_text, 1.1)
    return weights


def _vector_norm(weights: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in weights.values()))


def prepare_note_for_similarity(note: KnowledgeBaseNote) -> KnowledgeBaseNote:
    note.term_weights = _build_note_term_weights(note)
    note.vector_norm = _vector_norm(note.term_weights)
    return note


def _cosine_similarity(left: dict[str, float], left_norm: float, right: dict[str, float], right_norm: float) -> float:
    if not left or not right or left_norm <= 0 or right_norm <= 0:
        return 0.0
    dot = 0.0
    if len(left) > len(right):
        left, right = right, left
    for key, value in left.items():
        dot += value * right.get(key, 0.0)
    if dot <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _note_sort_key(note: KnowledgeBaseNote) -> tuple[datetime, str]:
    return (note.created_at or datetime.min, note.relative_path)


def _iter_markdown_files(root_path: Path) -> Iterable[Path]:
    for path in root_path.rglob("*.md"):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(root_path).parts):
            continue
        yield path


def discover_knowledge_base_root() -> Path | None:
    vault_roots = _open_obsidian_vault_roots()
    if not vault_roots:
        return None

    for vault_root in vault_roots:
        candidate = vault_root / _DEFAULT_KNOWLEDGE_BASE_DIR
        if candidate.is_dir():
            return candidate

    for vault_root in vault_roots:
        if any((vault_root / name).is_file() for name in _INDEX_NOTE_NAMES):
            return vault_root

    return vault_roots[0]


def _open_obsidian_vault_roots() -> list[Path]:
    try:
        payload = json.loads(_OBSIDIAN_APP_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    roots: list[Path] = []
    for meta in (payload.get("vaults") or {}).values():
        if not isinstance(meta, dict) or not meta.get("open"):
            continue
        path = Path(str(meta.get("path") or "")).expanduser()
        if path.is_dir():
            roots.append(path)
    return roots


def _build_root_signature(root_path: Path) -> tuple[int, float]:
    count = 0
    latest_mtime = 0.0
    for note_path in _iter_markdown_files(root_path):
        count += 1
        try:
            latest_mtime = max(latest_mtime, note_path.stat().st_mtime)
        except OSError:
            continue
    return count, latest_mtime


def parse_knowledge_note(note_path: Path, root_path: Path) -> KnowledgeBaseNote | None:
    try:
        raw_text = note_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    frontmatter, body = _parse_frontmatter(raw_text)
    note_type = _clean_optional_string(frontmatter.get("type"))
    if note_type == "index" or note_path.name in _INDEX_NOTE_NAMES:
        return None

    relative_path = note_path.relative_to(root_path).as_posix()
    title = (
        _clean_optional_string(frontmatter.get("title"))
        or _extract_h1_title(body)
        or _filename_title(note_path)
    )
    summary = _extract_summary(frontmatter, body)
    excerpt = _excerpt_from_body(body)
    extracted_text = _extract_text_block(body)
    folder = (
        _clean_optional_string(frontmatter.get("folder"))
        or note_path.parent.relative_to(root_path).as_posix()
    )
    if folder == ".":
        folder = ""

    note = KnowledgeBaseNote(
        note_id=relative_path,
        title=title or _filename_title(note_path),
        summary=summary,
        body=body.strip(),
        excerpt=excerpt,
        extracted_text=extracted_text,
        tags=_extract_tags(frontmatter),
        folder=folder,
        source=_clean_optional_string(frontmatter.get("source")),
        created_at=_parse_note_datetime(frontmatter.get("date"), note_path),
        relative_path=relative_path,
        item_id=_clean_optional_string(frontmatter.get("item_id")),
        note_type=note_type,
    )
    return prepare_note_for_similarity(note)


def load_knowledge_base_snapshot() -> KnowledgeBaseSnapshot:
    root_path = discover_knowledge_base_root()
    if root_path is None:
        return KnowledgeBaseSnapshot(root_path=None, notes=[], loaded_at=datetime.utcnow())

    cache_key = root_path.as_posix()
    note_count, latest_mtime = _build_root_signature(root_path)
    cached = _SNAPSHOT_CACHE.get(cache_key)
    if cached and cached[0] == note_count and cached[1] == latest_mtime:
        return cached[2]

    notes: list[KnowledgeBaseNote] = []
    for note_path in _iter_markdown_files(root_path):
        note = parse_knowledge_note(note_path, root_path)
        if note is None:
            continue
        notes.append(note)

    notes.sort(key=_note_sort_key, reverse=True)
    snapshot = KnowledgeBaseSnapshot(
        root_path=root_path.as_posix(),
        notes=notes,
        loaded_at=datetime.utcnow(),
    )
    _SNAPSHOT_CACHE[cache_key] = (note_count, latest_mtime, snapshot)
    return snapshot


def rank_notes_for_query(snapshot: KnowledgeBaseSnapshot, query: str, limit: int = 8) -> list[tuple[KnowledgeBaseNote, float]]:
    normalized_query = (query or "").strip()
    if not normalized_query:
        return [(note, 0.0) for note in snapshot.notes[: max(1, limit)]]

    query_weights: dict[str, float] = defaultdict(float)
    _add_weighted_terms(query_weights, normalized_query, 1.0)
    query_norm = _vector_norm(query_weights)
    if query_norm <= 0:
        return [(note, 0.0) for note in snapshot.notes[: max(1, limit)]]

    wants_recent = bool(_RECENT_QUERY_PATTERN.search(normalized_query))
    lowered_query = normalized_query.lower()
    query_terms = [term for term in lowered_query.split() if len(term) >= 2]
    now = datetime.utcnow()

    scored: list[tuple[float, KnowledgeBaseNote]] = []
    for note in snapshot.notes:
        score = _cosine_similarity(query_weights, query_norm, note.term_weights, note.vector_norm)
        title_lower = note.title.lower()
        summary_lower = note.summary.lower()
        if lowered_query and lowered_query in title_lower:
            score += 0.95
        elif lowered_query and lowered_query in summary_lower:
            score += 0.7
        if note.folder and any(term in note.folder.lower() for term in query_terms):
            score += 0.2
        if note.tags and any(term in " ".join(note.tags).lower() for term in query_terms):
            score += 0.25
        # Full-text body substring matching for individual query terms
        if query_terms:
            body_lower = note.body.lower()
            body_hits = sum(1 for term in query_terms if term in body_lower)
            if body_hits > 0:
                score += min(0.4, body_hits * 0.12)
        # Source URL matching (helps find GitHub repos, specific websites, etc.)
        if note.source and query_terms:
            source_lower = note.source.lower()
            source_hits = sum(1 for term in query_terms if term in source_lower)
            if source_hits > 0:
                score += min(0.5, source_hits * 0.2)
        if wants_recent and note.created_at:
            age_days = max((now - note.created_at).total_seconds() / 86400.0, 0.0)
            score += max(0.0, 0.55 - age_days * 0.03)
        if score > 0:
            scored.append((score, note))

    scored.sort(key=lambda entry: (entry[0], entry[1].created_at or datetime.min, entry[1].relative_path), reverse=True)
    return [(note, round(score, 4)) for score, note in scored[: max(1, limit)]]


def expand_query_from_top_results(
    snapshot: "KnowledgeBaseSnapshot",
    query: str,
    seed_limit: int = 5,
) -> list[str]:
    """Local pseudo-relevance feedback: use top TF-IDF results to generate expanded queries.

    1. Run TF-IDF with original query → top seed_limit results
    2. Extract high-weight terms from those results' titles, tags, summaries
    3. Filter: prefer terms that appear in multiple seed results (more likely relevant)
    4. Return original query + expanded keyword strings

    This replaces AI-based query expansion with zero-latency local computation.
    """
    seed_results = rank_notes_for_query(snapshot, query, limit=seed_limit)
    if not seed_results:
        return [query]

    query_term_set = set(extract_terms(query))

    # Track both score and document frequency for each expansion term
    expansion_scores: dict[str, float] = defaultdict(float)
    expansion_doc_freq: dict[str, int] = defaultdict(int)

    for note, score in seed_results:
        weight = max(0.3, score)
        seen_in_note: set[str] = set()

        for term in extract_terms(note.title):
            if term not in query_term_set and len(term) >= 2:
                expansion_scores[term] += weight * 2.0
                seen_in_note.add(term)
        for tag in note.tags:
            for term in extract_terms(tag):
                if term not in query_term_set and len(term) >= 2:
                    expansion_scores[term] += weight * 1.5
                    seen_in_note.add(term)
        for term in extract_terms(note.summary):
            if term not in query_term_set and len(term) >= 2:
                expansion_scores[term] += weight * 0.5
                seen_in_note.add(term)

        for term in seen_in_note:
            expansion_doc_freq[term] += 1

    if not expansion_scores:
        return [query]

    # Boost terms that appear in multiple seed results (more likely genuinely related)
    # Filter out CJK bigrams that only appear once (likely noise like "键生", "撼更")
    final_terms: list[tuple[str, float]] = []
    for term, score in expansion_scores.items():
        df = expansion_doc_freq[term]
        is_cjk_bigram = len(term) == 2 and _CJK_PATTERN.fullmatch(term)
        if is_cjk_bigram and df < 2:
            continue  # skip noisy CJK bigrams that only appear in one result
        boosted_score = score * (1.0 + 0.5 * (df - 1))
        final_terms.append((term, boosted_score))

    final_terms.sort(key=lambda item: item[1], reverse=True)
    top_terms = [term for term, _ in final_terms[:20]]

    # Group into 2-3 expansion queries of ~6 terms each
    expanded_queries = [query]
    for i in range(0, min(len(top_terms), 18), 6):
        chunk = top_terms[i:i + 6]
        if chunk:
            expanded_queries.append(" ".join(chunk))

    return expanded_queries


def rank_notes_for_expanded_queries(
    snapshot: KnowledgeBaseSnapshot,
    queries: list[str],
    limit: int = 8,
) -> list[tuple[KnowledgeBaseNote, float]]:
    """Search with multiple query strings and merge results, keeping the best score per note."""
    if not queries:
        return []

    best_scores: dict[str, tuple[KnowledgeBaseNote, float]] = {}
    expanded_limit = max(limit, limit + 2)

    for query in queries:
        ranked = rank_notes_for_query(snapshot, query, limit=expanded_limit)
        for note, score in ranked:
            existing = best_scores.get(note.note_id)
            if existing is None or score > existing[1]:
                best_scores[note.note_id] = (note, score)

    merged = sorted(best_scores.values(), key=lambda entry: entry[1], reverse=True)
    return [(note, round(score, 4)) for note, score in merged[: max(1, limit)]]


def rank_related_notes(
    snapshot: KnowledgeBaseSnapshot,
    seed_note: KnowledgeBaseNote,
    *,
    limit: int = 5,
) -> list[tuple[KnowledgeBaseNote, float]]:
    if not seed_note.term_weights or seed_note.vector_norm <= 0:
        return []

    scored: list[tuple[float, KnowledgeBaseNote]] = []
    for note in snapshot.notes:
        if seed_note.item_id and note.item_id and note.item_id == seed_note.item_id:
            continue
        if note.note_id == seed_note.note_id:
            continue
        score = _cosine_similarity(seed_note.term_weights, seed_note.vector_norm, note.term_weights, note.vector_norm)
        if seed_note.folder and note.folder and seed_note.folder == note.folder:
            score += 0.18
        if seed_note.tags and note.tags:
            overlap = set(seed_note.tags) & set(note.tags)
            score += min(0.3, len(overlap) * 0.08)
        if score > 0:
            scored.append((score, note))

    scored.sort(key=lambda entry: (entry[0], entry[1].created_at or datetime.min, entry[1].relative_path), reverse=True)
    return [(note, round(score, 4)) for score, note in scored[: max(1, limit)]]
