# Lessons

- When the user asks for an application-level sidebar, do not interpret collapse as a compact rail unless they explicitly ask for it. Default to either fully visible or fully hidden, and always leave a stable reveal control.
- When a localhost page makes the whole machine lag, do not stop after fixing request frequency alone. Verify the render/compositing layer too, especially repeated `backdrop-filter`, large blur, and animated background effects on card-heavy screens.
- When aligning to a provided frontend reference, do not lock the page into `body { overflow: hidden; }` plus nested scroll containers unless the design explicitly requires an app-shell viewport. Default to natural document scrolling.
- Do not collapse all same-day timestamps into `刚刚`. Encode explicit thresholds for minutes, hours, and days so relative time labels stay accurate.
- Do not reuse destructive action button styles for neutral folder operations. Folder and move actions need their own visual treatment.
- When a sidebar can be collapsed, keep the re-open control inside the same toolbar/layout flow. Floating reveal buttons can leave visual duplicates and expose stale width constraints that only show up in the collapsed state.
- When the user gives a concrete sidebar reference, match its interaction model directly. Do not swap a rail-style in-place collapse for a separate header control unless they ask for a different behavior.
- When polishing UI against screenshots, verify collapsed rails and edge controls with a real render pass. Old state-specific padding and fragile SVG icons can both survive code review but fail immediately in the actual viewport.
- When a SaaS migration checklist asks for the tenancy boundary, do not treat a provisional `workspace` layer as final architecture. Keep the first migration slice reversible and switch to the user-confirmed boundary before building more features on top of it.
- When introducing request-scoped auth helpers into an existing backend, avoid top-level imports that bounce through `tenant -> auth -> models/database -> tenant`. Use a lazy wrapper for the session-dependent accessor instead of creating a circular import chain.
- When issuing persistent auth sessions, treat optional request metadata like `User-Agent` and client IP as best-effort only. Do not assume those headers are always present, or login can fail on perfectly valid callback or native-client traffic.
- When a login provider must be visible before authentication, do not store its enablement/config only in per-user settings. Pre-login provider discovery needs an app-level config source that anonymous session/bootstrap endpoints can read.
- In one-time-code login flows, do not stop after verifying that the code record exists. Also test the full post-verification path that creates the user session and cookie, or users will see a misleading second-order error like `No active verification code` after the real failure already consumed the code.
- When adapting a mobile shortcut or external client, do not assume it will match the browser payload contract. Verify the exact auth header and request body shape first, then make the backend accept that concrete protocol.
- When the user asks for a mobile UI that is "just one centered pill input", remove helper sections and secondary controls instead of keeping extra cards, titles, or action rows.
