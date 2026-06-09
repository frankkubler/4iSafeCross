---
applyTo: "{templates/**/*.html,static/js/**/*.js,static/css/**/*.css}"
description: "Use when editing 4iSafeCross web UI: Flask templates, zone editor assets, and frontend interactions with API endpoints."
---
# Frontend Instructions — 4iSafeCross

## Scope

Applies to HTML templates and static JS/CSS assets.

## Core Rules

- Do not break existing API calls used by dashboards and zone editor.
- Keep zone editor interactions compatible with `/api/zones/<cid>`, `/api/masks/<cid>`, `/api/relay_positions/<cid>`.
- Preserve readable operator UX in industrial context (high contrast, clear state labels, low ambiguity).
- Avoid introducing heavy client-side processing that increases UI latency.

## Integration Rules

- If request/response payloads change, update backend, UI, and docs together.
- Keep static assets paths and template names stable unless migration is explicit.
- Do not hardcode secrets or environment data in frontend files.

## Validation Checklist

- Main page renders without JS errors.
- Zone editor loads and saves zones successfully.
- Live views and key status panels still render.

## Common Policy (Harmonized)

- Security: destructive commands and destructive operations targeting sensitive directories require explicit user confirmation (ask mode via hooks).
- API stability: preserve public JSON response contracts unless an explicit breaking-change request is given.
- Minimum validation: run the repository API smoke check before PR and report failing routes with actionable details.
- Observability: prefer `logging` for diagnostics and keep production traces usable for debugging.
- Documentation sync: any endpoint behavior change must be reflected in README/docs and related customization files.
