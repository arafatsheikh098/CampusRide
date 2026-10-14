# DECISIONS.md

Log of small in-scope decisions made when the spec was ambiguous. One line per entry: `YYYY-MM-DD — decision — rationale`.

- 2026-10-14 — Dependency manager: pinned `requirements.txt` (no Poetry/uv) — the smallest option that satisfies "pin all versions" and uses the allowed stack as written.
- 2026-10-14 — UI: vendored HTMX (no inline scripts, CSP `script-src 'self'`) plus a small `app/static/js/app.js` for theme/lang cookie reads; light/dark theme is selected by the `cr_theme` cookie with `prefers-color-scheme: dark` as the auto-default — gives an attractive dynamic UI without adding endpoints or dependencies outside the allowed stack.
- 2026-10-14 — M1 ships all SQLModel entities (Job, Heartbeat, User, etc.) so later milestones add behaviour, not schema churn. Schema is exactly the spec; the route modules exist as bare routers only and get real endpoints in their milestone — keeping M1 minimal while keeping migrations a single linear series.
- 2026-10-14 — `/me/theme` and `/me/lang` are M1 deliverable because the spec says "GET /health; security headers; custom 404/500" and the user requested a dynamic UI. The toggles are tiny and CSP-safe.
