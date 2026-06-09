---
applyTo: "{config/**/*.ini,scripts/**,docker-compose.yml,Dockerfile,.env,.env.example}"
description: "Use when editing 4iSafeCross operational and sensitive configuration files: INI config, deployment scripts, Docker runtime, and environment variables."
---
# Ops & Config Instructions — 4iSafeCross

## Scope

Applies to runtime configuration and deployment-related files.

## Core Rules

- Treat `config/`, `.env`, `scripts/`, and container files as safety-critical.
- Do not relax security or fail-safe defaults without explicit request.
- Keep backward compatibility of config keys used by runtime loaders.
- Never commit real credentials/secrets.

## Deployment Safety

- Any change impacting systemd/deployment scripts must preserve rollback path.
- Avoid destructive operations on `db/` and `dataset/` in automation scripts.
- Keep Jetson-specific assumptions explicit in docs when changed.

## Validation Checklist

- Config parses cleanly at startup.
- No secret leakage introduced.
- Deployment docs updated when operational behavior changes.

## Common Policy (Harmonized)

- Security: destructive commands and destructive operations targeting sensitive directories require explicit user confirmation (ask mode via hooks).
- API stability: preserve public JSON response contracts unless an explicit breaking-change request is given.
- Minimum validation: run the repository API smoke check before PR and report failing routes with actionable details.
- Observability: prefer `logging` for diagnostics and keep production traces usable for debugging.
- Documentation sync: any endpoint behavior change must be reflected in README/docs and related customization files.
