"""Pipeline de détection : callback appelé par les threads d'inférence.

Applique les filtres anti-faux-positifs (keypoints via alert_manager, debounce
temporel par zone, recouvrement IoU personne/forklift), met à jour les
structures partagées pour l'affichage et déclenche les alertes.
"""
import asyncio
import logging
import time
from datetime import datetime

import cv2
import numpy as np

from src.core import failsafe, geometry
from src.core.state import state

logger = logging.getLogger(__name__)


def get_frame_func_factory(cid):
    def get_frame():
        cam_id = state.cam_ids[cid]

        return state.manager.get_frame_array(cam_id)
    return get_frame


def detection_callback_factory(cid, main_loop=None):
    # previous_detection devient un dict par zone
    previous_detection = {}
    # Debounce : fenêtre temporelle glissante de détection par zone.
    # Une alerte nécessite PERSON_DEBOUNCE_FRAMES détections valides dans la fenêtre PERSON_WINDOW_SECONDS.
    # Le counter ne se remet à 0 qu'après PERSON_RESET_SECONDS sans aucune détection.
    # Robuste aux dropouts MOG2 (frames vides ponctuelles entre deux inférences réelles).
    person_consecutive_frames = {}  # {zone_name: int}
    person_last_detect_time = {}    # {zone_name: float} — timestamp de la dernière détection valide
    PERSON_DEBOUNCE_FRAMES = 2
    PERSON_RESET_SECONDS = 0.8      # Reset le counter après 800ms sans détection

    def _get_zone_debounce(zone_name):
        """Retourne (debounce_frames, reset_seconds) pour la zone donnée.

        Utilise les valeurs configurées dans zones.ini si présentes,
        sinon replie sur les constantes globales.
        """
        zone_cfg = state.alert_manager._zones_flat.get(zone_name, {})
        frames = zone_cfg.get("debounce_frames")
        reset = zone_cfg.get("debounce_reset_seconds")
        return (
            int(frames) if frames is not None else PERSON_DEBOUNCE_FRAMES,
            float(reset) if reset is not None else PERSON_RESET_SECONDS,
        )

    def detection_callback(detection_result):
        nonlocal previous_detection
        # Extraire les valeurs du dictionnaire
        if isinstance(detection_result, dict):
            detections = detection_result.get("detections", [])
            roi = detection_result.get("roi", None)
            x_pad = detection_result.get("x_pad", None)
            y_pad = detection_result.get("y_pad", None)
            is_skipped_frame = detection_result.get("skipped", False)
        else:
            detections = detection_result
            roi = None
            x_pad = None
            y_pad = None
            is_skipped_frame = False

        _iou_overlap = geometry.iou_overlap

        # Stocker les détections dans la structure partagée
        with state.shared_detections_lock:
            # Ajoute la zone à la fin de chaque détection
            zones = state.zones_by_camera.get(cid, [])
            zone_names_list = [zone["name"] for zone in zones]
            detections_with_zone = []
            # Initialiser previous_detection pour chaque zone si besoin
            for zone_name in zone_names_list:
                if zone_name not in previous_detection:
                    previous_detection[zone_name] = False
            # Marquer les zones détectées dans cette frame
            zones_detected = set()  # uniquement les personnes valides (pour le tracking previous_detection)
            forklifts_in_frame = [d for d in detections if d.get("label") == "forklift"]
            for det in detections:
                zone_names = geometry.get_zone_for_detection(det, zones)
                det_with_zone = det.copy()  # Copie le dictionnaire
                det_with_zone["zones"] = zone_names  # Ajoute les zones
                detections_with_zone.append(det_with_zone)
                # Ne compter la zone comme "détectée" que pour les personnes passant le filtre keypoints
                # ET ne chevauchant pas un forklift (même critère que pour déclencher l'alerte)
                if det.get("label") == "person" and state.alert_manager.should_trigger_alert_for_detection(det_with_zone):
                    # Filtre IoU inline (cohérent avec le filtre appliqué lors de l'alerte)
                    overlapping_forklift = any(
                        _iou_overlap(det, f) > 0.15 for f in forklifts_in_frame
                    ) if forklifts_in_frame else False
                    if not overlapping_forklift:
                        for zn in zone_names:
                            zones_detected.add(zn)
            state.shared_detections[cid] = detections_with_zone

            # Debounce : mise à jour des compteurs avec reset temporel par zone.
            now_ts = time.time()
            for zone_name in zone_names_list:
                if zone_name not in person_consecutive_frames:
                    person_consecutive_frames[zone_name] = 0
                if zone_name not in person_last_detect_time:
                    person_last_detect_time[zone_name] = 0.0
                _, reset_secs = _get_zone_debounce(zone_name)
                if zone_name in zones_detected and not is_skipped_frame:
                    person_consecutive_frames[zone_name] += 1
                    person_last_detect_time[zone_name] = now_ts
                elif zone_name not in zones_detected and now_ts - person_last_detect_time[zone_name] > reset_secs:
                    person_consecutive_frames[zone_name] = 0
            # Zones ayant confirmé la présence sur N frames consécutives (seuil par zone)
            debounced_zones = {
                zn for zn in zone_names_list
                if person_consecutive_frames.get(zn, 0) >= _get_zone_debounce(zn)[0]
            }

        with state.shared_motion_roi_lock:
            # Si la méthode motion.py retourne le tuple étendu (x_pad, y_pad, w_pad, h_pad, x, y, w, h)
            # on le stocke dans le dico partagé pour l'affichage vidéo
            if isinstance(x_pad, (tuple, list)) and len(x_pad) == 8:
                x_pad_val, y_pad_val, w_pad, h_pad, x_raw, y_raw, w_raw, h_raw = x_pad
                state.shared_motion_roi[cid] = {
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
                state.shared_motion_roi[cid] = {
                    "x_pad": x_pad if x_pad is not None else 0,
                    "y_pad": y_pad if y_pad is not None else 0,
                    "w": w,
                    "h": h
                }
        now = datetime.now()
        current_timestamp = now.timestamp()

        # ===== HEARTBEAT FAIL-SAFE =====
        failsafe.update_heartbeat()

        # Correction asyncio event loop pour thread
        loop = main_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

        # Pour chaque zone, gérer l'état previous_detection (basé sur les zones debouncées)
        for zone_name in zone_names_list:
            detected = zone_name in debounced_zones
            if detected and not previous_detection[zone_name]:
                previous_detection[zone_name] = True
            elif not detected and previous_detection[zone_name]:
                previous_detection[zone_name] = False
                logger.info(f"Plus de détection sur la caméra {cid} dans la zone {zone_name}")
                asyncio.run_coroutine_threadsafe(
                    state.alert_manager.on_no_more_detection(current_timestamp, zone_names=[zone_name]),
                    loop
                )

        # Filtre IoU : exclure les personnes dont la bbox chevauche significativement
        # un chariot élévateur dans la même frame (pose=[] ou avec keypoints parasites).
        forklifts = [d for d in detections if d.get("label") == "forklift"]
        detections_person = []
        for det in [d for d in detections if d.get("label") == "person"]:
            overlapping = next(
                (f for f in forklifts if _iou_overlap(det, f) > 0.15),
                None
            )
            if overlapping:
                logger.info(
                    f"Personne écartée (IoU/overlap={_iou_overlap(det, overlapping):.2f}"
                    f" > 0.15 avec forklift) — probable même objet"
                )
            else:
                detections_person.append(det)

        # Ajouter les zones aux détections personnes et appliquer le filtrage par stature/zone
        detections_person_with_zone = []
        for det in detections_person:
            zone_names = geometry.get_zone_for_detection(det, zones)
            det_with_zone = det.copy()  # Copie le dictionnaire
            # N'inclure que les zones confirmées par le debounce temporel
            det_with_zone["zones"] = [zn for zn in zone_names if zn in debounced_zones]

            # Vérifier si cette détection doit déclencher une alerte (filtre keypoints)
            if state.alert_manager.should_trigger_alert_for_detection(det_with_zone):
                detections_person_with_zone.append(det_with_zone)

        # Logger une seule fois les zones confirmées qui déclenchent l'alerte
        if detections_person_with_zone:
            for det in detections_person_with_zone:
                pose = det.get("pose")
                visible_kp_log = (
                    sum(1 for kp in pose if len(kp) >= 3 and float(kp[2]) >= 0.40)
                    if pose else "N/A"
                )
                logger.info(
                    f"Alerte déclenchée — zones {det.get('zones', [])}"
                    f" (keypoints visibles : {visible_kp_log})"
                )

        # Déclencher l'alerte seulement si il y a des détections valides après filtrage
        if len(detections_person_with_zone) > 0:
            current_day = now.strftime('%Y-%m-%d %H:%M:%S')
            frame = state.manager.get_frame_array(state.cam_ids[cid])
            # Appliquer les masques sur la frame d'alerte (sauvegarde/Telegram)
            # pour ne pas exposer les zones masquées dans les captures
            if frame is not None:
                cam_masks = state.masks_by_camera.get(cid, [])
                if cam_masks:
                    frame = frame.copy()
                    for _m in cam_masks:
                        _poly = _m.get('polygon')
                        if _poly and len(_poly) >= 3:
                            _pts = np.array(_poly, dtype=np.int32)
                            cv2.fillPoly(frame, [_pts], (0, 0, 0))
            logger.debug(f"Détections caméra {cid} (après filtrage stature/zone) : {detections_person_with_zone}, {current_day}")
            asyncio.run_coroutine_threadsafe(
                state.alert_manager.on_detection(current_timestamp, frame, detections_person_with_zone, cid),
                loop
            )
    return detection_callback
