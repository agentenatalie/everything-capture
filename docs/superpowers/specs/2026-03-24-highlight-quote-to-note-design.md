# Text Highlighting & Quote-to-Note Design

## Overview

Add persistent text highlighting to the article reader, with the ability to quote highlighted text into page notes. Users can select text, choose a highlight color, and optionally send the quoted text into a new or existing note.

## Data Model

### New Table: `highlights`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID PK | Highlight ID |
| `item_id` | FK → items | Associated article |
| `user_id` | FK → users | Owner |
| `workspace_id` | FK → workspaces | Workspace |
| `color` | String(16) | Color key: `yellow` / `green` / `blue` / `red`. Default `yellow` |
| `text` | Text | Selected plain text (for display and fallback matching) |
| `selector_path` | String | CSS selector path from `modalContent` to the start text node's parent element |
| `start_text_node_index` | Integer | Index of the start text node among its parent's childNodes |
| `start_offset` | Integer | Character offset within start text node |
| `end_selector_path` | String | CSS selector path to end text node's parent element (may differ for cross-node selections) |
| `end_text_node_index` | Integer | Index of the end text node among its parent's childNodes |
| `end_offset` | Integer | Character offset within end text node |
| `context_before` | Text | ~100 chars before the selection (for fallback text matching) |
| `context_after` | Text | ~100 chars after the selection (for fallback text matching) |
| `page_note_id` | FK → item_page_notes, nullable, ON DELETE SET NULL | Linked note (if quoted to a note) |
| `created_at` | DateTime | Creation timestamp |
| `updated_at` | DateTime | Last modification timestamp |

**ORM model** added to `backend/models.py` as `Highlight` class:
- `Item.highlights = relationship("Highlight", back_populates="item", cascade="all, delete-orphan")`
- Add `highlights` relationship to `User` and `Workspace` models (following `ItemPageNote` pattern)
- `page_note_id` FK uses `ondelete="SET NULL"` — deleting a note clears the link, does not delete the highlight
- `workspace_id` defaults to `DEFAULT_WORKSPACE_ID` (matching existing pattern)

**Schema migration** in `database.py` `ensure_runtime_schema()`:
- `CREATE TABLE IF NOT EXISTS highlights (...)` with all columns
- Create indexes: `idx_highlights_item_id` on `item_id`, `idx_highlights_user_id` on `user_id`

## API Endpoints

Added to `backend/routers/items.py`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/items/{item_id}/highlights` | List all highlights for an article |
| POST | `/api/items/{item_id}/highlights` | Create a highlight |
| PATCH | `/api/items/{item_id}/highlights/{id}` | Update highlight (color, page_note_id) |
| DELETE | `/api/items/{item_id}/highlights/{id}` | Delete a highlight |

### Schemas (in `backend/schemas.py`)

**HighlightCreateRequest:**
```
color: Literal["yellow", "green", "blue", "red"] = "yellow"
text: str
selector_path: str
start_text_node_index: int
start_offset: int
end_selector_path: str
end_text_node_index: int
end_offset: int
context_before: str = ""
context_after: str = ""
page_note_id: Optional[str] = None
```

**HighlightUpdateRequest:**
```
color: Optional[Literal["yellow", "green", "blue", "red"]] = None
page_note_id: Optional[str] = None
```

**HighlightResponse:**
```
id: str
item_id: str
color: str
text: str
selector_path: str
start_text_node_index: int
start_offset: int
end_selector_path: str
end_text_node_index: int
end_offset: int
context_before: str
context_after: str
page_note_id: Optional[str]
created_at: datetime
updated_at: datetime
```

GET endpoint returns highlights sorted by `created_at ASC` (document order approximation).

## Frontend Interaction

All frontend code lives in existing files — no new JS files created.

### Selection → Floating Toolbar (`app-items.js`)

1. Listen for `mouseup` on `modalContent` element.
2. Check `window.getSelection()` for non-empty, non-collapsed selection.
3. Show a floating toolbar positioned above the selection (using `Range.getBoundingClientRect()`).
4. Toolbar contains:
   - 4 color dots (yellow, green, blue, red) — click to highlight with that color.
   - A "quote to note" button (document icon) — highlights in yellow + quotes to note.
5. Toolbar dismissed on: click outside, Esc key, or new selection start (`mousedown`).

### Highlight Creation

1. User clicks a color dot.
2. Compute CSS selector paths and offsets from the selection Range.
3. POST to create highlight.
4. Wrap selected text in `<mark class="highlight-{color}" data-highlight-id="{id}">`.
5. Clear selection, dismiss toolbar.

### Cross-Node Mark Wrapping

For selections spanning multiple DOM nodes:
- Split into segments: start node (from startOffset to end), middle nodes (fully wrapped), end node (from 0 to endOffset).
- Each segment gets its own `<mark>` element with the same `data-highlight-id`.

### Quote to Note

1. Click "quote to note" button.
2. Determine target note:
   - If sidebar has an active note in edit mode (`activePageNoteId` is set and `pageNoteViewMode === 'source'`): use that note's ID.
   - Otherwise: POST create a new page note with content `> {quoted text}\n\n` and title derived from the quoted text (first ~30 chars + "..."). Use the new note's ID.
3. POST create highlight (yellow by default) with `page_note_id` set to the target note ID (single request, no separate PATCH needed).
4. If appending to existing note: append `\n\n> {quoted text}\n\n` to the textarea and trigger auto-save.
5. Open sidebar on the pageNotes tab if not already visible. Set `activePageNoteId` and switch to source mode if a new note was created.

### Click on Existing Highlight

1. Click on a `<mark>` element with `data-highlight-id`.
2. Show a small popover near the mark with:
   - 4 color dots (current color has a checkmark).
   - "Quote to note" button.
   - "Delete" button (trash icon).
3. Color change → PATCH update + swap CSS class.
4. Delete → DELETE request + unwrap `<mark>` (preserve inner text).
5. Quote to note → same flow as above, linking to existing highlight.

### Restoring Highlights on Article Open

In `openModalByItem()`, after rendering article content:

1. GET `/api/items/{item_id}/highlights`.
2. For each highlight, attempt CSS selector + offset restoration:
   - `document.querySelector(selector_path)` to find the text node.
   - Create a Range with the stored offsets.
   - Wrap in `<mark>`.
3. If selector restoration fails (node not found or text mismatch), fallback:
   - Search `modalContent.textContent` for `context_before + text + context_after`.
   - If found, compute the DOM range from the text position and wrap.
4. If both fail, skip silently (highlight data preserved in DB for future attempts).

### CSS Selector Path Generation

From a text node, walk up to `modalContent`:
- If an ancestor has an `id`, start from `#id`.
- Otherwise, build `tagName:nth-child(n)` at each level.
- Final path example: `#modalContent > div:nth-child(2) > p:nth-child(3)`.
- The selector path points to the **parent element** of the text node.
- `start_text_node_index` / `end_text_node_index` identify which childNode is the text node (e.g., `<p>Hello <em>world</em> foo</p>` has childNodes: [text"Hello ", em, text" foo"] — index 0 or 2 for the text nodes).

### Frontend Cache

```javascript
const highlightsByItem = new Map();        // itemId → highlights[]
const highlightsLoadStateByItem = new Map(); // itemId → 'idle'|'loading'|'loaded'
```

Cache cleared when article is re-extracted or content changes.

### Edge Cases

- **Content re-extraction**: If article HTML changes (e.g., user triggers re-parse), stored selector paths may become invalid. Highlights are preserved in DB; restoration falls back to text matching. If both fail, highlights are silently skipped (not deleted — the text field still holds the quoted content).
- **Overlapping highlights**: If a user highlights text that overlaps an existing highlight, both `<mark>` elements are nested. This is visually acceptable (colors blend). No deduplication needed.
- **Empty selection / toolbar inside mark**: Clicking inside an existing `<mark>` opens the highlight popover, not the new-highlight toolbar. The `mouseup` handler checks `event.target.closest('mark[data-highlight-id]')` first.

## CSS Styles (in `frontend/css/index.css`)

### Highlight Colors

```css
mark.highlight-yellow { background: rgba(255, 212, 0, 0.3); cursor: pointer; border-radius: 2px; }
mark.highlight-green  { background: rgba(72, 199, 142, 0.3); cursor: pointer; border-radius: 2px; }
mark.highlight-blue   { background: rgba(66, 153, 225, 0.3); cursor: pointer; border-radius: 2px; }
mark.highlight-red    { background: rgba(245, 101, 101, 0.3); cursor: pointer; border-radius: 2px; }

mark[class*="highlight-"]:hover {
  filter: brightness(0.92);
}
```

### Floating Toolbar

```css
.highlight-toolbar {
  position: absolute;
  z-index: 1000;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 6px 10px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  display: flex;
  align-items: center;
  gap: 8px;
}
```

Color dots: 20px circles with the highlight color, border on hover. Quote button: icon button matching existing toolbar styles.

### Highlight Popover (click existing mark)

Same visual style as toolbar but smaller, with color dots + delete + quote actions.

## Files Modified

| File | Changes |
|------|---------|
| `backend/models.py` | Add `Highlight` ORM model |
| `backend/database.py` | Add CREATE TABLE in `ensure_runtime_schema()` |
| `backend/schemas.py` | Add `HighlightCreateRequest`, `HighlightUpdateRequest`, `HighlightResponse` |
| `backend/routers/items.py` | Add 4 highlight endpoints |
| `frontend/js/app-items.js` | Selection listener, toolbar, mark wrapping, highlight restore, cache |
| `frontend/css/index.css` | Highlight colors, toolbar styles, popover styles |

No new files created.
