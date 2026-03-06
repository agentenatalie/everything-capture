# Notion / Obsidian / ZIP Fix

- [x] Read root project documentation and handover notes
- [x] Trace the `Notion settings are incomplete` failure path
- [x] Reproduce ZIP, Notion sync, and Obsidian sync from the backend runtime context
- [x] Fix backend path handling so runtime cwd no longer changes the active database/static directory
- [x] Fix Notion sync so it can auto-resolve a single accessible page/database target and sync successfully
- [x] Fix ZIP export so Unicode titles no longer crash `Content-Disposition`
- [x] Improve Obsidian sync compatibility for HTTPS self-signed localhost and `PUT /vault/{path}`
- [x] Verify the updated flow with local checks and live Notion API calls

## Review

- ZIP root cause: non-ASCII item titles were inserted directly into the `Content-Disposition` header, which triggered a `UnicodeEncodeError`.
- Runtime path root cause: the app depended on relative `./items.db` and `static/...` paths, so behavior changed with the process cwd.
- Notion root cause: the saved token could see one accessible Notion page target but no saved target ID in app settings. The sync flow now auto-discovers and reuses that single target. Live sync succeeded and wrote `notion_page_id=31ba7a1e-dabc-8105-9fcf-ec111f5d6fd9` for item `71aff06f-5e9a-4c61-b03a-30ac6ca15d3b`.
- Obsidian runtime evidence: the Local REST API plugin is installed and configured in `/Users/hbz/Documents/Obsidian Vault/.obsidian/plugins/obsidian-local-rest-api/data.json`, but macOS has no listener on ports `27124` or `27123`, so the server itself is not currently running.
