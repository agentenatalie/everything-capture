# Performance Investigation Todo

- [x] Review entry points and identify likely hot paths in the localhost page
- [x] Reproduce the slowdown locally and capture concrete evidence
- [x] Confirm the root cause(s) instead of applying generic optimizations
- [x] Implement the minimal fix set that removes the heavy work
- [x] Re-run verification and record the before/after result

# Frontend Alignment Todo

- [x] Compare the current library UI against the provided reference HTML
- [x] Remove the fixed viewport-style layout and restore natural page scrolling
- [x] Make file card bottom tags/actions stay pinned to the card bottom for consistent alignment
- [x] Fix relative-time thresholds to 5 minutes / 1 hour / 1 day / day count
- [x] Change the folder action hover treatment to blue instead of destructive red
- [x] Re-run a local verification pass for layout and rendering regressions

## Review

- Updated the design-sync overrides in `backend/static/index.html` so the library page uses document scrolling again instead of a fixed shell with nested scrolling.
- Reworked the gallery card content column so the tag/action bar is pinned to the bottom edge across short and long titles.
- Split the folder action into its own non-destructive button style and updated relative time formatting to the requested thresholds.

# Sidebar/Header UI Fix Todo

- [x] Reproduce the remaining sidebar collapse and header layout issues in the current board UI
- [x] Identify the exact CSS/JS interactions causing duplicate sidebar controls and header right-side gaps
- [x] Implement a coherent sidebar reveal pattern and tighten the toolbar layout so no empty header region remains
- [x] Re-run a local verification pass for desktop and narrow-width behavior

## Review

- Removed the detached header-side reveal control and rebuilt the sidebar around the provided reference pattern: an in-place 240px/64px width transition with a circular edge toggle that stays attached to the sidebar itself.
- Adapted the real folder navigation to the collapsed rail by adding glyph slots, hiding text/count/menu states cleanly, and collapsing search/group/footer content without leaving vertical text artifacts.
- Kept the toolbar full-width fix in place and re-verified the page with Playwright in expanded desktop, collapsed desktop, and narrow-width layouts using the local static HTML render.
