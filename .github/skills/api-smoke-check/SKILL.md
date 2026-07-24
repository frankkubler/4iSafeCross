---
name: api-smoke-check
description: 'Run a quick Flask API smoke test for 4iSafeCross endpoints. Use after backend/UI changes, before PR, and when validating failsafe, zones, and inference stats routes.'
argument-hint: 'Optional base URL, default http://localhost:5050'
user-invocable: true
---

# API Smoke Check — 4iSafeCross

Quick workflow to validate that core Flask routes still behave nominally.

## Goal

Validate core API availability, failsafe route health, and upstream inference integration reachability.

## When to Use

- After modifying [src/web/](src/web/) routes, [src/core/](src/core/) modules, [src/inference.py](src/inference.py), [src/alert_manager.py](src/alert_manager.py)
- Before opening a PR
- After config/runtime changes affecting API behavior

## Inputs

- Optional argument: base URL
- Default base URL: `http://localhost:5050`

Examples:
- `/api-smoke-check`
- `/api-smoke-check http://127.0.0.1:5050`

## Procedure

1. Resolve base URL from argument; fallback to `http://localhost:5050`.
2. Health and safety checks:
   - `GET /`
   - `GET /failsafe_status`
   - `GET /cache_stats`
   - `GET /api/inference/stats`
3. Basic media/API checks for camera `0`:
   - `GET /snapshot/0`
   - `GET /api/zones/0`
   - `GET /api/masks/0`
   - `GET /api/relay_positions/0`
4. Check configured upstream inference servers from [utils/constants.py](utils/constants.py):
   - validate `URL_YOLO` and `URL_RFDETR` are reachable (at least root/health responds).
   - if unreachable, report as integration risk (not necessarily app regression).
5. Run lightweight local tests if impacted:
   - `python test_detections_format.py`
   - `python test_zone_editor.py` (if zone editor/API changed)
6. Summarize pass/fail per check and report first actionable error.

## Suggested Commands

```bash
BASE_URL="http://localhost:5050"

# Core checks
curl -sS -f "$BASE_URL/" | head -c 300 | cat
curl -sS -f "$BASE_URL/failsafe_status" | cat
curl -sS -f "$BASE_URL/cache_stats" | cat
curl -sS -f "$BASE_URL/api/inference/stats" | cat

# Camera/API checks
curl -sS -f "$BASE_URL/snapshot/0" -o /tmp/4isafecross_snapshot.jpg && file /tmp/4isafecross_snapshot.jpg
curl -sS -f "$BASE_URL/api/zones/0" | cat
curl -sS -f "$BASE_URL/api/masks/0" | cat
curl -sS -f "$BASE_URL/api/relay_positions/0" | cat

# Upstream inference server reachability (from utils/constants.py)
python - <<'PY'
from utils.constants import URL_YOLO, URL_RFDETR
print('URL_YOLO=', URL_YOLO)
print('URL_RFDETR=', URL_RFDETR)
PY

# Optional local tests
python test_detections_format.py
```

## Success Criteria

- Every required route returns HTTP 200.
- JSON routes return valid JSON with expected top-level keys.
- Snapshot route returns a valid JPEG file.
- Upstream inference URLs are readable and reported for integration diagnostics.

## Notes

- Keep this smoke test lightweight and fast.
- If endpoint contracts change, update this skill and [README.md](README.md) together.
- For operational changes, align with docs under [docs/deployment/](docs/deployment/) and [docs/security/](docs/security/).
