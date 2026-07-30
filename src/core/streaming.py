"""Générateur MJPEG pour les flux vidéo web (/video_feed/<cid>).

Dessine ROI, overlays de zones, masques GUI et détections sur la frame brute,
avec copie paresseuse et cache de frames encodées (src/core/caches.py).
"""
import logging
import time

import cv2
import numpy as np

from src.core import caches
from src.core.state import state
from utils.constants import OBJECT_COLORS

logger = logging.getLogger(__name__)


def gen_frames(cid):
    cam_id = state.cam_ids[cid]
    last_frame_time = 0
    frame_interval = 0.2  # 5 FPS = 200ms entre frames
    logger.debug(f"🎬 Nouveau générateur de frames démarré pour caméra {cid}")

    while True:
        current_time = time.time()

        # On ne génère les frames que pour l'affichage vidéo
        if not state.stream_enabled.get(cid, True):
            # On attend que le stream soit réactivé, sans bloquer la détection
            logger.debug(f"⏸️  Stream désactivé pour caméra {cid}")
            time.sleep(0.2)
            continue

        # Limiter la fréquence de génération des frames pour l'affichage
        if current_time - last_frame_time < frame_interval:
            time.sleep(0.01)
            continue

        # Vérifier le cache de frame
        with caches.frame_cache_lock:
            cached_frame = caches.frame_cache.get(cid)
            cache_time = caches.frame_cache_timestamp.get(cid, 0)

        # Utiliser le cache si la frame est récente
        if cached_frame is not None and current_time - cache_time < caches.FRAME_CACHE_DURATION:
            caches.cache_performance_stats['hits'] += 1
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + cached_frame + b'\r\n')
            last_frame_time = current_time
            continue

        frame = state.manager.get_frame_array(cam_id)
        if frame is not None:
            caches.cache_performance_stats['misses'] += 1
            generation_start_time = time.time()

            # Vérifier que la frame est valide (pas de copie systématique, voir _ensure_writable)
            try:
                h, w = frame.shape[:2]
            except Exception as e:
                logger.error(f"❌ Erreur lors de la lecture de frame pour caméra {cid}: {e}")
                time.sleep(0.1)
                continue

            # 🚀 Copie paresseuse : la frame n'est dupliquée qu'à la première
            # écriture réelle (ROI, overlay masque debug, zones, masques GUI,
            # détections, point de mouvement). Sans aucune de ces écritures,
            # aucune copie n'est faite — gain CPU/mémoire notable quand
            # aucune zone/masque/détection n'est active.
            frame_dirty = False

            def _ensure_writable():
                nonlocal frame, frame_dirty
                if not frame_dirty:
                    frame = frame.copy()
                    frame_dirty = True

            with state.shared_detections_lock:
                detections = state.shared_detections.get(cid, [])
            with state.shared_motion_roi_lock:
                roi_info = state.shared_motion_roi.get(cid, None)
            # Afficher les ROI seulement si activé
            if state.roi_display_enabled.get(cid, False) and roi_info and roi_info.get("w_pad", 0) > 0 and roi_info.get("h_pad", 0) > 0:
                _ensure_writable()
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
            # Overlay debug du masque de mouvement (semi-transparent vert)
            if state.mask_overlay_enabled.get(cid, False) and cid in state.inference_threads:
                detector = getattr(state.inference_threads[cid], 'motion_detector', None)
                if detector is not None and detector._last_mask is not None:
                    _ensure_writable()
                    dbg_mask = detector._last_mask
                    if dbg_mask.shape[:2] != (h, w):
                        dbg_mask = cv2.resize(dbg_mask, (w, h), interpolation=cv2.INTER_NEAREST)
                    green_overlay = np.zeros_like(frame)
                    green_overlay[dbg_mask > 0] = (0, 200, 0)
                    frame = cv2.addWeighted(frame, 1.0, green_overlay, 0.45, 0)
            # Superposer l'overlay des zones (créé une seule fois)
            zone_overlay = caches.get_zone_overlay(frame.shape, cid)
            # Créer un masque pour ne dessiner que les pixels non-noirs de l'overlay
            zone_mask = np.any(zone_overlay > 0, axis=2)
            if np.any(zone_mask):
                _ensure_writable()
                frame[zone_mask] = zone_overlay[zone_mask]
            # Appliquer les masques noirs sur la GUI (zones exclues de la détection)
            mask_bool = caches.get_mask_overlay(frame.shape, cid)
            if np.any(mask_bool):
                _ensure_writable()
                frame[mask_bool] = 0
            # Récupérer l'état du mouvement depuis le thread d'inférence
            motion = False
            if cid in state.inference_threads:
                motion = state.inference_threads[cid].motion
            for det in detections:
                _ensure_writable()
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
                label = f'{confidence:.2f} {label} '
                cv2.putText(frame, label, (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_bgr, 2)
                # Afficher la zone sur la détection
                if zone_names:
                    for i, zone_name in enumerate(zone_names):
                        # Utiliser le cache pour la couleur de la zone
                        color = caches.get_zone_color(cid, zone_name)
                        cv2.putText(frame, zone_name, (x1, y2 + 20 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            # Ajout du point vert si mouvement détecté
            if motion:
                _ensure_writable()
                # En haut à droite
                cv2.circle(frame, (w - 20, 20), 15, (0, 0, 255), -1)
            # Encodage JPEG optimisé pour réduire la latence
            target_w = state.stream_display_width.get(cid, 854)
            h_frame, w_frame = frame.shape[:2]
            if w_frame != target_w:
                target_h = int(h_frame * target_w / w_frame)
                frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, caches.FRAME_QUALITY_OPTIMIZED])
            if ret:
                frame_bytes = buffer.tobytes()
                generation_time_ms = (time.time() - generation_start_time) * 1000
                caches.cache_performance_stats['total_generation_time'] += generation_time_ms

                # Mettre en cache la frame encodée
                with caches.frame_cache_lock:
                    caches.frame_cache[cid] = frame_bytes
                    caches.frame_cache_timestamp[cid] = current_time
                    cache_size = len(caches.frame_cache)

                avg_generation_time = caches.cache_performance_stats['total_generation_time'] / caches.cache_performance_stats['misses']
                hit_rate = caches.cache_performance_stats['hits'] / (caches.cache_performance_stats['hits'] + caches.cache_performance_stats['misses']) * 100

                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                last_frame_time = current_time
            else:
                logger.error(f"❌ Erreur encodage JPEG pour caméra {cid}")
                break
        else:
            logger.debug(f"⏳ Pas de frame disponible pour caméra {cid}")
            time.sleep(0.1)  # Attendre si pas de frame disponible
