# Tech Debt Audit — 4iSafeCross

Generated: 2026-07-30 · Commit: `441ad32` · Branch: `main`
Scope: full repository (~12 200 LOC Python/JS/HTML/CSS, 118 tracked files, 554 commits since 2025-07-23)

---

## Statut d'application (2026-07-30)

Le « Top 5 » puis la liste **Quick wins** ont été appliqués.

Findings **RESOLVED** : F001, F002 (code), F003, F005, F006, F007, F008, F009,
F010, F011, F015, F016, F020, F021, F022, F023, F024, F026, F028, F029, F033,
F034, F040, F041, F043, F044, F045, F056.

Findings **PARTIEL** :

- **F004** — le mécanisme d'authentification existe (HTTP Basic,
  `src/web/app_factory.py`) mais reste inactif tant que `SAFECROSS_AUTH_USER` /
  `SAFECROSS_AUTH_PASSWORD` ne sont pas définis sur la cible ; un avertissement
  est journalisé au démarrage. `/health` est explicitement exempté du défi
  d'authentification (le HEALTHCHECK Docker interroge sans identifiants).
- **F042** — le groupe `[dependency-groups] dev` existe et épingle
  `bandit`/`pip-audit`/`pytest`/`ruff`/`nuitka` via `uv.lock` ; la CI l'installe
  avec `uv sync --frozen --only-group dev`. Le pin `cython==3.2.8` reste dans le
  `Dockerfile` : il est déjà explicite, et déplacer la chaîne de build Cython
  vers un groupe `build` n'a pas été jugé justifié face au risque de casser le
  build multi-arch.
- **F049** — les quatre `print()` de `utils/constants.py` sont convertis en
  `logging.debug` (partie triviale). Le `load_config()` appelé depuis
  `bootstrap` reste à faire.

Détails notables :

- **F023** — la table `detections` n'est plus créée et `insert_detection` est
  supprimée (aucune écriture n'a jamais eu lieu). Les bases existantes
  conservent la table, vide et sans effet. README corrigé en conséquence.
- **F028** — `/health` renvoie 503 uniquement sur boot inachevé, module relais
  absent, ou zéro caméra en ligne. Le **mode fail-safe ne renvoie pas 503** :
  les relais y sont verrouillés en alerte, donc le système remplit sa fonction ;
  le signaler « unhealthy » entraînerait à ignorer la sonde au pire moment.
- **F033 / F034** — remplacés par deux helpers dans `src/core/caches.py` :
  `get_zone_color()` (lecture défensive sous verrou) et `invalidate_zones()`
  (vide overlays **et** couleurs), utilisés par les trois sites d'invalidation.

**Actions restant à la charge de l'exploitant** (non automatisables ici) :

- **F001** — les fichiers sont dé-suivis, mais la clé HMAC et la licence sont
  toujours dans l'historique git de tous les clones. **Régénérer la clé
  `license_state.key` et réémettre le `.lic`**, puis purger l'historique si le
  dépôt distant n'est pas strictement privé.
- **F002** — **révoquer les deux tokens Telegram** via BotFather. Les
  supprimer du code ne les invalide pas.
- **F004** — définir les deux variables d'authentification dans le `.env` de
  chaque site.
- **F006** — le premier déploiement après cette modification doit amorcer
  `/data/4isafecross` depuis l'image (`scripts/deploy-jetson.sh` le fait
  automatiquement ; voir le commentaire dans les fichiers compose pour la
  procédure manuelle).

Les autres findings du tableau ci-dessous sont inchangés.

---

## Executive summary

1. **`licenses/license_state.key` and `licenses/4isafecross.lic` are committed to git.** README.md:557 states in writing that these must never be versioned. The `.gitignore` rules that protected them (`config/license_state.key`) were never updated when commit `80fc3ec` moved the files to `licenses/`. The 32-byte HMAC key authenticates the local licence state — publishing it defeats the clock-rollback protection the licence system exists to provide.
2. **Two Telegram bot tokens are in the source tree and in git history** (`src/bot_aiogram.py:67`, `utils/constants.py:5`, reachable from `git log -S`). They are commented out, which does not un-leak them.
3. **The web UI has no authentication of any kind, and `/shutdown` (GET) and `/quit` (POST) kill the safety supervision.** The app binds `0.0.0.0:5050` under `network_mode: host`. `/quit` reaches `os._exit(0)` under waitress. Any device on the plant network can stop the pedestrian-detection system with one request.
4. **All runtime-mutable state lives inside the container with no volume.** `config/*.ini` (rewritten by the zone editor), `db/detections.db` (the relay-event audit trail), `detections/` and `dataset/` are baked into the image. The one volume that *is* mounted — `/app/data` — is referenced by no line of code. Every `docker compose pull && up` silently discards the site's zone geometry and relay history.
5. **Telegram detection alerts have never worked.** `src/alert_manager.py:223` awaits `send_detection_frame`, which is a synchronous `def` (`src/bot_aiogram.py:73`). The resulting `TypeError` is swallowed by the blanket `except Exception` at `alert_manager.py:225`.
6. **RTSP credentials are written to logs at INFO on every camera connect and reconnect** (`src/camera_manager.py:191` logs the full pipeline string, `src/core/bootstrap.py:157,159` log the credentialed URL). Those logs go to a `json-file` driver retained at 10 MB × 5.
7. **`config/zones.ini` — the safety-zone geometry — is rewritten non-atomically** (`utils/zone_writer.py:239`: open `"w"`, then write). A crash or power loss mid-save leaves a truncated file; the next boot loads fewer zones, or none, and supervises nothing without complaining.
8. **Test coverage is one function.** `test_detections_format.py` exercises `get_zone_for_detection` with bare asserts; `test_zone_editor.py` is not a test at all but a dev server that writes to the real `config/zones.ini`. `AGENTS.md:34,71` instructs contributors to run it before every PR. Nothing in either CI pipeline runs tests.
9. **The inference-server response is parsed with raw dict indexing** (`src/inference.py:366-385`). A contract change on the YOLO side raises `KeyError` outside the only `except` clause (`:405` catches `ConnectionError` only), killing the inference thread permanently. The fail-safe holds — relays latch ON — but detection never recovers without a restart.
10. **~1 900 lines of dead code ship in the production image**: `templates/preview.html` + `mockup.html` (1 561 lines, no route renders them), `src/context_vehicle.py` (139 lines, imported and never called), `utils/coco_classes.py` (176 lines, referenced only from a comment).

Counts: **4 Critical · 17 High · 26 Medium · 15 Low** (62 findings).
Debt concentration: `src/alert_manager.py` + `src/bot_aiogram.py` (alerting path, 8 findings), `src/collect_dataset.py` (duplication, 1 000 LOC), documentation/deployment drift (13 findings).

---

## Architectural mental model

4iSafeCross is a **single-process, heavily-threaded Flask application** whose real job is to hold a set of Yoctopuce relays in the correct state. `run.py` starts waitress (8 threads, no fork — chosen deliberately after `gunicorn`'s fork broke GStreamer, see commits `1e3f370` → `6409dea`) and calls `create_application()` in `src/core/bootstrap.py`, which executes a **fixed boot order that is itself an operational contract**: logging → asyncio loop → licence → *relays ON* → Telegram → zones/masks → alert manager → watchdog → cache → RTSP probe → cameras → inference threads → dataset → deferred relay-off.

Everything communicates through one module-level singleton, `src/core/state.py`. Around it run: N GStreamer capture threads (one per RTSP camera, each writing the latest frame into `frames[cid]` under a per-camera lock), N `InferenceServerThread`s (MOG2 motion gate → `np.save` the full 1080p frame → HTTP POST to an external YOLO/pose server → filter → callback), one asyncio loop thread that owns all relay-extinction timers, a heartbeat watchdog, a cache-cleanup thread, optional dataset threads, and the waitress request threads that generate MJPEG from the same frame buffers. There is no queue anywhere; coordination is entirely locks + shared dicts.

The safety invariant is inverted from a normal app: **relays default ON and only turn off once the system has proven it is working.** `failsafe.py` enforces this with a 30-second heartbeat, updated from the detection callback. Anything that stops the detection pipeline therefore fails *loud* (alarms latched on), which is correct — and which also means most of the bugs in this audit degrade the system into a permanently-alarming state rather than a silently-blind one. The two findings that break that property are F014 (zone reconfiguration disarms every relay) and F007 (config loss on image update).

Configuration is INI files parsed at *import time* in `utils/constants.py`, with `print()` calls that run before logging exists. Hot-reload paths rewrite the INI from the web UI and re-invoke the same loader functions. This is why `constants.py` is the single file excluded from Cython compilation (`setup_cython.py:18`, `Dockerfile:76`) — the rest of `src/` and `utils/` is compiled to `.so` and the `.py` sources deleted, for source protection.

**Where the model contradicts the README:** README.md:22-85 documents a structure that no longer exists — `requirements.txt` (deleted in `a1a300f`), `utils/license_validator.py` (replaced by the external `license-validator` package), and licence artefacts under `config/` (moved to `licenses/` in `80fc3ec`). README.md:910-948 still presents Nuitka as the build path; the actual pipeline has been Docker + Cython since `f6b6b6e`. README.md:94,314 specifies JetPack 6.2 / L4T 36.4.3 while `Dockerfile:82,249` targets JetPack 7.2 / L4T r39.2.0. That drift is itself finding F040-F046.

---

## Findings

| ID | Category | File:Line | Severity | Effort | Description | Recommendation |
|----|----------|-----------|----------|--------|-------------|----------------|
| F001 | Security | `licenses/license_state.key`, `licenses/4isafecross.lic` | Critical | S | Both are tracked by git. `.gitignore:6-8` only covers the old `config/` paths abandoned in commit `80fc3ec`. README.md:557 explicitly states they must not be versioned. The HMAC key authenticates the anti-rollback licence state. | `git rm --cached licenses/license_state.key licenses/4isafecross.lic`; add `licenses/*.lic`, `licenses/license_state.*` to `.gitignore`; rotate the HMAC key and reissue the licence; purge from history if the remote is not private. |
| F002 | Security | `src/bot_aiogram.py:67`, `utils/constants.py:5-6` | Critical | S | Two live-format Telegram bot tokens and a chat ID left in commented-out code, and present in git history from `6e2c019` onward. | Revoke both tokens via BotFather. Delete the comments. Treat history as compromised. |
| F003 | Security | `src/web/routes_system.py:215-229` | Critical | M | `/shutdown` (GET, no auth) releases all cameras; `/quit` (POST, no auth) reaches `os._exit(0)` because waitress provides no `werkzeug.server.shutdown`. GET means a prefetch or an `<img>` tag can trigger it. Called from `templates/index.html` via `fetch('/quit')`. | Delete both routes, or gate them behind an auth check and make `/shutdown` POST-only. There is no legitimate remote-kill requirement for a safety supervisor. |
| F004 | Security | `src/web/app_factory.py:15-40` | Critical | L | No authentication, session, or CSRF protection on any of the 32 registered routes. `POST /api/zones/<cid>` rewrites the safety-zone geometry; `POST /toggle_detection/<cid>` disables detection entirely; `POST /set_motion_param/<cid>` can set the motion threshold high enough to suppress all inference. Deployed with `network_mode: host` on `0.0.0.0:5050`. | Add a `before_request` auth hook on the blueprint set (shared secret header or basic auth behind TLS at minimum), and bind to the management interface rather than `0.0.0.0`. |
| F005 | Security | `src/camera_manager.py:191`; `src/core/bootstrap.py:140,157,159` | High | S | The RTSP password is embedded in `cam_id` and logged at INFO: `logger.info(f"Pipeline GStreamer [{self.backend}]: {pipeline_str}")` prints `rtsp://login:password@host:554/stream1`, on every connect and every reconnect. Same for the ping loop. Logs are retained by the json-file driver (50 MB). | Add a `_redact(url)` helper replacing the userinfo segment; apply at all four sites. |
| F006 | Reliability | `docker-compose-amd64.yml:32-35`, `docker-compose-arm64.yml:39-44` | Critical | M | No volume for `config/`, `db/`, `detections/`, or `dataset/`. The zone editor writes `config/zones.ini` inside the container layer. `/app/data` is mounted and referenced nowhere in the codebase (`grep -rn "app/data" src/ utils/` → 0 hits). Every image update discards site configuration and the relay-event audit trail. | Mount `./config:/app/config` and `./db:/app/db` (or point `DB_PATH`/`DATASET_OUTPUT_DIR` at `/app/data` and mount that). Verify a `docker compose pull && up -d` preserves zones before the next site deployment. |
| F007 | Correctness | `src/alert_manager.py:223` ↔ `src/bot_aiogram.py:73` | High | S | `await self.telegram_bot.send_detection_frame(...)` awaits a plain `def` returning `None` → `TypeError: object NoneType can't be used in 'await' expression`, swallowed at `alert_manager.py:225`. Telegram detection alerts have never fired. | Drop the `await` and dispatch via `loop.run_in_executor` (see F008), or make `send_detection_frame` a coroutine. Add an ERROR log that distinguishes send failure from send skipped. |
| F008 | Performance | `src/bot_aiogram.py:115` | High | M | `requests.post(..., timeout=30)` is synchronous and is called from inside the `on_detection` coroutine, i.e. on the same asyncio loop that owns every `_delayed_off_relay` timer. A stalled Telegram API can delay relay extinction by up to 30 s. Currently masked by F007 — fixing F007 alone activates this. | Wrap the send in `await loop.run_in_executor(None, self.send_frame_to_telegram, frame, caption)` when fixing F007. |
| F009 | Type & contract | `src/inference.py:366-385` | High | M | The external inference server's JSON is consumed with raw indexing (`d["x_min"]`, `d["class_id"]`, `float(d["confidence"])`). The enclosing `try` catches only `requests.ConnectionError` (`:405`), so a contract change raises out of `run()` and terminates the thread. Detection then never resumes; the watchdog latches relays ON after 30 s. AGENTS.md:22-24 names this as a cross-repo contract. | Validate the payload at the boundary: a small `_parse_detection(d)` returning `None` on malformed entries, plus a broad `except Exception` around the response-handling block that logs and continues the loop rather than exiting it. |
| F010 | Reliability | `utils/zone_writer.py:239-245` | High | S | `_write_ini_sections` opens the target with `"w"` (truncate) and writes in place. Used by all three savers for `zones.ini`, `masks.ini`, `relay_positions.ini`. A crash mid-write leaves truncated safety-zone config; `load_zones_by_camera_from_ini` then silently returns fewer zones. | Write to `ini_path + ".tmp"`, `f.flush()` + `os.fsync()`, then `os.replace()`. Three-line change, protects the most safety-relevant file in the repo. |
| F011 | Test debt | `test_zone_editor.py:23,166`; `AGENTS.md:34,71` | High | S | Not a test — a 203-line Flask dev server on port 5051 whose `POST /api/zones/<cid>` handler calls `save_zones_to_ini("config/zones.ini", ...)`, i.e. the production config. `AGENTS.md` lists it under "Tests rapides" and in the pre-PR checklist. | Rename to `tools/zone_editor_sandbox.py`, point `ZONES_INI_PATH` at a temp copy, and remove it from the AGENTS.md test list. |
| F012 | Test debt | `test_detections_format.py:16-60` | High | M | The entire automated test surface for ~12 200 LOC is one function (`get_zone_for_detection`), asserted with bare `assert` + `print`, no runner, no fixtures. No pytest config in `pyproject.toml`. | Add a `[dependency-groups] dev = ["pytest"]`, move both files under `tests/`, and start with the pure modules listed in F013. |
| F013 | Test debt | `src/core/failsafe.py`, `src/core/detection_pipeline.py:104-120`, `src/alert_manager.py:257-322`, `utils/zone_writer.py` | High | M | Zero coverage on the fail-safe watchdog, the per-zone debounce window, the 11-second relay hold, and INI round-tripping — all pure or trivially fakeable (no hardware, no licence), and all safety-relevant. `src/core/geometry.py:3` advertises itself as testable but only 1 of its 4 functions is covered. | Test in this order: `zone_writer` round-trip, `geometry.iou_overlap` / `create_mask_overlay`, debounce state machine with a fake clock, `_delayed_off_relay` with a fake relay. |
| F014 | Correctness | `src/alert_manager.py:342-345,356` | High | M | `set_zones` — reached from `POST /api/zones/<cid>` — calls `self.relays.action_off(relay_num)` for every currently-ON relay, then resets `relay_on` to all-`False`. Saving a zone from the web UI therefore disarms every alarm on every camera, with no grace period, and re-arms only on the next confirmed detection. This inverts the fail-safe invariant. | Re-arm to ON (matching `bootstrap.py:208`) after reconfiguration and let `_delayed_off_relay` decide, or apply the `STARTUP_GRACE_PERIOD` path. See open question Q2 if this is deliberate. |
| F015 | Error handling | `src/alert_manager.py:202-226` | High | S | One `try` / `except Exception` wraps the frame copy, the annotation drawing, the disk-save scheduling *and* the Telegram send, logging a single generic message. This is the mechanism that hid F007 for the life of the project. | Split into three narrow blocks with distinct log messages, or at minimum add `exc_info=True` so the traceback identifies which stage failed. |
| F016 | Error handling | `utils/constants.py:43-44,95-96` | High | S | `except Exception: pass` while extracting `cam_id` from an INI section name. A typo in `zones.ini` (`zone1_cam0 ` with a trailing space, `zone1_camO`) makes a safety zone silently vanish — no log, no startup warning, no visible difference in the UI beyond a missing overlay. | Log at WARNING with the offending section name, and log the loaded zone count per camera at INFO on boot. |
| F017 | Architectural decay | `src/collect_dataset.py:88-464` vs `:466-842` | High | L | Two full implementations of the same collector — `DatasetCollectionThread` (integrated) and `DatasetCollector` (standalone) — duplicating `_is_working_hours`, `_class_quota_reached`, `_increment_class_count`, `_init_log`, `_setup_dirs` and `_save_sample` with near-identical bodies across 1 000 lines. | Extract the sampling policy (working hours, quotas, filename/label formatting) into a `SamplingPolicy` class used by both, or delete the standalone path per F018. |
| F018 | Dead code | `src/collect_dataset.py:16,844-960` | Medium | S | The standalone mode is documented as `uv run scripts/collect_dataset.py`; that file does not exist. `Dockerfile:76` deletes every `.py` under `src/`, so `main()`, `parse_args()` and `split_dataset()` are unreachable in any deployed image. | Either restore a real `scripts/collect_dataset.py` entry point excluded from the Cython delete, or delete `DatasetCollector` + CLI (≈500 lines) and keep the integrated thread only. |
| F019 | Consistency | `src/collect_dataset.py:537-543,966-971` | Medium | S | `DatasetCollector` reads `config/config.ini` with its own `configparser` instead of `utils.constants`, and `main()` re-reads RTSP credentials from the INI only — bypassing the `RTSP_LOGIN`/`RTSP_PASSWORD` environment-variable precedence implemented at `utils/constants.py:169-170`. Standalone mode would connect with the (empty) INI credentials. | Import from `utils.constants` like every other module. |
| F020 | Dead code | `src/context_vehicle.py` (139 lines); imported at `src/inference.py:9` | Medium | S | `infer_in_vehicle_context` is imported and never called anywhere. The whole module is unreachable. Its `iou()` (`:14`) also duplicates `src/core/geometry.py:29` with different semantics (plain IoU vs `max(IoU, containment)`). | Delete the module and the import, or wire it in if the driver-context feature is still wanted (README.md:12 advertises it as one of the three anti-false-positive filters). |
| F021 | Dead code | `templates/preview.html` (1 072 lines), `templates/mockup.html` (489 lines) | Medium | S | Neither is rendered by any route — `render_template` appears only at `routes_ui.py:62,71` (index, zone_editor) and in `test_zone_editor.py:178`. Both are copied into the image by `Dockerfile:222,308`. Last touched 2026-03-16. | Delete, or move under `docs/mockups/` and add to `.dockerignore`. |
| F022 | Dead code | `utils/coco_classes.py` (176 lines); `src/alert_manager.py:12,381` | Medium | S | The only reference to `COCO_CLASSES` is a commented-out line. The import at `:12` is unused. | Delete both. |
| F023 | Dead code | `src/detection_db.py:9-20,35-43`; `src/alert_manager.py:10` | Medium | S | `insert_detection` is never called (the import is commented out) and the `detections` table it targets is created on every boot and never written — verified empty in the committed `db/detections.db`. README.md:16 advertises "Base de données SQLite des événements (détections + activations relais)". | Either wire detections into the DB (they are already RGPD-scoped by `RELAY_EVENTS_KEEP_DAYS`) or drop the table, the function, and the README claim. |
| F024 | Dead code | `src/relay_pilot.py:6-54` | Low | S | `YoctoRelay` (single-relay) is superseded by `YoctoMultiRelay` and never instantiated. | Delete. |
| F025 | Correctness | `utils/constants.py:219-222`; `src/web/routes_ui.py:62`; `templates/index.html:837-840` | Medium | S | `STATURE_COLORS` is built from `config.ini` `[STATURE_COLORS]` (12 lines of config) and imported nowhere. The template block labelled "Légende postures" is passed `OBJECT_COLORS` instead, so the UI presents `person/forklift/driver/unknown` under a "postures" heading. | Pass `STATURE_COLORS` to the template, or delete the constant, the config section, and relabel the legend. See Q4. |
| F026 | Correctness | `templates/index.html:514-527` | Medium | S | `setWhitePixelsThreshold()` posts to `/set_white_pixels_threshold/<idx>`, which is not registered by any blueprint → 404 → `r.json()` rejects → the confirmation `alert()` never runs and the threshold is never applied. The working equivalent is `POST /set_motion_param/<cid>` with `param: 'white_pixels_threshold'` (`routes_detection.py:27-32`). | Change the fetch to `/set_motion_param/` + `idx` with the correct body shape. |
| F027 | Dead code | `src/web/routes_stream.py:60-73`; `src/camera_manager.py:45`; `templates/index.html:957,961` | Medium | S | `/set_control/<cid>` looks up `state.manager.cams`, which is initialised to `{}` at `camera_manager.py:45` and never written — the GStreamer rewrite removed the OpenCV `VideoCapture` objects it expected. The route always returns 404, and the two brightness/exposure sliders in the dashboard are inert. One of them also posts to `/set_control/` with an empty cid, which cannot match the `<int:cid>` rule. | Delete the route and both sliders, or reimplement against GStreamer element properties. |
| F028 | Reliability | `Dockerfile:242-243,330-331`; both compose files | Medium | S | The healthcheck requests `/health`, which no blueprint registers. Because the probe is `requests.get(...)` with no `raise_for_status()`, a 404 still exits 0 — so the container reports *healthy* whenever the TCP port answers, regardless of application state. | Add a real `/health` route returning `{'ok': True, 'cameras': ..., 'healthy': state.application_healthy}` and change the probe to `requests.get(...).raise_for_status()`. `/failsafe_status` already contains everything needed. |
| F029 | Correctness | `src/core/state.py:49` vs `src/core/bootstrap.py:227` | Medium | S | Two sources of truth for the Telegram-alert flag: `state.telegram_alert_enabled` initialises to `False`, while `AlerteManager` is constructed with `telegram_alert_enabled=TELEGRAM_ENABLED`. `routes_ui.py:62` renders the button from the former, so with `TELEGRAM_ENABLED = true` the UI shows "🔕 Activer Telegram" while alerts are already armed. | Initialise `state.telegram_alert_enabled = TELEGRAM_ENABLED` in `bootstrap.py` and have `AlerteManager` read it from state. |
| F030 | Correctness | `src/alert_manager.py:280-297` | Medium | M | In the `time_on is None` branch, the relay is switched off but `insert_relay_event(...)` is **not** called — unlike the normal branch at `:304`. Relay activations that began without a recorded start time therefore never reach the audit DB. `duration = 0` is computed at `:282` only to be interpolated into a log line. | Call `insert_relay_event` in both branches (with a `NULL`/sentinel duration if unknown), or document why this path is exempt. |
| F031 | Correctness | `src/core/detection_pipeline.py:219` | Medium | S | The alert frame is re-fetched with `state.manager.get_frame_array(...)` rather than reusing the frame the detections were computed from. Between the inference POST (up to ~100 ms) and this call, the capture thread has replaced the buffer — so saved and Telegram-sent captures can show boxes at coordinates from a different frame. | Pass the analysed frame through the callback payload (it is already available in `InferenceServerThread.run`). |
| F032 | Performance | `src/alert_manager.py:203-206` | Medium | S | `current_frame = frame.copy()` (≈6 MB at 1080p) plus `_draw_detections` run on **every** detection callback, before the 120-second save gate at `:208` and the Telegram gate at `:221`. In steady alarm state that is ~5 wasted full-frame copies + annotation passes per second per camera. | Move the copy and draw inside the gate — compute them only when a save or send will actually happen. |
| F033 | Concurrency | `src/core/streaming.py:163`; `src/core/caches.py:61-66`; `src/web/routes_zones_api.py:100` | Medium | S | `gen_frames` indexes `caches.zone_color_cache[cid]` directly. The dict is populated only on a *zone-overlay* cache miss and is cleared wholesale by `save_zones`. A `POST /api/zones/1` landing between `streaming.py:119` and `:163` on a cam-0 generator raises `KeyError: 0`, which is not caught — the generator dies and that camera's MJPEG stream goes black until the browser reconnects. | Use `.get(cid, {}).get(zone_name, (255, 0, 0))`, and move the colour cache under `zone_overlay_lock`. |
| F034 | Correctness | `src/web/routes_system.py:204-212` | Low | S | `/clear_zone_cache` clears `zone_overlay_cache` but not `zone_color_cache`, so zone label colours stay stale after a manual cache clear (unlike `save_zones`, which clears both). | Clear both, or expose a single `caches.invalidate_zones()` helper used by all three call sites. |
| F035 | Concurrency | `src/core/failsafe.py:35-46` | Medium | S | The watchdog holds `state.heartbeat_lock` while calling `state.relays.get_relay_state(i)` and `action_on(i)` — blocking USB I/O to the Yoctopuce module, once per relay. `detection_pipeline` calls `update_heartbeat()` (same lock) on every callback, so the entire detection pipeline stalls on USB during fail-safe recovery. | Read `last_heartbeat` under the lock, release it, then do the relay I/O. |
| F036 | Concurrency | `src/core/streaming.py:47,55,180` | Low | S | `cache_performance_stats['hits'] / ['misses'] / ['total_generation_time']` are mutated without a lock from N concurrent waitress generator threads (one per open tab per camera). The `/cache_stats` numbers drift. | Move the increments inside the existing `frame_cache_lock`, or use `itertools.count`. |
| F037 | Dead code | `src/core/streaming.py:186-189` | Low | S | `cache_size`, `avg_generation_time` and `hit_rate` are computed on every cache miss and never used — leftovers from a removed log line. `avg_generation_time` also divides by `misses` with no guard. | Delete the three statements. |
| F038 | Dead code | `src/inference.py:443-457` | Low | S | `self.detections` is reset to `[]` at `:445`; the branch at `:454` tests `len(self.detections) > 0` and can therefore never be taken. The "5 ms if detection active" sleep is dead — it is always 10 ms. | Evaluate the condition before the reset, or delete the branch and keep a single sleep. |
| F039 | Dead code | `src/core/caches.py:18` | Low | S | `MAX_ZONE_COLOR_CACHE_SIZE = 20` is declared and never referenced; `zone_color_cache` is unbounded (bounded in practice by camera count). | Delete the constant, or enforce it alongside the other two caches. |
| F040 | Config | `pyproject.toml:14` | Medium | S | `nuitka>=2.7.12` is a **runtime** dependency. The build has used Cython since `f6b6b6e`; `uv sync --frozen --no-dev` installs Nuitka into the production venv of every image (confirmed: `.venv/bin/nuitka` exists). | Remove from `[project.dependencies]`. |
| F041 | Config | `pyproject.toml:11` | Medium | S | `gunicorn>=23.0.0` is likewise a runtime dependency; `run.py:29` uses waitress, and gunicorn was explicitly reverted in commit `6409dea` because forking breaks GStreamer. Shipped and unused. | Remove. |
| F042 | Config | `pyproject.toml` (no dev group) | Medium | S | There is no dependency group for tooling. `cython`, `setuptools` and `wheel` are pinned ad hoc in `Dockerfile:59`, and `bandit`/`pip-audit` are `pip install`ed in CI — so the versions the audit runs against are unpinned and drift silently. | Add `[dependency-groups] dev = ["pytest", "bandit", "pip-audit", "cython==3.2.8", "ruff"]` and use `uv sync --group dev` in CI. |
| F043 | CI | `.gitlab-ci.yml:24-33,40` | Medium | S | The `security:sast` job has `allow_failure: true` **and** every command is suffixed with `|| echo ...`. Bandit and pip-audit results can never fail or even mark the pipeline; they are only visible by downloading artifacts. `docs/security/cve-2026-47265-suivi.md` exists, so CVEs are clearly being tracked manually instead. | Drop the `|| echo` on the human-readable runs, keep `allow_failure: true` for one release, then flip it to `false`. |
| F044 | CI | `.github/workflows/build-linux-executable.yml:32-34,62,116` | Medium | S | Still builds with Nuitka and audits `requirements.txt`, deleted in commit `a1a300f`. `continue-on-error: true` plus `|| true` hides the resulting failure. Runs on every PR to `main`. | Delete the workflow (GitLab CI is the real pipeline) or rewrite it against the Cython/Docker path. |
| F045 | CI | `.gitlab-ci.yml.bak`, `.gitlab-ci-nuitka.yml` | Low | S | 6.4 KB + 163 lines of superseded pipeline definitions kept at the repo root. | Delete — git history preserves them. |
| F046 | CI | *(both pipelines)* | Medium | M | Neither `.gitlab-ci.yml` nor the GitHub workflow has a test stage. Nothing runs `test_detections_format.py`. | Add a `test` stage running `uv run pytest` before `build`, once F012 lands. |
| F047 | Config | `.dockerignore:5,26` | Low | S | References `.gitlab-ci-docker.yml` and `!CYTHON_README.md`; neither file exists (the latter became `docs/build/cython-readme.md`). | Clean up. |
| F048 | Dead code | `static/ffmpeg/bin/openh264-1.8.0-win64.dll`, `libopenh264-1.8.0-linux64.4.so` | Low | S | Vendored binaries — including a Windows DLL — for a Linux/Jetson-only product. Nothing in the codebase references ffmpeg or openh264; `.gitignore:8-10` ignores the ffmpeg executables that would have used them. | Delete both and the empty `static/ffmpeg/` tree. |
| F049 | Architectural decay | `utils/constants.py:15-16,62,100,134,139-141` | Medium | M | The module performs file I/O and four `print()` calls at import time. Any importer needs `config/*.ini` relative to the CWD (which is why `collect_dataset.main()` has to `os.chdir`). The prints run before `logs_settings()` exists, bypassing the log format entirely, and directly contradict `AGENTS.md:59` ("Préférer `logging` aux nouveaux `print()`"). | Convert prints to `logging.debug`. Longer term, wrap the loads in a `load_config()` called from `bootstrap`, keeping the module-level names as a thin compatibility layer. |
| F050 | Architectural decay | `src/collect_dataset.py:54,76` | Medium | S | `sys.path.insert(0, PROJECT_ROOT)` and `logging.basicConfig(...)` execute at import time, and `bootstrap.py:22` imports the module unconditionally — even when `DATASET_COLLECTION = false`. The `basicConfig` handler is later discarded by `logs_settings()`, which exists precisely to defend against this pattern (see its comment at `bootstrap.py:52-54`). | Move both into `main()`. |
| F051 | Architectural decay | `templates/index.html` (1 088 lines, ~506 inline script) | Medium | L | The dashboard's entire client lives in a `<script>` block inside the Jinja template: polling loops, cache stats, latency panel, gallery, all toggles. It cannot be linted, cached, or tested, and it is where F026 hides. The zone editor, by contrast, uses an external `static/js/zone_editor.js` — two conventions in the same app. | Extract to `static/js/dashboard.js`, passing the Jinja-dependent values through `data-*` attributes or a single JSON `<script type="application/json">` block. |
| F052 | Architectural decay | `static/js/zone_editor.js` (1 490 lines, 66 functions, one IIFE) | Medium | L | Zone drawing, mask drawing, and relay-icon placement share one closure and one flat namespace (`selectZone`/`selectMask`, `deleteZone`/`deleteMask`, `renumberZones`/`renumberMasks` — parallel implementations throughout). | Split into `polygon-editor.js` (shared draw/edit primitives) + `zones.js` / `masks.js` / `projectors.js`. |
| F053 | Correctness | `src/alert_manager.py:80-96` | Medium | S | `_get_relay_nums_from_zone` falls back to a hardcoded name-substring mapping (`"zone1" in zone_name → [0,1,2]`) when a zone has no `relays` field. A zone created through the editor without relays selected silently drives relays 0/1/2 or relay 1 depending on its *name*, and a name that matches neither pattern logs a warning and drives nothing. | Make `relays` mandatory in the editor (`routes_zones_api.py:74-89` already assigns names and colours automatically), and turn the fallback into a startup validation error. |
| F054 | Security | `src/web/routes_zones_api.py:74-89,126-135,168-184` | High | M | The three POST handlers accept arbitrary JSON with no schema validation. `zone['name']` flows unescaped into an INI section header via `zone_writer.py:243` (`f"[{section['header']}]\n"`) — a name containing `]\n[zone9_cam1` forges sections for another camera. Polygon points reach `int(pt[0])` with no type check, producing 500s from `ValueError`/`TypeError`. | Validate at the boundary: name against `^[a-z]+[0-9]+_cam[0-9]+$`, polygon as a list of ≥3 integer pairs within frame bounds, relays as ints < `len(state.relays.relays)`. Reject with 400 rather than 500. |
| F055 | Error handling | `src/web/routes_system.py:103`, `routes_stream.py:25`, `routes_zones_api.py:110`, `routes_ui.py:69`, `routes_system.py:218` | Medium | M | Five different error shapes across the API: `{'status':'error','message':...}` + 500, `{'error':...}` + 404, `{'images':[],'error':...}` + **200**, bare text + 404, bare text + 200. The 200-with-error case makes a failure indistinguishable from "no detections" for the dashboard gallery. | Standardise on `{'status': 'error', 'message': str}` with a correct HTTP status; add a Flask `errorhandler` for the uncaught case. |
| F056 | Observability | `src/inference.py:395` | Medium | S | `logger.info(f"Détections actuelles : {current_detections}")` serialises every detection dict — including all 17 pose keypoints when `POSE_ENABLED` — on every inference with a hit. At 5 FPS × 2 cameras this dominates log volume against a 10 MB × 5 json-file cap, evicting the diagnostic lines that matter. | Demote to DEBUG, or log a summary (`n detections, labels=[...], zones=[...]`). |
| F057 | Observability | `src/core/bootstrap.py:46`; `scripts/4isafecross.logrotate` | Medium | S | `logs_settings()` creates `logs/` but attaches only a `StreamHandler(sys.stdout)` — no `FileHandler` anywhere. The logrotate config rotates files the application no longer writes, and README.md:723 documents log rotation as a live feature. | Either add a `RotatingFileHandler` under `logs/`, or delete the `makedirs`, the logrotate unit, and the README section — Docker's json-file driver already covers retention. |
| F058 | Observability | `src/motion.py:71` | Low | S | `update_fgbg_params` logs at INFO on every call, including when nothing changed, and `/set_motion_param` is invoked on every slider interaction from the dashboard. | Log only when `updated` is true (the `:73` line already does; `:71` is the redundant one). |
| F059 | Config | `utils/constants.py:205-209` | Low | S | The fallbacks (`'/predict_frame_rf_detr/'`, `'http://127.0.0.1:8002/'`) carry slashes while the values actually in `config/config.ini:88-92` do not, and `inference.py:38` interpolates as `f"{URL}/{fonction}/"`. If the INI keys are ever absent, the URL becomes `http://127.0.0.1:8002///predict_frame_rf_detr//`. | Normalise with `urljoin`, or strip slashes in the fallbacks so they match the INI convention. |
| F060 | Correctness | `src/web/routes_stream.py:17,34` | Low | S | `/video_feed/<cid>` and `/cam_status/<cid>` index `state.cam_ids[cid]` with no bounds check → `IndexError` → 500, while `/snapshot/<cid>` (`:24`) and `/zone_editor/<cid>` (`routes_ui.py:68`) both validate. | Add the same guard for consistency. |
| F061 | Performance | `src/inference.py:339-354` | Medium | L | Each inference `np.save`s a full 1920×1080×3 BGR frame (~6.2 MB) and POSTs it as multipart at up to 5 FPS per camera — ~30 MB/s per camera over loopback, plus the parse/deserialise cost the server pays. The instrumentation added in `3067618` (`inference.py:91-113`, `get_timing_stats`) exists precisely to size this. | Decide on the data now in `/api/inference/stats`: if `transport_share_pct` is material, crop to the motion ROI before sending (already computed) or move to shared memory / ZeroMQ as the comments anticipate. Cropping is the cheaper first step. |
| F062 | Maintainability | `src/alert_manager.py:264-275` | Low | S | The 11-second minimum relay-on hold appears as a bare literal `11` in four places, with the semantics ("garantir 11s d'allumage") only in a log string. | Extract `MIN_RELAY_ON_SECONDS = 11` next to `MAX_RECORDING_QUEUE_SIZE` and reference it — this is a safety parameter, it should be findable. |

---

## Top 5 — if you fix nothing else, fix these

### 1. F001 — Get the licence key and licence file out of git

The `.gitignore` was written for a layout that commit `80fc3ec` abandoned. README.md:557 already states the rule; the repo just stopped enforcing it.

```diff
--- a/.gitignore
+++ b/.gitignore
 # Fichiers de configuration contenant des credentials sensibles
 .env
-config/4isafecross.lic
-config/license_state.json
-config/license_state.key
+licenses/*.lic
+licenses/license_state.json
+licenses/license_state.key
```

```bash
git rm --cached licenses/4isafecross.lic licenses/license_state.key
```

Then **rotate**: generate a new HMAC key and reissue the `.lic`. The removal alone does not help — the key is in every clone and in the reflog. `licenses/public_key.pem` can stay tracked (it is a public key by construction).

Same commit: delete the token comments at `src/bot_aiogram.py:67` and `utils/constants.py:5-6`, and revoke both tokens with BotFather (F002).

### 2. F006 — Persist the state the site actually depends on

Today, an operator draws zones in the web editor, they are written to `config/zones.ini` *inside the container layer*, and the next `docker compose pull && up -d` throws them away. The relay-event audit trail (`db/detections.db`) goes with them.

```diff
--- a/docker-compose-arm64.yml
+++ b/docker-compose-arm64.yml
     volumes:
-      - /data/4isafecross:/app/data
+      - /data/4isafecross/config:/app/config
+      - /data/4isafecross/db:/app/db
+      - /data/4isafecross/detections:/app/detections
+      - /data/4isafecross/dataset:/app/dataset
       - ./licenses:/app/licenses
```

Apply the same to `docker-compose-amd64.yml`. Seed `/data/4isafecross/config` from the image's `config/` on first deploy. Note that `/app/data` — the volume currently mounted — is referenced nowhere in the code, so nothing breaks by repurposing it.

Verify with: save a zone via the UI → `docker compose pull && docker compose up -d` → confirm the zone is still there.

### 3. F003 + F004 — Stop shipping unauthenticated kill switches

`/quit` reaching `os._exit(0)` on a pedestrian-safety supervisor, reachable from any host on the plant network, is the single highest-consequence line in the repo.

```diff
--- a/src/web/routes_system.py
+++ b/src/web/routes_system.py
-@system_bp.route('/shutdown')
-def shutdown():
-    state.manager.release()
-    return "Cameras released"
-
-
-@system_bp.route('/quit', methods=['POST'])
-def quit_server():
-    state.manager.release()
-    func = request.environ.get('werkzeug.server.shutdown')
-    if func is not None:
-        func()
-    else:
-        os._exit(0)
-    return 'Serveur arrêté.'
```

`restart: unless-stopped` is already set in both compose files, so `docker compose stop` is the correct way to stop the service. Remove the corresponding button from `templates/index.html`.

Then add a minimal gate for everything else, in `app_factory.create_app`:

```python
@app.before_request
def _require_token():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if not hmac.compare_digest(request.headers.get('X-API-Key', ''), API_KEY):
        return jsonify({'status': 'error', 'message': 'unauthorized'}), 401
```

with `API_KEY` from the environment. This is not a substitute for network segmentation, but it removes drive-by mutation of the zone geometry.

### 4. F009 + F015 — Make the inference boundary and the alert path fail loudly

Two changes, both small, that together stop the system from failing silently.

At `src/inference.py:366`, the list comprehension over the server's JSON should not be able to kill the thread:

```python
def _parse_detection(self, d):
    try:
        if d["class_id"] not in self.class_id:
            return None
        if float(d["confidence"]) < self.confidence_threshold:
            return None
        return { ... }                      # existing dict body
    except (KeyError, TypeError, ValueError) as exc:
        self.logger.error("Détection malformée ignorée (%s) : %r", exc, d)
        return None
```

and widen the handler at `:405` to `except (requests.RequestException, ValueError)` plus a trailing `except Exception` that logs with `exc_info=True` and `continue`s rather than falling out of `run()`.

At `src/alert_manager.py:225`, split the blanket handler so the three stages report separately — this is what would have surfaced the Telegram bug (F007) on day one:

```python
except Exception:
    self.logger.error("Échec du traitement de l'alerte caméra %s", cid, exc_info=True)
```

Then fix F007 itself: drop the `await` and dispatch the blocking send off-loop (F008):

```python
await asyncio.get_running_loop().run_in_executor(
    None, self.telegram_bot.send_detection_frame, current_frame, caption
)
```

### 5. F010 + F011 — Protect `zones.ini` from both halves of the problem

The file holds the geometry that defines where pedestrians are protected. Today it can be truncated by a power cut mid-save, and it can be overwritten by anyone following the documented pre-PR checklist.

```diff
--- a/utils/zone_writer.py
+++ b/utils/zone_writer.py
 def _write_ini_sections(ini_path, sections):
     os.makedirs(os.path.dirname(ini_path) or ".", exist_ok=True)
-
-    with open(ini_path, "w", encoding="utf-8") as f:
+    tmp_path = f"{ini_path}.tmp"
+    with open(tmp_path, "w", encoding="utf-8") as f:
         for i, section in enumerate(sections):
             if i > 0:
                 f.write("\n")
             f.write(f"[{section['header']}]\n")
             for key, value in section["entries"]:
                 f.write(f"{key} = {value}\n")
+        f.flush()
+        os.fsync(f.fileno())
+    os.replace(tmp_path, ini_path)
```

And for F011 — rename `test_zone_editor.py` to `tools/zone_editor_sandbox.py`, point its `ZONES_INI_PATH` at a scratch copy, and remove it from `AGENTS.md:34,71`. The file name is what makes it dangerous: it reads as a test, is listed as a test, and writes to production config.

---

## Quick wins

Low effort, Medium severity or above. Roughly ordered by value per minute.

- [x] **F001** — `git rm --cached` the two licence artefacts, fix `.gitignore`, rotate the HMAC key.
- [x] **F002** — Revoke both Telegram tokens; delete the comments at `bot_aiogram.py:67` and `constants.py:5-6`.
- [x] **F003** — Delete `/shutdown` and `/quit` and the dashboard button that calls them.
- [x] **F005** — Redact the RTSP userinfo before logging (`camera_manager.py:191`, `bootstrap.py:157,159`).
- [x] **F007** — Remove the bad `await` at `alert_manager.py:223`; Telegram alerts start working.
- [x] **F010** — Atomic write in `zone_writer._write_ini_sections`.
- [x] **F011** — Rename `test_zone_editor.py` and repoint its `ZONES_INI_PATH`.
- [x] **F015** — Add `exc_info=True` to the alert-path handler at `alert_manager.py:225`.
- [x] **F016** — Replace `except Exception: pass` with a WARNING at `constants.py:43,95`; log zone counts at boot.
- [x] **F026** — Point the threshold slider at `/set_motion_param/` (`index.html:516`).
- [x] **F028** — Add a real `/health` route and `raise_for_status()` in both healthchecks.
- [x] **F029** — Initialise `state.telegram_alert_enabled` from `TELEGRAM_ENABLED` in `bootstrap.py`.
- [x] **F033** — `caches.zone_color_cache.get(cid, {})` at `streaming.py:163`.
- [x] **F040 / F041** — Drop `nuitka` and `gunicorn` from `[project.dependencies]`.
- [x] **F043** — Remove the `|| echo` suffixes from the human-readable bandit/pip-audit runs.
- [x] **F044 / F045** — Delete the stale Nuitka workflow and the two dead CI files.
- [x] **F020 / F021 / F022 / F023 / F024** — Delete ~1 900 lines of dead code in one commit.
- [x] **F056** — Demote the per-detection dict dump to DEBUG (`inference.py:395`).

---

## Things that look bad but are actually fine

Calls I considered flagging and decided against, with reasoning.

- **The module-level `state` singleton (`src/core/state.py`).** A global mutable object shared across a dozen threads is normally the first thing to flag. It is correct here and the file says why at lines 1-11: detection callbacks, the watchdog and the dataset threads all run outside Flask's request context, so `current_app` is unavailable, and waitress is single-process without fork (`run.py:12-16` records the gunicorn crash that established this). Related: `create_app(state)` accepts `state` and never uses it (`app_factory.py:15-21`) — that reads as a bug, but the docstring says it exists to make the boot dependency explicit. Leave both.

- **The sleep ladder in `InferenceServerThread.run` (`inference.py:288,314,330,455-457`).** Five different hardcoded sleeps and an adaptive backoff look like accreted hackery. They are a deliberate CPU/latency tradeoff on a thermally-constrained Jetson, and the class carries the instrumentation to justify them (`get_optimization_stats`, exposed at `/api/inference/stats`). Tuning them without that telemetry in hand would be guesswork.

- **`Gst.init([])` plus a `fakesrc ! fakesink` warmup pipeline (`camera_manager.py:66-71`).** Textbook cargo cult. Commit `2532ade` shows it fixes a real crash: the GStreamer plugin registry scan must happen on the main thread before any secondary thread touches it. The comment at `:62-64` also documents why `[]` and not `None`. Keep.

- **`protocols=tcp` hardcoded on `rtspsrc` (`camera_manager.py:136`).** Forcing TCP costs latency versus UDP and looks like an unexamined default. Commit `2bbe224` and the comment at `:123-127` document a GPF in rtspsrc's GLib UDP thread pool on kernel ≥ 6.17 + glibc 2.35. Do not "optimise" this back to UDP.

- **`boundscheck` / `wraparound` left at their default `True` in `setup_cython.py:94-99`.** Every Cython guide says to disable them. The comment records the specific SIGSEGV that resulted (commit `affebdd`): these directives compile negative indices into unchecked memory access, and this codebase uses `list[-1]`. The performance argument does not even apply — there are no typed C arrays here.

- **`send_from_directory(DETECTIONS_DIR, filename)` (`routes_system.py:107-109`).** Looks like textbook path traversal on an unauthenticated route. Flask's `send_from_directory` routes through `werkzeug.security.safe_join`, which rejects `..` and absolute paths. It is safe as written. (The *authentication* gap is real and covered by F004; the traversal is not.)

- **`db/detections.db` committed to git.** A binary database in version control is a smell, but this one is a 48 KB schema-only file with zero rows in both tables (verified). `init_db()` uses `CREATE TABLE IF NOT EXISTS`, so it is redundant rather than harmful. Not worth a change on its own — it becomes relevant only alongside F006.

- **Broad `except Exception` in `gpu_metrics.get_gpu_metrics` (`:168`) and `system_metrics.get_resource_metrics`.** Blanket handlers usually hide bugs. These are best-effort telemetry behind a debug route on hardware where the sysfs paths genuinely vary by JetPack version, and both modules say so in their docstrings ("Ne lève jamais"). A failed GPU probe must not 500 the debug panel. Correct as written — unlike the handler at `alert_manager.py:225` (F015), which wraps the *alerting* path.

- **`frame_interval = 0.2` in `gen_frames` and `min_inference_interval = 0.2` in `InferenceServerThread`.** The same magic number in two places reads like a copy-paste that should be a shared constant. They are independent budgets — display refresh versus AI rate limit — that happen to coincide today. Coupling them would be wrong.

- **`AlerteManager` keeping `relay_on` state in Python rather than reading the hardware.** Caching device state is usually a bug waiting to happen. Here the watchdog (`failsafe.py:43-46`) independently reconciles against `get_relay_state(i)` every 5 seconds, so drift self-corrects, and avoiding a USB round-trip per detection matters at 5 FPS.

---

## Open questions for the maintainer

1. **`np.frombuffer(mapinfo.data)` followed by `buf.unmap(mapinfo)` (`camera_manager.py:231-239`).** Is `mapinfo.data` a `bytes` copy on the PyGObject/GStreamer versions you actually ship, or a live view over the mapped buffer? If it is a view, every consumer (`get_frame_array` returns it uncopied) reads memory that has been unmapped — which would be a strong candidate root cause for the GPF class of crashes commits `ec070e0` through `2bbe224` were chasing. If it is a copy, that is ~6 MB memcpy per frame per camera and worth knowing for F061. I could not settle this statically and did not want to assert either way.

2. **`set_zones` switching every relay OFF during reconfiguration (`alert_manager.py:342-345`).** Deliberate — on the assumption an operator is physically present at the console while editing zones — or an unnoticed disarm window? It is the one place where the fail-safe invariant inverts, so I flagged it as F014, but the answer changes the fix.

3. **`privileged: true` in `docker-compose-arm64.yml:7`.** The Jetson device nodes are already enumerated individually at `:30-37` and the nvidia runtime is declared at `:6`. Is `privileged` still needed, or is it a leftover from before the device list was written out?

4. **`[STATURE_COLORS]` in `config.ini:111-126` and `POSE_ENABLED = false` (`config.ini:76`).** Has posture classification been abandoned? `pose_analyser.py` (500 lines) and `PoseAnalyzer.analyze_stature` are still wired into `inference.py:390`, but with pose disabled in config the `stature` field is always `"inconnu"`. If posture is dead, that is another ~500 lines to remove; if it is dormant, F025 should restore the legend rather than delete it.

5. **Class-ID mapping across modes.** `DETECTION = transfert` selects `TRANSFERT_CLASSES = [0..5]` (`config.ini:81`), while `collect_dataset.TRANSFERT_TO_DATASET` (`:63`) maps only ids 1, 2, 3. Is `SIMPLE_CLASSES = [1, 2]` still meaningful for any deployed model, or is `transfert` now the only live mode? The `switch_inference_mode` route and the RF-DETR path (`URL_RFDETR`) may be in the same situation.

6. **`config/config.ini` is tracked with two lab IPs at `:105`.** Is the tracked copy expected to be the production one (in which case F006's bind-mount changes the deployment story), or is it a template each site overrides? The credential fields are correctly empty, so this looks like a template — but nothing documents the override mechanism, and today there is no mount point for one.

7. **Three overlapping sets of agent instructions**: `AGENTS.md`, `.github/instructions/*.instructions.md` (frontend / python-backend / ops-config), and `.github/skills/api-smoke-check/SKILL.md`. Which is canonical? `AGENTS.md:34,71` currently points contributors at the destructive `test_zone_editor.py` (F011), so at least one of them is actively misleading.

8. **JetPack version.** README.md:94,314 documents flashing JetPack 6.2 (L4T 36.4.3); `Dockerfile:82,249` builds against JetPack 7.2 / L4T r39.2.0 and pulls the `r39.2` apt repos. Which is deployed on the reServer J4012 today? If the answer is 7.2, the flash procedure doc is now wrong for anyone provisioning a new unit.

9. **Licence file location in the docs.** `bootstrap.py:108` defaults to `licenses/4isafecross.lic`; README.md:512,515,518,552 instructs deploying to `config/4isafecross.lic` and setting `SAFECROSS_LICENSE=config/...`. Following the README puts the licence where the app will not find it. Which path is intended going forward?
