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
