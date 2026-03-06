# Frontend Layout Refinement

- [x] Rework card/list metadata and sync badge styling so the footer reads cleaner and removes the time stamp
- [x] Convert the detail modal to a solid white reading surface with fullscreen toggle and sticky bottom actions
- [x] Improve settings modal grouping and field rhythm so Notion/Obsidian sections look intentional instead of stacked raw inputs
- [x] Rebuild list-row layout and selection states to avoid hover overflow, improve alignment, and create clearer visual focus
- [x] Verify the updated inline script and review the final diff for interaction regressions

## Review

- Card and list footers now show date-only metadata, cleaner sync badges, and a more consistent action cluster so the lower information layer reads in one scan.
- Detail modal now uses a pure white reading surface, a top-right fullscreen toggle, and a dedicated bottom action bar that stays available while scrolling long content.
- Settings are regrouped into clearer section cards with better label rhythm and status placement for Notion, Obsidian, and auto-sync.
- List rows now render as independent aligned cards with fixed right-column structure and active-state emphasis instead of clipped hover scaling inside one large container.
- Verified the HTML parses and the inline script compiles successfully after the DOM and interaction changes.

# Restore Inline Web Images

- [x] Restore web article rendering so images stay in content flow instead of falling back to detached gallery placement
- [x] Keep the recent UI refresh, but fix detail modal logic so normal website entries prefer the original structured image order
- [x] Add a safer fallback for broken extracted HTML/block data so repeated or missing inline images do not destroy the reading layout
- [x] Verify representative generic/web entries still show thumbnails and detail images after the renderer change

## Review

- Detail modal now restores website entries through a dedicated renderer that prefers structured content blocks, falls back to stored article HTML, and only uses a generated inline layout when the saved inline data is clearly broken.
- Repeated-image edge cases are now detected before rendering, so malformed extracted HTML no longer causes one duplicated image to replace the full article layout.
- The modal title is explicitly refreshed again, and article HTML now forces normal whitespace so the newer reading-surface styles do not distort original paragraph and image flow.
- Verified against current local item data that generic/web entries now route through the intended renderer paths instead of always collapsing into the detached text-plus-gallery fallback.

# Command Palette Refresh

- [x] Replace the existing simplified Command K layout with the preferred search-header and suggestion-list composition
- [x] Reconnect the current extract flow, keyboard shortcuts, overlay dismissal, and autofocus behavior to the new panel
- [x] Add explicit loading motion for URL extraction and clipboard import so the panel has clear in-place feedback
- [x] Verify the updated inline HTML and script compile cleanly after the Command K refactor

## Review

- Command K now uses the new centered glass panel with search icon, large inline input, ESC keycap, and suggestion rows instead of the old title-plus-pill form.
- The primary action keeps the existing `/api/extract` workflow but now shows loading inside the suggestion row, which matches the new layout more cleanly than the old pill button.
- Clipboard import is now a real action with its own loading state and fills the input directly without breaking the existing `Enter`, `Esc`, and `⌘K / Ctrl+K` interactions.
- Verified the HTML parses and the inline script still compiles after replacing the panel DOM and associated event wiring.

# Knowledge Sync Reliability Fixes

- [x] Rework Notion sync so page creation uses structured content order instead of flattening into "all images then all text"
- [x] Add Notion remote-existence checks and clear stale sync IDs when the remote page was deleted
- [x] Switch Notion image handling to local file uploads with external-URL fallback so signed or anti-hotlink image URLs stop breaking page creation
- [x] Fix Obsidian note path encoding and media upload paths so titles containing spaces, `%`, or Unicode punctuation no longer fail
- [x] Limit Obsidian uploads to media actually referenced by the note and keep note embeds inline inside one Markdown document
- [x] Add front-end sync status refresh so deleted remote pages/notes stop showing as already synced in the library
- [x] Verify the updated backend routes compile and spot-check the new helpers against real local item records

## Review

- Notion sync now builds children from stored structured blocks when available, uploads local images through the Notion file upload flow, appends overflow blocks beyond the first 100, and verifies an existing `notion_page_id` before deciding a record is already synced.
- Obsidian sync now percent-encodes vault paths, keeps attachments grouped under `EverythingCapture_Media/<item-id>/`, uploads only referenced media instead of the whole scraped asset set, and rebuilds the note body from the same structured block order used by the reader.
- The library now calls a lightweight remote status refresh after loading items, which clears stale `notion_page_id` / `obsidian_path` values in both the database and UI when the remote content was deleted.
- Verified with `python3 -m py_compile` and with runtime helper checks inside the project virtualenv for structured block parsing, encoded Obsidian paths, and inline media embedding behavior.

# Obsidian Reliability Pass

- [x] Reproduce the real Obsidian integration against the local REST API instead of relying on static reasoning
- [x] Fix stale Obsidian status detection so missing or wrong-content notes no longer appear as synced
- [x] Eliminate same-title note collisions by switching new note paths to `标题-短ID.md`
- [x] Add optional Obsidian target folder setting and surface the actual write location in Settings
- [x] Add a real Obsidian write/read/delete probe endpoint and verify it against the live local API
- [x] Re-sync the failing Douyin sample and confirm the created note can be read back from Obsidian

## Review

- Confirmed the active Obsidian service is reachable at `https://127.0.0.1:27124`, not the previously stored `http://` URL, and the backend now persists the working base URL after a successful probe or sync.
- The previously failing Douyin entry now syncs to a unique path, `1.7亿阅读的“人生作弊码”，教你一天“重装你的人生系统” #个人成长-f905b87b.md`, and read-back verification confirmed the note contains the expected frontmatter and body in Obsidian.
- Duplicate-title records no longer share the same `obsidian_path`; stale paths are cleared when the remote note is missing or belongs to a different item, which fixes the false-positive “已同步” state in the library.
- Settings now expose the Obsidian target folder and an explicit write-location hint, so the UI shows that writes go to the currently opened Obsidian vault root unless a folder is configured.

# Restore HTML-First Sync Formatting

- [x] Reproduce the current fallback path for items that have `canonical_html` but no `content_blocks_json`
- [x] Add an HTML-to-structured-block fallback for Notion and Obsidian sync so image positions stay inline
- [x] Preserve richer Markdown text formatting from stored article HTML when building Obsidian notes
- [x] Add regression tests covering inline image order and markdown formatting from `canonical_html`
- [x] Verify the backend compiles and the new tests pass locally

## Review

- Root cause was the sync fallback path: records with `canonical_html` but no `content_blocks_json` were rebuilt from `canonical_text` plus a trailing media list, which always pushed images to the bottom and stripped rich-text structure.
- Sync now rebuilds ordered blocks from stored article HTML before falling back to plain-text paragraphs, so existing generic web captures preserve inline image placement without needing re-extraction.
- Obsidian note generation now emits markdown for headings, lists, quotes, code fences, links, and emphasis from the stored HTML structure instead of flattening everything into raw paragraphs.
- Notion child generation now uses the same HTML-derived ordered blocks, including headings, list items, quotes, code blocks, dividers, and inline image placement, and the sync target resolver now supports both legacy `database_id` and current `data_source_id` targets.
- Notion sync now auto-creates `Date`, `Source`, and `Platform` properties on the writable data source when missing, writes those values on each synced page, and formats the stored date string as `MM/DD HH:MM`.
- Obsidian frontmatter now writes `date` in the same `MM/DD HH:MM` format instead of ISO timestamps.
- Verified with `python -m py_compile`, an expanded `unittest` suite, and real end-to-end writes to both Obsidian and Notion using temporary items that exercised the exact regression case: `canonical_html` present, `content_blocks_json` missing, images expected to remain inline, and the new schema/time-format requirements. The temporary remote artifacts were cleaned up after read-back verification.
