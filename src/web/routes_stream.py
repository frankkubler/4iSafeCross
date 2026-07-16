"""Flux vidéo : MJPEG, snapshots, statut caméra et réglages d'affichage."""
import logging

from flask import Blueprint, Response, jsonify, request

from src.core import caches
from src.core.state import state
from src.core.streaming import gen_frames

logger = logging.getLogger(__name__)

stream_bp = Blueprint('stream', __name__)


@stream_bp.route('/video_feed/<int:cid>')
def video_feed(cid):
    return Response(gen_frames(cid),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@stream_bp.route('/snapshot/<int:cid>')
def snapshot(cid):
    """Retourne un snapshot JPEG de la caméra spécifiée."""
    if cid < 0 or cid >= len(state.cam_ids):
        return jsonify({'error': 'Caméra inconnue'}), 404
    frame_bytes = state.manager.get_frame(state.cam_ids[cid])
    if frame_bytes is None:
        return jsonify({'error': 'Caméra hors ligne'}), 503
    return Response(frame_bytes, mimetype='image/jpeg')


@stream_bp.route('/cam_status/<int:cid>')
def cam_status(cid):
    return jsonify({'status': state.manager.get_status(state.cam_ids[cid])})


@stream_bp.route('/toggle_stream/<int:cid>', methods=['POST'])
def toggle_stream(cid):
    data = request.get_json()
    enabled = data.get('enabled', True)
    state.stream_enabled[cid] = enabled
    return jsonify({'status': 'ok', 'enabled': enabled})


@stream_bp.route('/switch_resolution/<int:cid>', methods=['POST'])
def switch_resolution(cid):
    current = state.stream_display_width.get(cid, 854)
    new_width = 1280 if current == 854 else 854
    state.stream_display_width[cid] = new_width
    # Invalider le cache de frame pour forcer la régénération à la nouvelle taille
    with caches.frame_cache_lock:
        caches.frame_cache.pop(cid, None)
        caches.frame_cache_timestamp.pop(cid, None)
    mode = '720p' if new_width == 1280 else '480p'
    logger.info(f"🖥️ Résolution stream caméra {cid} → {new_width}px ({mode})")
    return jsonify({'status': 'ok', 'mode': mode, 'width': new_width})


# Exemple de contrôle caméra (exposition, gain, etc.)
@stream_bp.route('/set_control/<int:cid>', methods=['POST'])
def set_control(cid):
    control = request.json.get('control')
    value = request.json.get('value')
    cam = state.manager.cams.get(cid)
    if cam is not None:
        # Exemple : changer la luminosité
        if control == "brightness":
            cam.set(10, float(value))  # 10 = cv2.CAP_PROP_BRIGHTNESS
        elif control == "exposure":
            cam.set(15, float(value))  # 15 = cv2.CAP_PROP_EXPOSURE
        # Ajoute d'autres contrôles ici
        return jsonify({"status": "ok"})
    return jsonify({"status": "error"}), 404
