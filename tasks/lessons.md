# Lessons

- When the user asks for an application-level sidebar, do not interpret collapse as a compact rail unless they explicitly ask for it. Default to either fully visible or fully hidden, and always leave a stable reveal control.
- When a localhost page makes the whole machine lag, do not stop after fixing request frequency alone. Verify the render/compositing layer too, especially repeated `backdrop-filter`, large blur, and animated background effects on card-heavy screens.
- When aligning to a provided frontend reference, do not lock the page into `body { overflow: hidden; }` plus nested scroll containers unless the design explicitly requires an app-shell viewport. Default to natural document scrolling.
- Do not collapse all same-day timestamps into `刚刚`. Encode explicit thresholds for minutes, hours, and days so relative time labels stay accurate.
- Do not reuse destructive action button styles for neutral folder operations. Folder and move actions need their own visual treatment.
- When a sidebar can be collapsed, keep the re-open control inside the same toolbar/layout flow. Floating reveal buttons can leave visual duplicates and expose stale width constraints that only show up in the collapsed state.
- When the user gives a concrete sidebar reference, match its interaction model directly. Do not swap a rail-style in-place collapse for a separate header control unless they ask for a different behavior.
- When polishing UI against screenshots, verify collapsed rails and edge controls with a real render pass. Old state-specific padding and fragile SVG icons can both survive code review but fail immediately in the actual viewport.
