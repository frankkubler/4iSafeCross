"""Contrôles de détection : paramètres motion, threads d'inférence, alertes."""
import logging
import threading

from flask import Blueprint, jsonify, request

from src.core.detection_pipeline import detection_callback_factory, get_frame_func_factory
from src.core.state import state
from src.inference import InferenceServerThread

logger = logging.getLogger(__name__)

detection_bp = Blueprint('detection', __name__)


# --- Route pour modifier dynamiquement les paramètres motion ---
@detection_bp.route('/set_motion_param/<int:cid>', methods=['POST'])
def set_motion_param(cid):
    data = request.json
    param = data.get('param')
    value = data.get('value')

    if cid not in state.inference_threads:
        return jsonify({'status': 'error', 'message': 'Caméra inconnue'}), 400

    # Traitez le paramètre spécial pour le thread
    if param == 'white_pixels_threshold':
        try:
            state.inference_threads[cid].white_pixels_threshold = int(value)
            return jsonify({'status': 'ok'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400

    detector = getattr(state.inference_threads[cid], 'motion_detector', None)
    if detector is None:
        return jsonify({'status': 'error', 'message': 'MotionDetector non trouvé'}), 400

    try:
        # Conversion typée
        if param in ('padding', 'min_area', 'varThreshold', 'history',
                     'motion_on_frames', 'motion_off_frames', 'min_single_contour'):
            value = int(value)
        if param in ('detectShadows', 'gaussian_blur', 'aspect_filter'):
            value = value in (True, 'true', 'True', 1, '1', 'on')

        # Mapping des noms API → attributs MotionDetector
        PARAM_TO_ATTR = {
            'min_area': 'min_contour_area',
            'gaussian_blur': 'use_gaussian_blur',
            'aspect_filter': 'use_aspect_filter',
        }
        attr_name = PARAM_TO_ATTR.get(param, param)

        # Mise à jour simple pour les champs non MOG2
        if param not in ('varThreshold', 'history', 'detectShadows'):
            if hasattr(detector, attr_name):
                setattr(detector, attr_name, value)
            else:
                return jsonify({'status': 'error', 'message': f'Paramètre {param} inconnu'}), 400

        # Mise à jour via la méthode dédiée pour MOG2
        if param in ('varThreshold', 'history', 'detectShadows'):
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


@detection_bp.route('/toggle_detection/<int:cid>', methods=['POST'])
def toggle_detection(cid):
    data = request.get_json()
    enabled = data.get('enabled', False)
    state.detection_enabled[cid] = enabled
    if enabled:
        if cid not in state.inference_threads or not state.inference_threads[cid].is_alive():
            stop_event = threading.Event()
            state.inference_stop_events[cid] = stop_event
            thread = InferenceServerThread(
                home_dir=".",
                get_frame_func=get_frame_func_factory(cid),
                detection_callback=detection_callback_factory(cid, state.main_loop),
                stop_event=stop_event,
                masks=state.masks_by_camera.get(cid, [])
            )
            thread.start()
            state.inference_threads[cid] = thread
    else:
        if cid in state.inference_stop_events:
            state.inference_stop_events[cid].set()
        # Nettoyer les détections affichées
        with state.shared_detections_lock:
            state.shared_detections[cid] = []
    return jsonify({'status': 'ok', 'enabled': enabled})


@detection_bp.route('/toggle_roi_display/<int:cid>', methods=['POST'])
def toggle_roi_display(cid):
    data = request.get_json()
    enabled = data.get('enabled', False)
    state.roi_display_enabled[cid] = enabled
    return jsonify({'status': 'ok', 'enabled': enabled})


@detection_bp.route('/toggle_mask_overlay/<int:cid>', methods=['POST'])
def toggle_mask_overlay(cid):
    data = request.get_json()
    enabled = data.get('enabled', False)
    state.mask_overlay_enabled[cid] = enabled
    return jsonify({'status': 'ok', 'enabled': enabled})


@detection_bp.route('/switch_inference_mode/<int:cid>', methods=['POST'])
def switch_inference_mode(cid):
    if cid in state.inference_threads:
        state.inference_threads[cid].switch_inference_mode()
        return jsonify({'status': 'ok', 'mode': state.inference_threads[cid].inference_mode})
    return jsonify({'status': 'error', 'message': 'Caméra inconnue'}), 400


@detection_bp.route('/toggle_telegram_alert', methods=['POST'])
def toggle_telegram_alert():
    data = request.get_json()
    state.telegram_alert_enabled = bool(data.get('enabled', True))
    if hasattr(state.alert_manager, 'set_telegram_alert_enabled'):
        state.alert_manager.set_telegram_alert_enabled(state.telegram_alert_enabled)
    return jsonify({'status': 'ok', 'enabled': state.telegram_alert_enabled})
