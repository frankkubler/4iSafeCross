from flask import Flask, render_template, Response, request, jsonify, send_from_directory
from src.camera_manager import CameraManager
from src.inference import InferenceServerThread
from src.alert_manager import AlerteManager
from utils.utils import get_non_local_ips, get_docker_info, get_service_status
from utils.zone_writer import save_zones_to_ini
from src.relay_pilot import YoctoMultiRelay
from src.bot_aiogram import BotThread
import threading
import cv2
import logging
import logging.handlers
import sys
import os
from datetime import datetime
import time
from utils.constants import (MOTIONTHRESHOLD, APP_NAME, APP_VERSION, RTSP_LOGIN, OBJECT_COLORS,
                             RTSP_PASSWORD, RTSP_HOST, RTSP_PORT, RTSP_STREAM, LOG_LEVEL, ZONES_BY_CAMERA, WAIT_BEFORE_TEST_RTSP, STATURE_COLORS, OBJECT_COLORS,
                             load_zones_by_camera_from_ini, NUM_RELAYS)
from utils.coco_classes import COCO_CLASSES
import psutil
import glob
import asyncio
import copy
import numpy as np

# Initialisation du MAIN_LOOP global pour l'application
MAIN_LOOP = asyncio.new_event_loop()


def start_main_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


threading.Thread(target=start_main_loop, args=(MAIN_LOOP,), daemon=True).start()


def logs_settings():
    # try:
    #     os.mkdir('logs')
    # except FileExistsError:
    #     pass
    # log_dir = 'logs/'
    # clean_files(log_dir, max_files=5)

    # # Utilisation d'un RotatingFileHandler pour limiter la taille à 5 Mo
    # log_file_path = os.path.join(log_dir, 'app.log')
    # file_handler = logging.handlers.RotatingFileHandler(
    #     log_file_path, maxBytes=5 * 1024 * 1024, backupCount=5
    # )
    os.makedirs('logs', exist_ok=True)
    console_handler = logging.StreamHandler(sys.stdout)
    logging.basicConfig(level=LOG_LEVEL,
                        format='Line: %(lineno)d - %(message)s - %(levelname)s - %(name)s - %(asctime)s',
                        handlers=[console_handler])
    # Function to log uncaught exceptions

    # def log_uncaught_exceptions(exctype, value, tb):
    #     logging.error("Uncaught exception", exc_info=(exctype, value, tb))
    #     file_handler.flush()
    # # Set the exception hook
    # sys.excepthook = log_uncaught_exceptions
    # # Flush and close the log file
    # file_handler.flush()
    # file_handler.close()


logs_settings()
logger = logging.getLogger(__name__)
relays = YoctoMultiRelay()
for i in range(len(relays.relays)):
    logger.debug(f"Relais {i} : {relays.get_relay_state(i)}")
    relays.action_on(i)  # MODE FAIL-SAFE : Alertes ON par défaut au démarrage
    logger.debug(f"Relais {i} : {relays.get_relay_state(i)}")
logger.warning(f"⚠️  MODE FAIL-SAFE ACTIVÉ : {len(relays.relays)} relais allumés par défaut")
# logger.info(f"Relais initialisé : {relays.is_initialized}, état actuel : {relays.states}")
# Lancer le bot Telegram au démarrage de l'app
telegram_bot = BotThread(overwrite_file=False)
threading.Thread(target=telegram_bot.run, daemon=True).start()

# Définir les zones pour chaque caméra
zones_by_camera = ZONES_BY_CAMERA

# Passer toutes les zones (toutes caméras) à l'alert_manager
alert_manager = AlerteManager(relays, telegram_bot=telegram_bot, zones_by_camera=zones_by_camera, telegram_alert_enabled=False)

# ===== SYSTÈME DE HEARTBEAT FAIL-SAFE =====
# Variables globales pour le heartbeat
heartbeat_lock = threading.Lock()
last_heartbeat = time.time()
HEARTBEAT_TIMEOUT = 30  # Si pas de heartbeat pendant 30s, considérer comme dysfonctionnel
application_healthy = True

def update_heartbeat():
    """Appelé régulièrement pour indiquer que l'application fonctionne correctement."""
    global last_heartbeat, application_healthy
    with heartbeat_lock:
        last_heartbeat = time.time()
        application_healthy = True

def failsafe_watchdog():
    """Thread surveillant la santé de l'application via heartbeat.
    Si aucun heartbeat reçu pendant HEARTBEAT_TIMEOUT secondes, active le mode fail-safe."""
    global application_healthy
    logger.info("🔒 Watchdog fail-safe démarré - Surveillance active")
    
    while True:
        time.sleep(5)  # Vérification toutes les 5 secondes
        
        with heartbeat_lock:
            time_since_heartbeat = time.time() - last_heartbeat
            
            if time_since_heartbeat > HEARTBEAT_TIMEOUT:
                if application_healthy:
                    application_healthy = False
                    logger.error(f"⚠️  ALERTE FAIL-SAFE : Aucun heartbeat depuis {time_since_heartbeat:.1f}s - Maintien des relais ON")
                    # S'assurer que tous les relais sont ON
                    for i in range(len(relays.relays)):
                        if not relays.get_relay_state(i):
                            logger.warning(f"🔧 Réactivation du relais {i} en mode fail-safe")
                            relays.action_on(i)
            else:
                if not application_healthy:
                    application_healthy = True
                    logger.info(f"✅ Application de nouveau opérationnelle (heartbeat reçu)")

# Démarrer le watchdog fail-safe
failsafe_thread = threading.Thread(target=failsafe_watchdog, daemon=True)
failsafe_thread.start()

# Cache pour les couleurs des zones par caméra pour optimisation
zone_color_cache = {}
MAX_ZONE_COLOR_CACHE_SIZE = 20  # Limite pour éviter les fuites mémoire

# Cache pour les overlays des zones par caméra
zone_overlay_cache = {}
zone_overlay_lock = threading.Lock()
MAX_ZONE_OVERLAY_CACHE_SIZE = 10  # Limite pour éviter les fuites mémoire (~6 Mo par entrée)

# Cache pour les frames générées (optimisation 10 FPS)
frame_cache = {}
frame_cache_lock = threading.Lock()
frame_cache_timestamp = {}
FRAME_CACHE_DURATION = 0.15  # Cache de 150ms - plus stable pour éviter alternance
FRAME_QUALITY_OPTIMIZED = 70  # Qualité JPEG optimisée

# Statistiques du cache
cache_performance_stats = {
    'hits': 0,
    'misses': 0,
    'total_generation_time': 0.0,
    'last_reset': time.time()
}

def cleanup_frame_cache():
    """Nettoie le cache des frames expirées"""
    current_time = time.time()
    with frame_cache_lock:
        expired_cameras = []
        for cam_id, timestamp in frame_cache_timestamp.items():
            # Nettoyage plus conservateur : expire après 3x la durée du cache (450ms)
            if current_time - timestamp > FRAME_CACHE_DURATION * 3:
                expired_cameras.append(cam_id)
        
        if expired_cameras:
            logger.debug(f"🧹 Nettoyage cache: suppression de {len(expired_cameras)} entrées expirées (caméras: {expired_cameras})")
        
        for cam_id in expired_cameras:
            frame_cache.pop(cam_id, None)
            frame_cache_timestamp.pop(cam_id, None)

# Lancer le nettoyage du cache périodiquement
def start_cache_cleanup():
    def cleanup_loop():
        logger.debug("🚀 Démarrage du thread de nettoyage du cache de frames")
        last_stats_log = time.time()
        while True:
            cleanup_frame_cache()
            
            # Log des statistiques toutes les 30 secondes
            current_time = time.time()
            if current_time - last_stats_log > 30:
                total_requests = cache_performance_stats['hits'] + cache_performance_stats['misses']
                if total_requests > 0:
                    hit_rate = cache_performance_stats['hits'] / total_requests * 100
                    avg_gen_time = cache_performance_stats['total_generation_time'] / max(cache_performance_stats['misses'], 1)
                    time_saved = cache_performance_stats['hits'] * avg_gen_time
                    logger.debug(f"📊 Stats cache (30s): {total_requests} requêtes, {hit_rate:.1f}% HIT, temps économisé: {time_saved:.0f}ms")
                last_stats_log = current_time
            
            time.sleep(3)  # Nettoyer toutes les 3 secondes au lieu de chaque seconde
    
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()

start_cache_cleanup()
logger.info(f"✅ Cache de frames initialisé - Durée: {FRAME_CACHE_DURATION*1000:.0f}ms, Qualité JPEG: {FRAME_QUALITY_OPTIMIZED}%")


def create_zone_overlay(frame_shape, zones, cid):
    """Crée un overlay transparent avec les zones dessinées une seule fois"""
    h, w = frame_shape[:2]
    overlay = np.zeros((h, w, 3), dtype=np.uint8)
    
    # Initialiser le cache des couleurs de zones pour cette caméra si nécessaire
    if cid not in zone_color_cache:
        zone_color_cache[cid] = {
            zone["name"]: (c[2], c[1], c[0])  # RGB → BGR pour OpenCV
            for zone in zones
            for c in [zone.get("color", (255, 0, 0))]
        }

    for i, zone in enumerate(zones):
        color_rgb = zone.get("color", (0, 255, 0))
        color = (color_rgb[2], color_rgb[1], color_rgb[0])  # RGB → BGR pour OpenCV
        if "polygon" in zone:
            # On s'assure que les points sont dans l'image
            pts = [
                (max(0, min(w - 1, int(xy[0]))), max(0, min(h - 1, int(xy[1]))))
                for xy in zone["polygon"]
            ]
            pts_np = np.array([pts], dtype=np.int32)
            cv2.polylines(overlay, pts_np, isClosed=True, color=color, thickness=4)
            # Afficher le nom de la zone au premier point
            cv2.putText(overlay, zone["name"], (pts[0][0], pts[0][1] + 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 3)
        elif "rect" in zone:
            x1, y1, x2, y2 = zone["rect"]
            # S'assurer que la zone ne dépasse pas l'image
            x1 = max(0, min(w - 1, x1))
            y1 = max(0, min(h - 1, y1))
            x2 = max(0, min(w - 1, x2))
            y2 = max(0, min(h - 1, y2))
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 4)
            cv2.putText(overlay, zone["name"], (x1, y1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 3)
    
    return overlay


def get_zone_overlay(frame_shape, cid):
    """Récupère l'overlay des zones depuis le cache ou le crée si nécessaire"""
    with zone_overlay_lock:
        cache_key = f"{cid}_{frame_shape[0]}_{frame_shape[1]}"
        
        # Limiter la taille du cache pour éviter les fuites mémoire
        if cache_key not in zone_overlay_cache:
            if len(zone_overlay_cache) >= MAX_ZONE_OVERLAY_CACHE_SIZE:
                # Supprimer la plus ancienne entrée
                oldest_key = next(iter(zone_overlay_cache))
                del zone_overlay_cache[oldest_key]
                logger.debug(f"🗑️ Cache overlay plein, suppression de {oldest_key}")
            
            zones = zones_by_camera.get(cid, [])
            zone_overlay_cache[cache_key] = create_zone_overlay(frame_shape, zones, cid)
            logger.debug(f"🎨 Overlay des zones créé pour caméra {cid} (résolution: {frame_shape[1]}x{frame_shape[0]})")
        
        return zone_overlay_cache[cache_key]


def get_zone_for_detection(det, zones):
    # det est maintenant un dictionnaire : {"x_min": ..., "y_min": ..., etc.}
    # On prend le centre du rectangle de détection
    x_centre = int((det["x_min"] + det["x_max"]) / 2)
    y_centre = int((det["y_min"] + det["y_max"]) / 2)
    matched_zones = []
    for zone in zones:
        if "polygon" in zone:
            pts = np.array(zone["polygon"], dtype=np.int32)
            # cv2.pointPolygonTest attend un tableau Nx2
            inside = cv2.pointPolygonTest(pts, (x_centre, y_centre), False)
            if inside >= 0:
                matched_zones.append(zone["name"])
        elif "rect" in zone:
            x1, y1, x2, y2 = zone["rect"]
            if x1 <= x_centre <= x2 and y1 <= y_centre <= y2:
                matched_zones.append(zone["name"])
    return matched_zones


def detection_callback_factory(cid, main_loop=None):
    # previous_detection devient un dict par zone
    previous_detection = {}

    def detection_callback(detection_result):
        nonlocal previous_detection
        # Extraire les valeurs du dictionnaire
        if isinstance(detection_result, dict):
            detections = detection_result.get("detections", [])
            roi = detection_result.get("roi", None)
            x_pad = detection_result.get("x_pad", None)
            y_pad = detection_result.get("y_pad", None)
        else:
            detections = detection_result
            roi = None
            x_pad = None
            y_pad = None
        # Stocker les détections dans la structure partagée
        with shared_detections_lock:
            # Ajoute la zone à la fin de chaque détection
            zones = zones_by_camera.get(cid, [])
            zone_names_list = [zone["name"] for zone in zones]
            detections_with_zone = []
            # Initialiser previous_detection pour chaque zone si besoin
            for zone_name in zone_names_list:
                if zone_name not in previous_detection:
                    previous_detection[zone_name] = False
            # Marquer les zones détectées dans cette frame
            zones_detected = set()
            for det in detections:
                zone_names = get_zone_for_detection(det, zones)
                for zn in zone_names:
                    zones_detected.add(zn)
                det_with_zone = det.copy()  # Copie le dictionnaire
                det_with_zone["zones"] = zone_names  # Ajoute les zones
                detections_with_zone.append(det_with_zone)
            shared_detections[cid] = detections_with_zone

        with shared_motion_roi_lock:
            # Si la méthode motion.py retourne le tuple étendu (x_pad, y_pad, w_pad, h_pad, x, y, w, h)
            # on le stocke dans le dico partagé pour l'affichage vidéo
            if isinstance(x_pad, (tuple, list)) and len(x_pad) == 8:
                x_pad_val, y_pad_val, w_pad, h_pad, x_raw, y_raw, w_raw, h_raw = x_pad
                shared_motion_roi[cid] = {
                    "x_pad": x_pad_val,
                    "y_pad": y_pad_val,
                    "w_pad": w_pad,
                    "h_pad": h_pad,
                    "x": x_raw,
                    "y": y_raw,
                    "w": w_raw,
                    "h": h_raw
                }
            else:
                w = roi.shape[1] if roi is not None else 0
                h = roi.shape[0] if roi is not None else 0
                shared_motion_roi[cid] = {
                    "x_pad": x_pad if x_pad is not None else 0,
                    "y_pad": y_pad if y_pad is not None else 0,
                    "w": w,
                    "h": h
                }
        now = datetime.now()
        current_timestamp = now.timestamp()
        
        # ===== HEARTBEAT FAIL-SAFE =====
        # Mise à jour du heartbeat pour indiquer que l'application fonctionne
        update_heartbeat()

        # Correction asyncio event loop pour thread
        loop = main_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

        # Pour chaque zone, gérer l'état previous_detection
        for zone_name in zone_names_list:
            detected = zone_name in zones_detected
            if detected and not previous_detection[zone_name]:
                # Début d'une détection dans cette zone
                previous_detection[zone_name] = True
                # On peut logger ou déclencher une action spécifique à la zone ici si besoin
            elif not detected and previous_detection[zone_name]:
                # Fin de détection dans cette zone
                previous_detection[zone_name] = False
                logger.info(f"Plus de détection sur la caméra {cid} dans la zone {zone_name}")
                asyncio.run_coroutine_threadsafe(
                    alert_manager.on_no_more_detection(current_timestamp),
                    loop
                )

            # Filtrer pour l'alerte uniquement label == "person" ET personne_type == "pieton"
            detections_person = [det for det in detections if det.get("label") == "person" and det.get("personne_type") == "pieton"]
            
            # Ajouter les zones aux détections personnes et appliquer le filtrage par stature/zone
            detections_person_with_zone = []
            for det in detections_person:
                zone_names = get_zone_for_detection(det, zones)
                det_with_zone = det.copy()  # Copie le dictionnaire
                det_with_zone["zones"] = zone_names  # Ajoute les zones
                
                # Vérifier si cette détection doit déclencher une alerte selon les règles de stature/zone
                # if alert_manager.should_trigger_alert_for_detection(det_with_zone):
                detections_person_with_zone.append(det_with_zone)
            
            # Déclencher l'alerte seulement si il y a des détections valides après filtrage
            if len(detections_person_with_zone) > 0:
                current_day = now.strftime('%Y-%m-%d %H:%M:%S')
                frame = manager.get_frame_array(CAM_IDS[cid])
                logger.debug(f"Détections caméra {cid} (après filtrage stature/zone) : {detections_person_with_zone}, {current_day}")
                asyncio.run_coroutine_threadsafe(
                    alert_manager.on_detection(current_timestamp, frame, detections_person_with_zone, cid),
                    loop
                )
    return detection_callback


def get_frame_func_factory(cid):
    def get_frame():
        cam_id = CAM_IDS[cid]

        return manager.get_frame_array(cam_id)
    return get_frame


app = Flask(__name__)

# Liste des IDs caméras (0 et 1 pour deux webcams locales)
# CAM_IDS = [0,
#            "rtsp://192.168.1.160:8554/1080p?mp4"]
# CAM_IDS = [#"https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1747948294/ei/pj4vaKWjCIG26dsPgZWMmQY/ip/2a01:e0a:98b:f390:d9e5:921:b8ec:2037/id/DLmn7f9SJ5A.1/itag/231/source/yt_live_broadcast/requiressl/yes/ratebypass/yes/live/1/sgovp/gir%3Dyes%3Bitag%3D135/rqh/1/hls_chunk_host/rr2---sn-f5f7lnld.googlevideo.com/xpc/EgVo2aDSNQ%3D%3D/playlist_duration/3600/manifest_duration/3600/bui/AecWEAYdo8jXUuiyYqwt9J7AuirB1kCVOuO6QiLXSKqD2dUz0FiVDAjZe_mDnJ92gesE_6JdYJIby9fp/spc/wk1kZpBdDiWh6r8S_J9vSTgJvnlqSuTWBQBgbDZOUyFHpGLbYyZC_LgliKtiaA/vprv/1/playlist_type/DVR/initcwndbps/2483750/met/1747926694,/mh/xY/mm/44/mn/sn-f5f7lnld/ms/lva/mv/m/mvi/2/pl/49/rms/lva,lva/dover/13/pacing/0/short_key/1/keepalive/yes/fexp/51466697/mt/1747926298/sparams/expire,ei,ip,id,itag,source,requiressl,ratebypass,live,sgovp,rqh,xpc,playlist_duration,manifest_duration,bui,spc,vprv,playlist_type/sig/AJfQdSswRQIgJUaw2bG2iWHQWe-HG71kb45QCqu5_6pBNWx72GgdImcCIQCACtsj3VrFouAQ4tG91btKkXP8eImokT9Yv-v5tHl1sg%3D%3D/lsparams/hls_chunk_host,initcwndbps,met,mh,mm,mn,ms,mv,mvi,pl,rms/lsig/ACuhMU0wRQIgOFZwgnNWyUvLT6-Uw7TArbPxuHWy5dtpn7uRaPsAkTsCIQCdd3pF_vY6gGQLhxIRb6oHgu_bKUAandUgJw_VZtzpxw%3D%3D/playlist/index.m3u8",
#            #"https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1747948055/ei/tz0vaPm8HfPbp-oP7_rswQs/ip/2a01:e0a:98b:f390:d9e5:921:b8ec:2037/id/BxEmGNapmr4.1/itag/231/source/yt_live_broadcast/requiressl/yes/ratebypass/yes/live/1/sgovp/gir%3Dyes%3Bitag%3D135/rqh/1/hls_chunk_host/rr2---sn-f5f7lnl6.googlevideo.com/xpc/EgVo2aDSNQ%3D%3D/playlist_duration/3600/manifest_duration/3600/bui/AecWEAafHep9GERMJIvmdQEwNjbmPnxTllh1pgqqpD2_1w9L3vV7dl90wpjaB8eALAIbm7lXcj3TFsvs/spc/wk1kZsQEz-ZNU2FZZ7ys1TLImdDz96IC2NRXniNgdLmW-GdfEpE/vprv/1/playlist_type/DVR/initcwndbps/3122500/met/1747926455,/mh/_P/mm/44/mn/sn-f5f7lnl6/ms/lva/mv/m/mvi/2/pl/49/rms/lva,lva/dover/13/pacing/0/short_key/1/keepalive/yes/mt/1747926055/sparams/expire,ei,ip,id,itag,source,requiressl,ratebypass,live,sgovp,rqh,xpc,playlist_duration,manifest_duration,bui,spc,vprv,playlist_type/sig/AJfQdSswRQIge0HPNKKJhbewq55w1L9-2OEiQAFyTzH2vkYuqOiUuM4CIQCnQOJsBKH8twFrhGYVC-qerXrhSxgmra_XeH7rf0LSZA%3D%3D/lsparams/hls_chunk_host,initcwndbps,met,mh,mm,mn,ms,mv,mvi,pl,rms/lsig/ACuhMU0wRQIhANHYSy6fOYvTu0b-pVYCZlasl8ZC9Qt2_ICyr1wXi38oAiBEezZzs68ovRMGs722JIUQU5REHBpr7jdc8VZ0sG5sYg%3D%3D/playlist/index.m3u8"
#            #"rtsp://kubikub:Gvgywse1@192.168.1.16/ch0_0.h264",
#            #"rtsp://192.168.1.160:8554/1080p?mp4",
#            0]
CAM_IDS = []
for host in RTSP_HOST:
    CAM_IDS.append(f"rtsp://{RTSP_LOGIN}:{RTSP_PASSWORD}@{host}:{RTSP_PORT}/{RTSP_STREAM}")

if not CAM_IDS:
    logger.error("Aucun flux RTSP configuré. Vérifiez la section RTSP du fichier config.ini")
    raise RuntimeError("No RTSP streams configured")

# Vérification des flux RTSP avant d'instancier CameraManager : attente active jusqu'à ce qu'au moins une caméra réponde au ping
available_cam_ids = []
attempt = 0
retry_delay = max(1, WAIT_BEFORE_TEST_RTSP)
while not available_cam_ids:
    attempt += 1
    results = CameraManager.test_rtsp_streams_parallel(CAM_IDS)
    available_cam_ids = [cid for cid, ok in results.items() if ok]

    # Logger l'état de chaque caméra pour cette tentative
    for cid in CAM_IDS:
        if results.get(cid, False):
            logger.info(f"Ping OK pour {cid} (tentative {attempt})")
        else:
            logger.warning(f"Ping échoué pour {cid} (tentative {attempt})")

    if available_cam_ids:
        if WAIT_BEFORE_TEST_RTSP > 0:
            logger.info(
                f"Au moins une caméra répond au ping ({available_cam_ids[0]}). Attente de {WAIT_BEFORE_TEST_RTSP}s avant démarrage des flux RTSP..."
            )
            time.sleep(WAIT_BEFORE_TEST_RTSP)
        break

    logger.warning(
        f"Aucune caméra ne répond au ping (tentative {attempt}). Nouvelle tentative dans {retry_delay}s..."
    )
    time.sleep(retry_delay)

CAM_IDS = available_cam_ids
logger.info(f"Caméras RTSP disponibles : {CAM_IDS}")
manager = CameraManager(CAM_IDS, frame_width=1920, frame_height=1080)

# Threads d'inférence et events d'arrêt pour chaque caméra
inference_threads = {}
inference_stop_events = {}

# Dictionnaire partagé pour stocker les détections par caméra
shared_detections = {}
shared_detections_lock = threading.Lock()
shared_motion_roi = {}
shared_motion_roi_lock = threading.Lock()


# Dictionnaire pour activer/désactiver le stream de chaque caméra
stream_enabled = {}
# Dictionnaire pour activer/désactiver la détection de chaque caméra
detection_enabled = {}
# Dictionnaire pour activer/désactiver l'affichage des ROI de chaque caméra
roi_display_enabled = {}
for i in range(len(CAM_IDS)):
    stream_enabled[i] = False  # vidéo masquée par défaut
    detection_enabled[i] = True  # détection active par défaut
    roi_display_enabled[i] = False  # affichage ROI désactivé par défaut
    # Démarrage automatique de la détection
    stop_event = threading.Event()
    inference_stop_events[i] = stop_event
    thread = InferenceServerThread(
        home_dir=".",
        white_pixels_threshold=MOTIONTHRESHOLD,
        get_frame_func=get_frame_func_factory(i),
        detection_callback=detection_callback_factory(i, MAIN_LOOP),
        stop_event=stop_event
    )
    thread.start()
    inference_threads[i] = thread


def gen_frames(cid):
    cam_id = CAM_IDS[cid]
    last_frame_time = 0
    frame_interval = 0.2  # 5 FPS = 200ms entre frames
    logger.debug(f"🎬 Nouveau générateur de frames démarré pour caméra {cid}")
    
    while True:
        current_time = time.time()
        
        # On ne génère les frames que pour l'affichage vidéo
        if not stream_enabled.get(cid, True):
            # On attend que le stream soit réactivé, sans bloquer la détection
            logger.debug(f"⏸️  Stream désactivé pour caméra {cid}")
            time.sleep(0.2)
            continue
            
        # Limiter la fréquence de génération des frames pour l'affichage
        if current_time - last_frame_time < frame_interval:
            time.sleep(0.01)
            continue
            
        # Vérifier le cache de frame
        with frame_cache_lock:
            cached_frame = frame_cache.get(cid)
            cache_time = frame_cache_timestamp.get(cid, 0)
            
        # Debug détaillé du cache (réduit)
        if cached_frame is not None:
            cache_age_ms = (current_time - cache_time) * 1000
            # Log seulement si on est proche de l'expiration ou si c'est un problème
            # if cache_age_ms > FRAME_CACHE_DURATION * 800:  # 80% de la durée
            #     logger.debug(f"🔍 Cache check caméra {cid}: âge={cache_age_ms:.1f}ms, limite={FRAME_CACHE_DURATION*1000:.0f}ms")
        
        # Utiliser le cache si la frame est récente
        if cached_frame is not None and current_time - cache_time < FRAME_CACHE_DURATION:
            cache_age_ms = (current_time - cache_time) * 1000
            cache_performance_stats['hits'] += 1
            # Log moins verbeux des hits
            # if cache_performance_stats['hits'] % 10 == 0:  # Log tous les 10 hits
                # hit_rate = cache_performance_stats['hits'] / (cache_performance_stats['hits'] + cache_performance_stats['misses']) * 100
                # logger.debug(f"📋 Cache HIT pour caméra {cid} - Taux: {hit_rate:.1f}% (dernier âge: {cache_age_ms:.1f}ms)")
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + cached_frame + b'\r\n')
            last_frame_time = current_time
            continue
            
        frame = manager.get_frame_array(cam_id)
        if frame is not None:
            cache_performance_stats['misses'] += 1
            # Log moins verbeux des misses
            # if cache_performance_stats['misses'] % 5 == 0:  # Log tous les 5 misses
                # logger.debug(f"🔄 Cache MISS pour caméra {cid} - Génération nouvelle frame...")
            generation_start_time = time.time()
            
            # Vérifier que la frame est valide avant de la copier
            try:
                frame = frame.copy()  # Rendre la frame modifiable
                h, w = frame.shape[:2]
            except Exception as e:
                logger.error(f"❌ Erreur lors de la copie de frame pour caméra {cid}: {e}")
                time.sleep(0.1)
                continue
                
            with shared_detections_lock:
                detections = shared_detections.get(cid, [])
            with shared_motion_roi_lock:
                roi_info = shared_motion_roi.get(cid, None)
            # Afficher les ROI seulement si activé
            if roi_display_enabled.get(cid, False) and roi_info and roi_info.get("w_pad", 0) > 0 and roi_info.get("h_pad", 0) > 0:
                x_pad = roi_info["x_pad"]
                y_pad = roi_info["y_pad"]
                w_roi = roi_info["w_pad"]
                h_roi = roi_info["h_pad"]
                # Rectangle rouge (ROI avec padding)
                x1 = max(0, min(w - 1, x_pad))
                y1 = max(0, min(h - 1, y_pad))
                x2 = max(0, min(w - 1, x_pad + w_roi))
                y2 = max(0, min(h - 1, y_pad + h_roi))
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                # Rectangle jaune (mouvement brut sans padding)
                x_raw = roi_info.get("x", 0)
                y_raw = roi_info.get("y", 0)
                w_raw = roi_info.get("w", 0)
                h_raw = roi_info.get("h", 0)
                if w_raw > 0 and h_raw > 0:
                    x1r = max(0, min(w - 1, x_raw))
                    y1r = max(0, min(h - 1, y_raw))
                    x2r = max(0, min(w - 1, x_raw + w_raw))
                    y2r = max(0, min(h - 1, y_raw + h_raw))
                    cv2.rectangle(frame, (x1r, y1r), (x2r, y2r), (0, 255, 255), 2)
            # Superposer l'overlay des zones (créé une seule fois)
            zone_overlay = get_zone_overlay(frame.shape, cid)
            # Créer un masque pour ne dessiner que les pixels non-noirs de l'overlay
            mask = np.any(zone_overlay > 0, axis=2)
            frame[mask] = zone_overlay[mask]
            # Récupérer l'état du mouvement depuis le thread d'inférence
            motion = False
            if cid in inference_threads:
                motion = inference_threads[cid].motion
            for det in detections:
                # Maintenant det est un dictionnaire
                zone_names = det.get("zones", [])  # Si les zones ont été ajoutées
                x1 = max(0, min(w-1, int(det["x_min"])))
                y1 = max(0, min(h-1, int(det["y_min"])))
                x2 = max(0, min(w-1, int(det["x_max"])))
                y2 = max(0, min(h-1, int(det["y_max"])))
                # Dessiner le rectangle de détection
                # Déterminer la couleur basée sur le type detectée
                label = det.get("label")
                if isinstance(label, tuple) and len(label) > 0:
                    label = label[0]  # Extraire la stature du tuple (stature, debug_info)
                if not isinstance(label, str):
                    label = "Unknown"

                color_rgb = OBJECT_COLORS.get(label, (0, 0, 255))  # Bleu par défaut
                color_bgr = (color_rgb[2], color_rgb[1], color_rgb[0])  # Conversion RGB vers BGR pour OpenCV

                cv2.rectangle(frame, (x1, y1), (x2, y2), color_bgr, 2)
                # Optionnel : afficher la confiance
                confidence = det.get("confidence", 0)
                class_id = det.get("class_id", -1)
                # tracker_id = det.get("tracker_id", -1)
                # label = det.get("label", "unknown")
                label = f'{confidence:.2f} {label} '
                cv2.putText(frame, label, (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_bgr, 2)
                # Afficher la zone sur la détection
                if zone_names:
                    for i, zone_name in enumerate(zone_names):
                        # Utiliser le cache pour la couleur de la zone
                        color = zone_color_cache[cid].get(zone_name, (255, 0, 0))
                        cv2.putText(frame, zone_name, (x1, y2 + 20 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            # Ajout du point vert si mouvement détecté
            if motion:
                # En haut à droite
                cv2.circle(frame, (w - 20, 20), 15, (0, 0, 255), -1)
            # Encodage JPEG optimisé pour réduire la latence
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, FRAME_QUALITY_OPTIMIZED])
            if ret:
                frame_bytes = buffer.tobytes()
                generation_time_ms = (time.time() - generation_start_time) * 1000
                cache_performance_stats['total_generation_time'] += generation_time_ms
                
                # Mettre en cache la frame encodée
                with frame_cache_lock:
                    frame_cache[cid] = frame_bytes
                    frame_cache_timestamp[cid] = current_time
                    cache_size = len(frame_cache)
                
                avg_generation_time = cache_performance_stats['total_generation_time'] / cache_performance_stats['misses']
                hit_rate = cache_performance_stats['hits'] / (cache_performance_stats['hits'] + cache_performance_stats['misses']) * 100
                # Log moins verbeux des générations
                # if cache_performance_stats['misses'] % 10 == 0:  # Log tous les 10 misses
                    # logger.debug(f"💾 Frame générée pour caméra {cid} en {generation_time_ms:.1f}ms (moy: {avg_generation_time:.1f}ms)")
                    # logger.debug(f"   Cache: {len(frame_bytes)} bytes, {cache_size} entrées, taux HIT: {hit_rate:.1f}%")

                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                last_frame_time = current_time
            else:
                logger.error(f"❌ Erreur encodage JPEG pour caméra {cid}")
                break
        else:
            logger.debug(f"⏳ Pas de frame disponible pour caméra {cid}")
            time.sleep(0.1)  # Attendre si pas de frame disponible


@app.route('/')
def index():
    # Préparer une liste de dicts avec l'id et le seuil de chaque caméra
    cam_infos = []
    for idx, cam_id in enumerate(CAM_IDS):
        threshold = MOTIONTHRESHOLD  # valeur par défaut
        if idx in inference_threads:
            threshold = getattr(inference_threads[idx], 'white_pixels_threshold', MOTIONTHRESHOLD)
        cam_infos.append({
            'id': cam_id,
            'idx': idx,
            'white_pixels_threshold': threshold,
            'roi_display_enabled': roi_display_enabled.get(idx, False)
        })
    return render_template('index.html', cam_infos=cam_infos, app_name=APP_NAME, app_version=APP_VERSION, telegram_alert_enabled=telegram_alert_enabled, stature_colors=OBJECT_COLORS)

# --- Ajout route pour modifier dynamiquement les paramètres motion ---
@app.route('/set_motion_param/<int:cid>', methods=['POST'])
def set_motion_param(cid):
    data = request.json
    param = data.get('param')
    value = data.get('value')

    # Correction : rediriger 'min_area' vers 'min_contour_area' pour le MotionDetector
    if param == 'min_area':
        param_detector = 'min_contour_area'
    else:
        param_detector = param

    if cid not in inference_threads:
        return jsonify({'status': 'error', 'message': 'Caméra inconnue'}), 400

    # Traitez le paramètre spécial pour le thread
    if param == 'white_pixels_threshold':
        try:
            inference_threads[cid].white_pixels_threshold = int(value)
            return jsonify({'status': 'ok'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400

    detector = getattr(inference_threads[cid], 'motion_detector', None)
    if detector is None:
        return jsonify({'status': 'error', 'message': 'MotionDetector non trouvé'}), 400


    try:
        # Conversion typée
        if param in ('padding', 'min_area', 'varThreshold', 'history'):
            value = int(value)
        if param == 'detectShadows':
            value = value in (True, 'true', 'True', 1, '1', 'on')

        # Mise à jour simple pour champ non MOG2
        if param not in ('varThreshold', 'history', 'detectShadows'):
            if hasattr(detector, param_detector):
                setattr(detector, param_detector, value)
            else:
                return jsonify({'status': 'error', 'message': f'Paramètre {param} inconnu'}), 400

        # Mise à jour via la méthode dédiée pour MOG2
        if param in ('varThreshold', 'history', 'detectShadows'):
            # Ne pas faire le setattr ici, laisser update_fgbg_params gérer l'affectation et la comparaison
            kwargs = {
                'varThreshold': value if param == 'varThreshold' else getattr(detector, 'varThreshold', None),
                'history': value if param == 'history' else getattr(detector, 'history', None),
                'detectShadows': value if param == 'detectShadows' else getattr(detector, 'detectShadows', None)
            }
            detector.update_fgbg_params(**kwargs)
            logger.debug(f"[ROUTE] Appel update_fgbg_params sur MotionDetector id={id(detector)} pour cid={cid} avec param={param}, value={value}")
            

        return jsonify({'status': 'ok'})

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400


@app.route('/video_feed/<int:cid>')
def video_feed(cid):
    return Response(gen_frames(cid),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


# Exemple de contrôle caméra (exposition, gain, etc.)
@app.route('/set_control/<int:cid>', methods=['POST'])
def set_control(cid):
    control = request.json.get('control')
    value = request.json.get('value')
    cam = manager.cams.get(cid)
    if cam is not None:
        # Exemple : changer la luminosité
        if control == "brightness":
            cam.set(10, float(value))  # 10 = cv2.CAP_PROP_BRIGHTNESS
        elif control == "exposure":
            cam.set(15, float(value))  # 15 = cv2.CAP_PROP_EXPOSURE
        # Ajoute d'autres contrôles ici
        return jsonify({"status": "ok"})
    return jsonify({"status": "error"}), 404


@app.route('/toggle_detection/<int:cid>', methods=['POST'])
def toggle_detection(cid):
    data = request.get_json()
    enabled = data.get('enabled', False)
    detection_enabled[cid] = enabled
    if enabled:
        if cid not in inference_threads or not inference_threads[cid].is_alive():
            stop_event = threading.Event()
            inference_stop_events[cid] = stop_event
            thread = InferenceServerThread(
                home_dir=".",
                get_frame_func=get_frame_func_factory(cid),
                detection_callback=detection_callback_factory(cid, MAIN_LOOP),
                stop_event=stop_event
            )
            thread.start()
            inference_threads[cid] = thread
    else:
        if cid in inference_stop_events:
            inference_stop_events[cid].set()
        # Nettoyer les détections affichées
        with shared_detections_lock:
            shared_detections[cid] = []
    return jsonify({'status': 'ok', 'enabled': enabled})


@app.route('/toggle_stream/<int:cid>', methods=['POST'])
def toggle_stream(cid):
    data = request.get_json()
    enabled = data.get('enabled', True)
    stream_enabled[cid] = enabled
    return jsonify({'status': 'ok', 'enabled': enabled})


@app.route('/toggle_roi_display/<int:cid>', methods=['POST'])
def toggle_roi_display(cid):
    data = request.get_json()
    enabled = data.get('enabled', False)
    roi_display_enabled[cid] = enabled
    return jsonify({'status': 'ok', 'enabled': enabled})


telegram_alert_enabled = False


@app.route('/toggle_telegram_alert', methods=['POST'])
def toggle_telegram_alert():
    global telegram_alert_enabled
    data = request.get_json()
    telegram_alert_enabled = bool(data.get('enabled', True))
    if hasattr(alert_manager, 'set_telegram_alert_enabled'):
        alert_manager.set_telegram_alert_enabled(telegram_alert_enabled)
    return jsonify({'status': 'ok', 'enabled': telegram_alert_enabled})


@app.route('/shutdown')
def shutdown():
    manager.release()
    return "Cameras released"


@app.route('/failsafe_status')
def failsafe_status():
    """Endpoint pour vérifier l'état du système fail-safe."""
    with heartbeat_lock:
        time_since_heartbeat = time.time() - last_heartbeat
        
    relay_states = {}
    for i in range(len(relays.relays)):
        relay_states[f"relay_{i}"] = relays.get_relay_state(i)
    
    return jsonify({
        'application_healthy': application_healthy,
        'last_heartbeat_seconds_ago': round(time_since_heartbeat, 2),
        'heartbeat_timeout': HEARTBEAT_TIMEOUT,
        'failsafe_mode': 'ACTIVE' if not application_healthy else 'STANDBY',
        'relay_states': relay_states,
        'relays_initialized': relays.is_initialized,
        'message': 'Système opérationnel' if application_healthy else '⚠️  MODE FAIL-SAFE ACTIF - Alertes maintenues ON'
    })


@app.route('/quit', methods=['POST'])
def quit_server():
    manager.release()
    func = request.environ.get('werkzeug.server.shutdown')
    if func is not None:
        func()
    else:
        import os
        os._exit(0)
    return 'Serveur arrêté.'


@app.route('/debug_info')
def debug_info():
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.5)
    disk = psutil.disk_usage('/')
    ip_str = ', '.join(get_non_local_ips()) or "N/A"
    docker_info = get_docker_info()
    service_status = get_service_status('4isafecross.service')
    try:
        load1, load5, load15 = os.getloadavg()
        load1 = round(load1, 1)
        load5 = round(load5, 1)
        load15 = round(load15, 1)
    except Exception as e:
        load1 = load5 = load15 = f"Erreur: {e}"
    return jsonify({
        'ram_used': round(mem.used / 1024 / 1024, 1),
        'ram_total': round(mem.total / 1024 / 1024, 1),
        'cpu_percent': cpu,
        'disk_used': round(disk.used / 1024 / 1024 / 1024, 2),
        'disk_total': round(disk.total / 1024 / 1024 / 1024, 2),
        'disk_percent': disk.percent,
        'ip': ip_str,
        'docker_info': docker_info,
        'service_status': service_status,
        'load_avg': f"{load1} / {load5} / {load15}"
    })


@app.route('/detections_thumbs')
def detections_thumbs():
    # Récupère les 10 dernières images du dossier detections
    try:
        files = glob.glob(os.path.join('detections', '*.jpg'))
        files.sort(key=os.path.getctime, reverse=True)
        last_files = files[:10]
        # On ne retourne que les noms de fichiers (pas le chemin complet)
        last_files = [os.path.basename(f) for f in last_files]
        return jsonify({'images': last_files})
    except Exception as e:
        return jsonify({'images': [], 'error': str(e)})


@app.route('/detections/<filename>')
def serve_detection_image(filename):
    # Sert une image du dossier detections
    return send_from_directory('detections', filename)


@app.route('/switch_inference_mode/<int:cid>', methods=['POST'])
def switch_inference_mode(cid):
    if cid in inference_threads:
        inference_threads[cid].switch_inference_mode()
        return jsonify({'status': 'ok', 'mode': inference_threads[cid].inference_mode})
    return jsonify({'status': 'error', 'message': 'Caméra inconnue'}), 400


@app.route('/set_zones', methods=['POST'])
def set_zones():
    data = request.get_json()
    zones = data.get('zones', [])
    alert_manager.set_zones(zones)
    
    # Vider le cache des overlays car les zones ont changé
    with zone_overlay_lock:
        zone_overlay_cache.clear()
        logger.debug("🗑️ Cache des overlays de zones vidé suite à modification des zones")
    
    return jsonify({'status': 'ok'})


# ===== ÉDITEUR DE ZONES =====

ZONES_INI_PATH = 'config/zones.ini'

# Palette de couleurs automatiques pour les zones
ZONE_COLORS_PALETTE = [
    (128, 255, 0),    # Vert clair
    (255, 128, 0),    # Orange
    (255, 255, 0),    # Jaune
    (0, 255, 255),    # Cyan
    (255, 0, 255),    # Magenta
    (0, 128, 255),    # Bleu clair
    (255, 64, 64),    # Rouge clair
    (128, 0, 255),    # Violet
]


@app.route('/snapshot/<int:cid>')
def snapshot(cid):
    """Retourne un snapshot JPEG de la caméra spécifiée."""
    if cid < 0 or cid >= len(CAM_IDS):
        return jsonify({'error': 'Caméra inconnue'}), 404
    frame_bytes = manager.get_frame(CAM_IDS[cid])
    if frame_bytes is None:
        return jsonify({'error': 'Caméra hors ligne'}), 503
    return Response(frame_bytes, mimetype='image/jpeg')


@app.route('/api/zones/<int:cid>', methods=['GET'])
def get_zones(cid):
    """Retourne les zones polygones de la caméra spécifiée en JSON."""
    zones = zones_by_camera.get(cid, [])
    result = []
    for zone in zones:
        if 'polygon' not in zone:
            continue  # Ignorer les zones rect
        result.append({
            'name': zone['name'],
            'polygon': [list(pt) for pt in zone['polygon']],
            'color': list(zone.get('color', (255, 0, 0))),
            'relays': zone.get('relays', []),
        })
    return jsonify(result)


@app.route('/api/zones/<int:cid>', methods=['POST'])
def save_zones(cid):
    """Sauvegarde les zones d'une caméra dans zones.ini et recharge."""
    global zones_by_camera
    data = request.get_json()
    zones_data = data.get('zones', [])

    # Attribuer les couleurs automatiquement si absentes
    for i, zone in enumerate(zones_data):
        if 'color' not in zone or not zone['color']:
            zone['color'] = list(ZONE_COLORS_PALETTE[i % len(ZONE_COLORS_PALETTE)])
        # S'assurer du nommage correct
        if 'name' not in zone or not zone['name']:
            zone['name'] = f'zone{i + 1}_cam{cid}'

    try:
        # Sauvegarder dans le fichier INI
        save_zones_to_ini(ZONES_INI_PATH, cid, zones_data)

        # Recharger toutes les zones depuis le fichier
        zones_by_camera = load_zones_by_camera_from_ini(ZONES_INI_PATH)

        # Vider tous les caches
        with zone_overlay_lock:
            zone_overlay_cache.clear()
        with frame_cache_lock:
            frame_cache.clear()
            frame_cache_timestamp.clear()
        zone_color_cache.clear()

        # Mettre à jour l'alert manager avec toutes les zones (toutes caméras)
        alert_manager.set_zones(zones_by_camera)

        logger.info(f"✅ Zones cam{cid} sauvegardées et rechargées ({len(zones_data)} zones)")
        return jsonify({'status': 'ok', 'zones_count': len(zones_data)})

    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde zones cam{cid}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/relay-count')
def relay_count():
    """Retourne le nombre de relais physiques disponibles."""
    return jsonify({'count': len(relays.relays) or NUM_RELAYS})


@app.route('/zone_editor/<int:cid>')
def zone_editor(cid):
    """Page d'édition visuelle des zones pour une caméra."""
    if cid < 0 or cid >= len(CAM_IDS):
        return "Caméra inconnue", 404
    cam_name = f"Camera {cid + 1}"
    return render_template(
        'zone_editor.html',
        cid=cid,
        cam_name=cam_name,
        app_name=APP_NAME,
        app_version=APP_VERSION,
        num_relays=len(relays.relays) or NUM_RELAYS,
    )


@app.route('/clear_frame_cache', methods=['POST'])
def clear_frame_cache():
    """Force le nettoyage du cache de frames"""
    with frame_cache_lock:
        cache_size = len(frame_cache)
        frame_cache.clear()
        frame_cache_timestamp.clear()
        logger.debug(f"🗑️ Cache de frames vidé manuellement ({cache_size} entrées supprimées)")
    
    return jsonify({'status': 'ok', 'cleared_entries': cache_size})


@app.route('/clear_zone_cache', methods=['POST'])
def clear_zone_cache():
    """Vide le cache des overlays de zones"""
    with zone_overlay_lock:
        cache_size = len(zone_overlay_cache)
        zone_overlay_cache.clear()
        logger.debug(f"🗑️ Cache des overlays de zones vidé manuellement ({cache_size} entrées supprimées)")
    
    return jsonify({'status': 'ok', 'cleared_entries': cache_size})


@app.route('/cam_status/<int:cid>')
def cam_status(cid):
    return jsonify({'status': manager.get_status(CAM_IDS[cid])})


@app.route('/cache_stats')
def cache_stats():
    """Endpoint pour obtenir les statistiques du cache de frames"""
    current_time = time.time()
    with frame_cache_lock:
        cache_info = {}
        total_size = 0
        expired_count = 0
        
        for cam_id, frame_data in frame_cache.items():
            timestamp = frame_cache_timestamp.get(cam_id, 0)
            age_ms = (current_time - timestamp) * 1000
            size_bytes = len(frame_data)
            total_size += size_bytes
            is_fresh = age_ms < FRAME_CACHE_DURATION * 1000
            
            if not is_fresh:
                expired_count += 1
            
            cache_info[cam_id] = {
                'age_ms': round(age_ms, 1),
                'size_bytes': size_bytes,
                'size_kb': round(size_bytes / 1024, 1),
                'is_fresh': is_fresh,
                'expired': age_ms > FRAME_CACHE_DURATION * 1000
            }

        # Calculer les statistiques de performance
        total_requests = cache_performance_stats['hits'] + cache_performance_stats['misses']
        hit_rate = (cache_performance_stats['hits'] / max(total_requests, 1)) * 100
        avg_generation_time = cache_performance_stats['total_generation_time'] / max(cache_performance_stats['misses'], 1)

        stats = {
            'cache_duration_ms': FRAME_CACHE_DURATION * 1000,
            'frame_quality': FRAME_QUALITY_OPTIMIZED,
            'total_entries': len(frame_cache),
            'expired_entries': expired_count,
            'total_size_bytes': total_size,
            'total_size_kb': round(total_size / 1024, 1),
            'hit_rate_percent': round(hit_rate, 1),
            'average_generation_time_ms': round(avg_generation_time, 1),
            'total_requests': total_requests,
            'cameras': cache_info
        }

    return jsonify(stats)

@app.route('/api/inference/stats')
def inference_stats():
    """Endpoint pour obtenir les statistiques d'optimisation de l'inférence."""
    stats = {}

    # Récupérer les stats de tous les threads d'inférence actifs
    for cid, inference_thread in inference_threads.items():
        if inference_thread and hasattr(inference_thread, 'get_optimization_stats'):
            camera_stats = inference_thread.get_optimization_stats()
            camera_stats['camera_id'] = cid
            camera_stats['inference_mode'] = inference_thread.inference_mode
            camera_stats['url'] = inference_thread.url
            stats[f'camera_{cid}'] = camera_stats
    
    # Calculer les totaux
    total_frames = sum(s.get('total_frames', 0) for s in stats.values())
    total_skipped = sum(s.get('skipped_frames', 0) for s in stats.values())
    total_time_saved = sum(s.get('time_saved_ms', 0) for s in stats.values())
    
    summary = {
        'total_frames_processed': total_frames,
        'total_frames_skipped': total_skipped,
        'overall_skip_rate': round((total_skipped / max(total_frames, 1)) * 100, 1),
        'total_time_saved_ms': total_time_saved,
        'total_time_saved_seconds': round(total_time_saved / 1000, 1),
        'cameras': stats
    }
    
    return jsonify(summary)


if __name__ == '__main__':
    from waitress import serve
    serve(app, host='0.0.0.0', port=5050)
