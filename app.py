from flask import Flask, render_template, Response, request, jsonify, send_from_directory
from src.camera_manager import CameraManager
from src.inference import InferenceServerThread
from src.alert_manager import AlerteManager
from utils.utils import get_non_local_ips, get_docker_info, get_service_status
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
from utils.constants import (MOTIONTRESHOLD, APP_NAME, APP_VERSION, RTSP_LOGIN,
                       RTSP_PASSWORD, RTSP_HOST, RTSP_PORT, RTSP_STREAM, LOG_LEVEL, ZONES_BY_CAMERA)
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
    relays.action_off(i)  # Assure que tous les relais sont éteints au démarrage
    logger.debug(f"Relais {i} : {relays.get_relay_state(i)}")
# logger.info(f"Relais initialisé : {relays.is_initialized}, état actuel : {relays.states}")
# Lancer le bot Telegram au démarrage de l'app
telegram_bot = BotThread(overwrite_file=False)
threading.Thread(target=telegram_bot.run, daemon=True).start()

# Définir les zones pour chaque caméra
zones_by_camera = ZONES_BY_CAMERA

# On passe par défaut les zones de la caméra 0 à l'alert_manager (pour compatibilité)
alert_manager = AlerteManager(relays, telegram_bot=telegram_bot, zones=zones_by_camera.get(0, []), telegram_alert_enabled=False)


def get_zone_for_detection(det, zones):
    # det : [x1, y1, x2, y2, ...]
    # On prend le centre du rectangle de détection
    x_centre = int((det[0] + det[2]) / 2)
    y_centre = int((det[1] + det[3]) / 2)
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
                det_with_zone = list(det) + [zone_names]
                detections_with_zone.append(det_with_zone)
            shared_detections[cid] = detections_with_zone

        with shared_motion_roi_lock:
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

            # Filtrer pour l'alerte uniquement class_id == 1
            detections_person = [det for det in detections if len(det) > 5 and det[5] == 1]
            if len(detections_person) > 0:
                current_day = now.strftime('%Y-%m-%d %H:%M:%S')
                frame = manager.get_frame_array(CAM_IDS[cid])
                # Ajoute les zones aux détections personnes
                detections_person_with_zone = []
                for det in detections_person:
                    zone_names = get_zone_for_detection(det, zones)
                    detections_person_with_zone.append(list(det) + [zone_names])
                logger.debug(f"Détections caméra {cid} (personnes) : {detections_person_with_zone}, {current_day}")
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

# Vérification des flux RTSP avant d'instancier CameraManager
results = CameraManager.test_rtsp_streams_parallel(CAM_IDS)
filtered_cam_ids = [cid for cid, ok in results.items() if ok]
for cid, ok in results.items():
    if ok:
        logger.info(f"Ping OK pour {cid}, attente 20s avant test RTSP...")
        time.sleep(20)
        break  # On passe à la suite dès qu'une caméra est OK
    else:
        logger.warning(f"Flux RTSP {cid} ignoré (non disponible)")
CAM_IDS = filtered_cam_ids
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
for i in range(len(CAM_IDS)):
    stream_enabled[i] = False  # vidéo masquée par défaut
    detection_enabled[i] = True  # détection active par défaut
    # Démarrage automatique de la détection
    stop_event = threading.Event()
    inference_stop_events[i] = stop_event
    thread = InferenceServerThread(
        home_dir=".",
        white_pixels_threshold=MOTIONTRESHOLD,
        get_frame_func=get_frame_func_factory(i),
        detection_callback=detection_callback_factory(i, MAIN_LOOP),
        stop_event=stop_event
    )
    thread.start()
    inference_threads[i] = thread


def gen_frames(cid):
    cam_id = CAM_IDS[cid]
    while True:
        # On ne génère les frames que pour l'affichage vidéo
        if not stream_enabled.get(cid, True):
            # On attend que le stream soit réactivé, sans bloquer la détection
            time.sleep(0.2)
            continue
        frame = manager.get_frame_array(cam_id)
        if frame is not None:
            frame = frame.copy()  # Correction : rendre la frame modifiable
            h, w = frame.shape[:2]
            with shared_detections_lock:
                detections = shared_detections.get(cid, [])
            with shared_motion_roi_lock:
                roi_info = shared_motion_roi.get(cid, None)
            if roi_info and roi_info["w"] > 0 and roi_info["h"] > 0:
                x_pad = roi_info["x_pad"]
                y_pad = roi_info["y_pad"]
                w_roi = roi_info["w"]
                h_roi = roi_info["h"]
                # Clamp les coordonnées pour rester dans l'image
                x1 = max(0, min(w - 1, x_pad))
                y1 = max(0, min(h - 1, y_pad))
                x2 = max(0, min(w - 1, x_pad + w_roi))
                y2 = max(0, min(h - 1, y_pad + h_roi))
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
            # Tracer les zones spécifiques à la caméra
            zones = zones_by_camera.get(cid, [])
            for i, zone in enumerate(zones):
                color = zone.get("color", (0, 255, 0))  # Utilise la couleur de la zone, vert par défaut
                if "polygon" in zone:
                    # On s'assure que les points sont dans l'image
                    pts = [
                        (max(0, min(w - 1, int(xy[0]))), max(0, min(h - 1, int(xy[1]))))
                        for xy in zone["polygon"]
                    ]
                    pts_np = np.array([pts], dtype=np.int32)
                    cv2.polylines(frame, pts_np, isClosed=True, color=color, thickness=4)
                    # Afficher le nom de la zone au premier point
                    cv2.putText(frame, zone["name"], (pts[0][0], pts[0][1] + 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 3)
                elif "rect" in zone:
                    x1, y1, x2, y2 = zone["rect"]
                    # S'assurer que la zone ne dépasse pas l'image
                    x1 = max(0, min(w - 1, x1))
                    y1 = max(0, min(h - 1, y1))
                    x2 = max(0, min(w - 1, x2))
                    y2 = max(0, min(h - 1, y2))
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 4)
                    cv2.putText(frame, zone["name"], (x1, y1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 3)
            # Récupérer l'état du mouvement depuis le thread d'inférence
            motion = False
            if cid in inference_threads:
                motion = inference_threads[cid].motion
            for det in detections:
                # On suppose que la zone est à la fin de la détection
                zone_names = det[-1] if isinstance(det[-1], list) else []
                x1 = max(0, min(w-1, int(det[0])))
                y1 = max(0, min(h-1, int(det[1])))
                x2 = max(0, min(w-1, int(det[2])))
                y2 = max(0, min(h-1, int(det[3])))
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                # Optionnel : afficher la confiance
                if len(det) > 5:
                    label = f"{det[4]:.2f} {COCO_CLASSES.get(det[5], 'unknown')}"  # Confiance et classe
                    cv2.putText(frame, label, (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                # Afficher la zone sur la détection
                if zone_names:
                    for i, zone_name in enumerate(zone_names):
                        # Chercher la couleur de la zone si disponible
                        color = (255, 0, 0)
                        for z in zones:
                            if z["name"] == zone_name:
                                color = z.get("color", (255, 0, 0))
                                break
                        cv2.putText(frame, zone_name, (x1, y2 + 20 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            # Ajout du point vert si mouvement détecté
            if motion:
                # En haut à droite
                cv2.circle(frame, (w - 20, 20), 15, (0, 0, 255), -1)
            # Encodage JPEG
            ret, buffer = cv2.imencode('.jpg', frame)
            if ret:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            else:
                break
        else:
            break


@app.route('/')
def index():
    # Préparer une liste de dicts avec l'id et le seuil de chaque caméra
    cam_infos = []
    for idx, cam_id in enumerate(CAM_IDS):
        threshold = MOTIONTRESHOLD  # valeur par défaut
        if idx in inference_threads:
            threshold = getattr(inference_threads[idx], 'white_pixels_threshold', MOTIONTRESHOLD)
        cam_infos.append({'id': cam_id, 'idx': idx, 'white_pixels_threshold': threshold})
    return render_template('index.html', cam_infos=cam_infos, app_name=APP_NAME, app_version=APP_VERSION, telegram_alert_enabled=telegram_alert_enabled)

# --- Ajout route pour modifier dynamiquement les paramètres motion ---
@app.route('/set_motion_param/<int:cid>', methods=['POST'])
def set_motion_param(cid):
    data = request.get_json()
    param = data.get('param')
    value = data.get('value')
    if cid in inference_threads:
        # Gestion spéciale pour le seuil white_pixels_threshold (attribut du thread, pas du motion_detector)
        if param == 'white_pixels_threshold':
            try:
                value = int(value)
                inference_threads[cid].white_pixels_threshold = value
                return jsonify({'status': 'ok'})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400
        detector = getattr(inference_threads[cid], 'motion_detector', None)
        if detector is None:
            return jsonify({'status': 'error', 'message': 'MotionDetector non trouvé'}), 400
        try:
            # Conversion des types selon le paramètre
            if param in ('padding', 'min_area', 'varThreshold', 'history'):
                value = int(value)
            if param == 'detectShadows':
                value = value in (True, 'true', 'True', 1, '1', 'on')
                setattr(detector, 'detectShadows', value)
            elif param in ('varThreshold', 'history'):
                # Toujours stocker ces valeurs dans l'objet pour la réinstanciation
                setattr(detector, param, value)
            elif hasattr(detector, param):
                setattr(detector, param, value)
            else:
                return jsonify({'status': 'error', 'message': f'Paramètre {param} inconnu'}), 400
            # Si on modifie varThreshold, history ou detectShadows, il faut ré-instancier le MOG2
            if param in ('varThreshold', 'history', 'detectShadows'):
                detector.fgbg = cv2.createBackgroundSubtractorMOG2(
                    history=getattr(detector, 'history', 500),
                    varThreshold=getattr(detector, 'varThreshold', 16),
                    detectShadows=getattr(detector, 'detectShadows', True)
                )
            return jsonify({'status': 'ok'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
    return jsonify({'status': 'error', 'message': 'Caméra inconnue'}), 400

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

@app.route('/set_white_pixels_threshold/<int:cid>', methods=['POST'])
def set_white_pixels_threshold(cid):
    data = request.get_json()
    threshold = data.get('threshold')
    if threshold is not None and cid in inference_threads:
        try:
            threshold = int(threshold)
            # logger.info(f"Setting white pixels threshold for camera {cid} to {threshold}")
            inference_threads[cid].white_pixels_threshold = threshold
            return jsonify({'status': 'ok', 'threshold': threshold})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
    return jsonify({'status': 'error', 'message': 'Caméra ou seuil invalide'}), 400


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
    return jsonify({'status': 'ok'})


@app.route('/cam_status/<int:cid>')
def cam_status(cid):
    return jsonify({'status': manager.get_status(CAM_IDS[cid])})


if __name__ == '__main__':
    from waitress import serve
    serve(app, host='0.0.0.0', port=5050)
