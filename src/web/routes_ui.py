"""Pages HTML : tableau de bord et éditeur de zones."""
from flask import Blueprint, render_template

from src.camera_manager import redact_rtsp_url
from src.core.state import state
from utils.constants import (MOTIONTHRESHOLD, APP_NAME, APP_VERSION, OBJECT_COLORS,
                             NUM_RELAYS,
                             FGBG_HISTORY, FGBG_VAR_THRESHOLD, FGBG_DETECT_SHADOWS,
                             MOTION_ON_FRAMES, MOTION_OFF_FRAMES,
                             MOTION_GAUSSIAN_BLUR, MOTION_ASPECT_FILTER,
                             MOTION_MIN_SINGLE_CONTOUR)

ui_bp = Blueprint('ui', __name__)


@ui_bp.route('/')
def index():
    # Préparer une liste de dicts avec l'id et le seuil de chaque caméra
    cam_infos = []
    for idx, cam_id in enumerate(state.cam_ids):
        threshold = MOTIONTHRESHOLD  # valeur par défaut
        var_threshold = FGBG_VAR_THRESHOLD
        history = FGBG_HISTORY
        detect_shadows = FGBG_DETECT_SHADOWS
        padding = 40
        min_area = 30
        motion_on_frames = MOTION_ON_FRAMES
        motion_off_frames = MOTION_OFF_FRAMES
        gaussian_blur = MOTION_GAUSSIAN_BLUR
        aspect_filter = MOTION_ASPECT_FILTER
        min_single_contour = MOTION_MIN_SINGLE_CONTOUR
        if idx in state.inference_threads:
            threshold = getattr(state.inference_threads[idx], 'white_pixels_threshold', MOTIONTHRESHOLD)
            detector = getattr(state.inference_threads[idx], 'motion_detector', None)
            if detector is not None:
                var_threshold = getattr(detector, 'varThreshold', FGBG_VAR_THRESHOLD)
                history = getattr(detector, 'history', FGBG_HISTORY)
                detect_shadows = getattr(detector, 'detectShadows', FGBG_DETECT_SHADOWS)
                padding = getattr(detector, 'padding', 40)
                min_area = getattr(detector, 'min_contour_area', 30)
                motion_on_frames = getattr(detector, 'motion_on_frames', MOTION_ON_FRAMES)
                motion_off_frames = getattr(detector, 'motion_off_frames', MOTION_OFF_FRAMES)
                gaussian_blur = getattr(detector, 'use_gaussian_blur', MOTION_GAUSSIAN_BLUR)
                aspect_filter = getattr(detector, 'use_aspect_filter', MOTION_ASPECT_FILTER)
                min_single_contour = getattr(detector, 'min_single_contour', MOTION_MIN_SINGLE_CONTOUR)
        cam_infos.append({
            # URL rédigée : le template n'utilise que 'idx', et cette page est
            # servie sans authentification tant que SAFECROSS_AUTH_* n'est pas défini.
            'id': redact_rtsp_url(cam_id),
            'idx': idx,
            'white_pixels_threshold': threshold,
            'varThreshold': var_threshold,
            'history': history,
            'detectShadows': detect_shadows,
            'padding': padding,
            'min_area': min_area,
            'motion_on_frames': motion_on_frames,
            'motion_off_frames': motion_off_frames,
            'gaussian_blur': gaussian_blur,
            'aspect_filter': aspect_filter,
            'min_single_contour': min_single_contour,
            'roi_display_enabled': state.roi_display_enabled.get(idx, False),
            'mask_overlay_enabled': state.mask_overlay_enabled.get(idx, False)
        })
    return render_template('index.html', cam_infos=cam_infos, app_name=APP_NAME, app_version=APP_VERSION, telegram_alert_enabled=state.telegram_alert_enabled, stature_colors=OBJECT_COLORS)


@ui_bp.route('/zone_editor/<int:cid>')
def zone_editor(cid):
    """Page d'édition visuelle des zones pour une caméra."""
    if cid < 0 or cid >= len(state.cam_ids):
        return "Caméra inconnue", 404
    cam_name = f"Camera {cid + 1}"
    return render_template(
        'zone_editor.html',
        cid=cid,
        cam_name=cam_name,
        app_name=APP_NAME,
        app_version=APP_VERSION,
        num_relays=len(state.relays.relays) or NUM_RELAYS,
    )
