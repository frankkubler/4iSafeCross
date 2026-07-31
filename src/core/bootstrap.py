"""Séquence de démarrage de l'application.

create_application() reproduit l'ordre de boot historique d'app.py :
logging → boucle asyncio → licence → relais ON (fail-safe) → bot Telegram →
zones/masques → alert manager → watchdog → cache → attente RTSP → caméras →
threads d'inférence → dataset → extinction différée → app Flask.

L'ordre est un contrat d'exploitation (voir docs/features/failsafe-mode.md) :
ne pas le modifier sans revalider le comportement fail-safe sur cible.
"""
import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path

from src.alert_manager import AlerteManager
from src.bot_aiogram import BotThread
from src.camera_manager import CameraManager, redact_rtsp_url
from src.collect_dataset import DatasetCollectionThread
from src.core import caches, failsafe
from src.core.detection_pipeline import detection_callback_factory, get_frame_func_factory
from src.core.state import state
from src.inference import InferenceServerThread
from src.relay_pilot import YoctoMultiRelay
from src.web.app_factory import create_app
from utils.constants import (MOTIONTHRESHOLD, RTSP_LOGIN,
                             RTSP_PASSWORD, RTSP_HOST, RTSP_PORT, RTSP_STREAM, LOG_LEVEL,
                             ZONES_BY_CAMERA, WAIT_BEFORE_TEST_RTSP,
                             DATASET_COLLECTION, DATASET_COLLECTION_INTERVAL,
                             DATASET_COLLECTION_START_HOUR, DATASET_COLLECTION_END_HOUR,
                             DATASET_COLLECTION_MAX_PER_CLASS, DATASET_OUTPUT_DIR, DATASET_FILES_KEEP_DAYS,
                             DATASET_BG_INTERVAL, DATASET_BG_ENABLED,
                             DATASET_HARD_NEG_CONFIDENCE, DATASET_HARD_NEG_ENABLED,
                             URL_YOLO, FONCTION_YOLO,
                             MASKS_BY_CAMERA,
                             RELAY_POSITIONS_BY_CAMERA,
                             TELEGRAM_ENABLED)

logger = logging.getLogger(__name__)


def logs_settings():
    os.makedirs('logs', exist_ok=True)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(
        'Line: %(lineno)d - %(message)s - %(levelname)s - %(name)s - %(asctime)s'
    ))

    # basicConfig() est un no-op si des handlers existent déjà sur le root logger
    # (ajoutés par flask/werkzeug/waitress lors des imports).
    # On configure directement le root logger pour garantir stdout.
    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)
    root.handlers.clear()
    root.addHandler(console_handler)

    # werkzeug est déjà importé via Flask — on vide son handler stderr éventuel
    logging.getLogger('werkzeug').handlers.clear()
    # Note : waitress n'est pas encore importé ici, son handler est nettoyé juste avant serve()


def _log_license_boot_failure(err: Exception) -> None:
    """Journalise une erreur de licence avec un diagnostic orienté exploitation."""
    err_msg = str(err)
    err_msg_low = err_msg.lower()

    if "rollback d'horloge" in err_msg_low:
        logger.critical("   Cause : rollback d'horloge détecté sur la machine")
        logger.critical("   Action : corriger l'horloge système puis redémarrer l'application")
        return

    if "hmac invalide" in err_msg_low:
        logger.critical("   Cause : intégrité du state licence compromise (HMAC invalide)")
        logger.critical("   Action : vérifier les fichiers licenses/license_state.*")
        return

    if "state de licence" in err_msg_low:
        logger.critical("   Cause : state local de licence absent/invalide/incompatible")
        logger.critical("   Action : vérifier les fichiers licenses/license_state.*")
        return

    if "signature de licence invalide" in err_msg_low:
        logger.critical("   Cause : signature RSA invalide")
        logger.critical("   Action : vérifier licenses/public_key.pem et le fichier .lic")
        return

    if "expirée" in err_msg_low:
        logger.critical("   Cause : licence expirée")
        logger.critical("   Action : générer et déployer une nouvelle licence")
        return

    if "destinée à la machine" in err_msg_low:
        logger.critical("   Cause : machine_id non correspondant")
        logger.critical("   Action : régénérer la licence avec le machine-id de la cible")
        return

    logger.critical("   Cause : échec de validation de licence non catégorisé")


def _verify_license():
    # Import ici : après la configuration du logging, comme historiquement,
    # et pour que les modules sans licence (tests) restent importables.
    from license_validator import load_and_verify_license, get_machine_id

    lic_path = os.environ.get("SAFECROSS_LICENSE", "licenses/4isafecross.lic")
    logger.info(f"Vérification de la licence dans : {lic_path}")

    try:
        lic_payload = load_and_verify_license(
            lic_path,
            required_features=["full"],  # adapter selon les fonctionnalités requises
        )
        logger.info("Licence acceptée pour : %s", lic_payload.get("client"))
    except (FileNotFoundError, ValueError) as lic_err:
        logger.critical("❌ Licence invalide : %s", lic_err)
        _log_license_boot_failure(lic_err)
        logger.critical("   Machine ID de cette machine : %s", get_machine_id())
        logger.critical("   Placez un fichier de licence valide dans : %s", lic_path)
        sys.exit(1)


def _start_main_loop():
    loop = asyncio.new_event_loop()

    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    threading.Thread(target=run_loop, daemon=True).start()
    return loop


def _log_zone_inventory():
    """Journalise ce qui a réellement été chargé depuis config/*.ini.

    Les chargeurs de utils.constants tournent à l'import, avant logs_settings() :
    ce récapitulatif est le premier endroit où l'exploitant peut constater qu'une
    caméra se retrouve sans zone de surveillance (section mal nommée, fichier
    tronqué). Une caméra sans zone ne déclenche aucune alerte.
    """
    if not ZONES_BY_CAMERA:
        logger.error(
            "Aucune zone de surveillance chargée depuis config/zones.ini — "
            "aucune détection ne déclenchera d'alerte."
        )
    for cam_id in sorted(ZONES_BY_CAMERA):
        zone_names = [z['name'] for z in ZONES_BY_CAMERA[cam_id]]
        logger.info(
            "Caméra %d : %d zone(s) chargée(s) — %s",
            cam_id, len(zone_names), ', '.join(zone_names)
        )
    for cam_id in sorted(MASKS_BY_CAMERA):
        logger.info("Caméra %d : %d masque(s) chargé(s)", cam_id, len(MASKS_BY_CAMERA[cam_id]))


def _wait_for_rtsp_streams():
    """Attente active jusqu'à ce qu'au moins une caméra réponde au ping RTSP."""
    cam_ids = []
    for host in RTSP_HOST:
        cam_ids.append(f"rtsp://{RTSP_LOGIN}:{RTSP_PASSWORD}@{host}:{RTSP_PORT}/{RTSP_STREAM}")

    if not cam_ids:
        logger.error("Aucun flux RTSP configuré. Vérifiez la section RTSP du fichier config.ini")
        raise RuntimeError("No RTSP streams configured")

    available_cam_ids = []
    attempt = 0
    retry_delay = max(1, WAIT_BEFORE_TEST_RTSP)
    while not available_cam_ids:
        attempt += 1
        results = CameraManager.test_rtsp_streams_parallel(cam_ids)
        available_cam_ids = [cid for cid, ok in results.items() if ok]

        # Logger l'état de chaque caméra pour cette tentative
        for cid in cam_ids:
            if results.get(cid, False):
                logger.info(f"Ping RTSP OK pour {redact_rtsp_url(cid)} (tentative {attempt})")
            else:
                logger.warning(f"Ping RTSP échoué pour {redact_rtsp_url(cid)} (tentative {attempt})")

        if available_cam_ids:
            if WAIT_BEFORE_TEST_RTSP > 0:
                logger.info(
                    f"Au moins une caméra répond au ping RTSP ({redact_rtsp_url(available_cam_ids[0])}). Attente de {WAIT_BEFORE_TEST_RTSP}s avant démarrage des flux RTSP..."
                )
                time.sleep(WAIT_BEFORE_TEST_RTSP)
            break

        logger.warning(
            f"Aucune caméra ne répond au ping RTSP (tentative {attempt}). Nouvelle tentative dans {retry_delay}s..."
        )
        time.sleep(retry_delay)

    return available_cam_ids


def _purge_dataset_files():
    # Purge inconditionnelle des images dataset (RGPD — Art. 5-1-e) — quelle que soit la valeur de DATASET_COLLECTION
    dataset_path = Path(DATASET_OUTPUT_DIR)
    cutoff = time.time() - DATASET_FILES_KEEP_DAYS * 86400
    purged = 0
    for subdir, ext in (("images/raw", ".jpg"), ("labels/raw", ".txt")):
        target = dataset_path / subdir
        if target.exists():
            for f in target.iterdir():
                if f.suffix == ext and f.stat().st_mtime < cutoff:
                    try:
                        f.unlink()
                        purged += 1
                    except OSError:
                        pass
    if purged:
        logger.info(f"🗑️ Purge dataset : {purged} fichier(s) supprimé(s) (>{DATASET_FILES_KEEP_DAYS}j)")


def create_application():
    """Boote tout le système et retourne (app Flask, state)."""
    state.main_loop = _start_main_loop()

    logs_settings()

    # ── Vérification de la licence ────────────────────────────────────────────
    _verify_license()

    state.relays = YoctoMultiRelay()
    for i in range(len(state.relays.relays)):
        logger.debug(f"Relais {i} : {state.relays.get_relay_state(i)}")
        state.relays.action_on(i)  # MODE FAIL-SAFE : Alertes ON par défaut au démarrage
        logger.debug(f"Relais {i} : {state.relays.get_relay_state(i)}")
    logger.warning(f"⚠️  MODE FAIL-SAFE ACTIVÉ : {len(state.relays.relays)} relais allumés par défaut")

    # Lancer le bot Telegram au démarrage de l'app
    if TELEGRAM_ENABLED:
        state.telegram_bot = BotThread(overwrite_file=False, state=state)
        threading.Thread(target=state.telegram_bot.run, daemon=True).start()
    else:
        state.telegram_bot = None

    # Zones, masques et positions de projecteurs par caméra (config/*.ini)
    state.zones_by_camera = ZONES_BY_CAMERA
    state.masks_by_camera = MASKS_BY_CAMERA
    state.relay_positions_by_camera = RELAY_POSITIONS_BY_CAMERA
    _log_zone_inventory()

    # Source unique de vérité pour l'état des alertes Telegram : le state, dont
    # le tableau de bord dérive le libellé du bouton. AlerteManager en reçoit une
    # copie ici, et /toggle_telegram_alert réaligne les deux à chaque bascule.
    state.telegram_alert_enabled = TELEGRAM_ENABLED

    # Passer toutes les zones (toutes caméras) à l'alert_manager
    state.alert_manager = AlerteManager(state.relays, telegram_bot=state.telegram_bot,
                                        zones_by_camera=state.zones_by_camera,
                                        telegram_alert_enabled=state.telegram_alert_enabled)

    # ===== SYSTÈME DE HEARTBEAT FAIL-SAFE =====
    failsafe.start_failsafe_watchdog()

    caches.start_cache_cleanup()
    logger.info(f"✅ Cache de frames initialisé - Durée: {caches.FRAME_CACHE_DURATION*1000:.0f}ms, Qualité JPEG: {caches.FRAME_QUALITY_OPTIMIZED}%")

    # Vérification des flux RTSP avant d'instancier CameraManager
    state.cam_ids = _wait_for_rtsp_streams()
    logger.info(f"Caméras RTSP disponibles : {[redact_rtsp_url(c) for c in state.cam_ids]}")
    state.manager = CameraManager(state.cam_ids, frame_width=1920, frame_height=1080)

    for i in range(len(state.cam_ids)):
        state.stream_enabled[i] = False  # vidéo masquée par défaut
        state.detection_enabled[i] = True  # détection active par défaut
        state.roi_display_enabled[i] = False  # affichage ROI désactivé par défaut
        state.mask_overlay_enabled[i] = False  # overlay masque désactivé par défaut
        state.stream_display_width[i] = 854  # 480p par défaut (854x480)
        # Démarrage automatique de la détection
        stop_event = threading.Event()
        state.inference_stop_events[i] = stop_event
        thread = InferenceServerThread(
            home_dir=".",
            white_pixels_threshold=MOTIONTHRESHOLD,
            get_frame_func=get_frame_func_factory(i),
            detection_callback=detection_callback_factory(i, state.main_loop),
            stop_event=stop_event,
            masks=state.masks_by_camera.get(i, []),
            cam_id=i,
        )
        thread.start()
        state.inference_threads[i] = thread

    _purge_dataset_files()

    if DATASET_COLLECTION:
        logger.info(
            f"📸 Collecte dataset activée : intervalle={DATASET_COLLECTION_INTERVAL}min "
            f"plage={DATASET_COLLECTION_START_HOUR:02d}h–{DATASET_COLLECTION_END_HOUR:02d}h "
            f"→ {DATASET_OUTPUT_DIR}/"
        )
        for i in range(len(state.cam_ids)):
            ds_thread = DatasetCollectionThread(
                cam_idx=i,
                get_frame_func=get_frame_func_factory(i),
                shared_detections=state.shared_detections,
                shared_detections_lock=state.shared_detections_lock,
                shared_motion_roi=state.shared_motion_roi,
                shared_motion_roi_lock=state.shared_motion_roi_lock,
                output_dir=DATASET_OUTPUT_DIR,
                interval_minutes=DATASET_COLLECTION_INTERVAL,
                start_hour=DATASET_COLLECTION_START_HOUR,
                end_hour=DATASET_COLLECTION_END_HOUR,
                max_per_class_per_hour=DATASET_COLLECTION_MAX_PER_CLASS,
                background_interval_minutes=DATASET_BG_INTERVAL,
                bg_enabled=DATASET_BG_ENABLED,
                hard_neg_confidence=DATASET_HARD_NEG_CONFIDENCE,
                hard_neg_enabled=DATASET_HARD_NEG_ENABLED,
                inf_url=f"{URL_YOLO}{FONCTION_YOLO}",
                stop_event=state.inference_stop_events[i],
                masks=state.masks_by_camera.get(i, []),
            )
            ds_thread.start()
            state.dataset_threads[i] = ds_thread
    else:
        logger.info("📸 Collecte dataset désactivée (DATASET_COLLECTION = false dans config.ini)")

    failsafe.start_startup_relay_off()

    app = create_app(state)
    return app, state
