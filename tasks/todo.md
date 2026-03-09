# SaaS Foundation Todo

- [x] Write the current-system baseline document to the repo root for future migration reference
- [x] Introduce a default workspace and backfill current records so backend reads/writes are workspace-scoped
- [x] Stop returning saved integration secrets to the frontend while preserving the existing settings workflow
- [x] Let Obsidian connectivity tests validate the current modal values instead of only the last saved config
- [x] Shift the runtime ownership model to `user_id`, keeping the earlier workspace layer only as a transitional compatibility field
- [x] Encrypt saved Notion/Obsidian secrets at rest and migrate existing local settings rows away from plaintext
- [x] Move newly downloaded media into user-scoped paths and clean up local media files when an item is deleted
- [x] Start the auth/session groundwork: replace the default local user assumption with real logged-in users
- [x] Add real login entry points for Google OAuth, email verification code, and phone verification code
- [x] Gate the existing single-page library behind session bootstrap while preserving current reader/folder/settings UX
- [x] Add backend tests for auth session issuance, default-user claiming, verification-code consumption, and logout revocation
- [x] Allow Google OAuth to be configured from the settings UI via deployment-level app config instead of environment variables only
- [ ] Start the next SaaS slice: storage abstraction for object storage plus true full-text search infrastructure

## Review

- Added `/Users/hbz/everything-grabber/CURRENT_SYSTEM_BASELINE.md` as the frozen pre-SaaS implementation baseline.
- Introduced a default workspace model plus runtime schema backfill so items, media, folders, and settings all now carry workspace ownership without breaking the current single-user local workflow.
- Hardened the settings contract so `/api/settings` no longer returns saved Notion/Obsidian secrets in plaintext, and updated the settings modal to preserve saved secrets while allowing replacements.
- Updated Obsidian connectivity testing to accept the current visible modal values, removing the earlier dependency on “save first, then test”.
- Added a default local user and switched backend scoping to `user_id`, which matches the SaaS direction you chose while keeping old `workspace_id` columns in place temporarily for compatibility.
- Added encrypted-at-rest storage for Notion and Obsidian secrets using a local master key in `backend/.local/master.key` or `EVERYTHING_GRABBER_MASTER_KEY`, and migrated existing stored secrets to ciphertext on startup.
- New media now lands under user-scoped paths like `backend/static/media/users/{user_id}/{item_id}/...`, and deleting an item now removes its local media files plus emptied directories.
- Added a real auth/session backbone with persistent `auth_sessions` and `auth_verification_codes` tables, request-scoped session resolution, and `/api/auth/*` endpoints for Google OAuth, email codes, phone codes, session lookup, and logout.
- Reworked the single-file frontend so the app now boots through `/api/auth/session`, blocks unauthenticated access with a dedicated login overlay, and only loads the existing library/folder/settings experience after a real user session is present.
- Preserved the current local migration path by letting the first real login claim the former default local user, which keeps old single-user content attached to the first authenticated account instead of orphaning it.
- Added a deployment-level `app_config` layer for Google OAuth so the login screen can know whether Google is enabled before any user is signed in, while still letting the local operator manage the client ID/secret/redirect URI from the existing settings modal.

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
