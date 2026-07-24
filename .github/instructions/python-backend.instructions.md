---
applyTo: "{run.py,src/**/*.py,utils/**/*.py,test_*.py}"
description: "Use when editing Python backend code in 4iSafeCross: Flask routes, inference pipeline, alert/failsafe logic, relay control, and detection data contracts."
---
# Python Backend Instructions — 4iSafeCross

## Scope

Applies to backend Python files (Flask app, src modules, utils, tests).

## Core Rules

- Keep public endpoint contracts stable for frontend and automations.
- Preserve fail-safe behavior (startup relay ON, watchdog heartbeat, minimum ON timers).
- Avoid frame/inference performance regressions in hot paths.
- Prefer `logging` over `print()` for new diagnostics.
- Keep detection payload schema backward compatible unless explicitly requested.

## Sensitive Integrations

- Relay logic (`src/relay_pilot.py`, `src/alert_manager.py`) must remain safe-by-default.
- Inference and pose filtering (`src/inference.py`, `src/pose_analyser.py`) must not silently relax safety filters.
- License checks in [utils/license_validator.py](utils/license_validator.py) must not be bypassed.

## Cross-Repo API Coupling

- 4iSafeCross consumes external inference APIs configured in [utils/constants.py](utils/constants.py):
	- `URL_YOLO` + `FONCTION_YOLO`
	- `URL_RFDETR` + `FONCTION_RFDETR`
- Keep compatibility with detection payload fields expected by [src/inference.py](src/inference.py):
	- required: `x_min`, `y_min`, `x_max`, `y_max`, `confidence`, `class_id`
	- expected when available: `label`, `tracker_id`, `pose`, `personne_type`
- Any payload contract change must be coordinated with linked inference repos and reflected in tests.

## Validation Checklist

- App boots with no import/runtime error.
- Modified routes return valid JSON/stream responses on nominal requests.
- Failsafe status endpoint remains coherent after changes.
- Run affected tests when behavior changes.
- Validate upstream inference API compatibility (URL/function reachable and payload parseable by `InferenceServerThread`).

## Common Policy (Harmonized)

- Security: destructive commands and destructive operations targeting sensitive directories require explicit user confirmation (ask mode via hooks).
- API stability: preserve public JSON response contracts unless an explicit breaking-change request is given.
- Minimum validation: run the repository API smoke check before PR and report failing routes with actionable details.
- Observability: prefer `logging` for diagnostics and keep production traces usable for debugging.
- Documentation sync: any endpoint behavior change must be reflected in README/docs and related customization files.
