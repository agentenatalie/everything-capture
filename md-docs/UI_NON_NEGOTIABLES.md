# UI Non-Negotiables

This file is the single source of truth for UI changes on this project.

If you are changing the UI, read this first.

## Purpose

The website UI can be visually redesigned, but the content-reading behavior must not be broken again.

The image placement logic in the detail view has already been restored multiple times.
It is now a protected behavior.

## Absolute Do-Not-Touch Rules

### 1. Website article images must stay inline in the reading flow

For normal website / web / generic / WeChat article content:

- Do not move article images into a detached top gallery.
- Do not move article images into a detached bottom gallery.
- Do not replace inline article rendering with "text first, all images later".
- Do not simplify the renderer in a way that loses the original image positions.

Required rendering priority:

1. `content_blocks_json`
2. `canonical_html`
3. inline fallback renderer

This priority must stay intact.

## 2. Social media and web articles are different and must stay different

`xiaohongshu` and `douyin` are allowed to render media in a top carousel / gallery style.

Normal web articles are not.

Do not merge these two rendering paths into one simplified renderer.

## 3. Card click behavior must never be broken by UI refactors

If cards are clickable, the modal-opening DOM and JS contract must remain valid.

The following IDs/functions are required by the current UI:

- `modalTitle`
- `modalContent`
- `modalFooter`
- `readerStatusDots`
- `toggleFullscreenBtn`
- `closeModal`
- `openModalById(...)`
- `openModalByItem(...)`

If any of these are removed or renamed, card clicks can silently fail.

## 4. Do not remove the modal title node while keeping title writes in JS

Current JS writes:

- `modalTitle.innerText = item.title || '无标题'`

So the `#modalTitle` element must exist whenever the detail modal exists.

## 5. Do not destroy thumbnail behavior while restyling cards

Card/list thumbnails are part of the browsing UX.

Do not remove or break:

- `getItemThumbnail(...)`
- card preview image rendering
- list preview image rendering

Visual restyling is allowed.
Thumbnail presence and click behavior are not optional.

## Protected File / Area

Current protected logic lives mainly in:

- `backend/static/index.html`

Especially:

- web article rendering logic
- modal DOM structure
- card click wiring
- thumbnail rendering

## What Is Safe To Change

These are safe to change if behavior is preserved:

- spacing
- colors
- borders
- shadows
- glassmorphism / flat / minimal / etc. visual direction
- toolbar layout
- button styling
- typography
- card visual styling
- modal visual styling

## What Must Be Verified After Any UI Change

After any UI refactor, manually verify all of the following:

1. Clicking a gallery card opens the detail modal.
2. Clicking a list row opens the detail modal.
3. A normal web article still shows images inline where they belong.
4. A Xiaohongshu item still shows gallery-style media correctly.
5. A Douyin item still shows video / cover correctly.
6. Card thumbnails still appear in gallery view.
7. Card thumbnails still appear in list view.
8. Modal title still updates correctly.
9. Close button still works.
10. Fullscreen toggle still works.

Do not consider a UI task complete until these checks pass.

## Change Policy

If a proposed UI simplification conflicts with these rules, do not do it.

Preserve behavior first.
Style changes come second.

If unsure, keep the existing rendering logic and only restyle the surrounding UI.
