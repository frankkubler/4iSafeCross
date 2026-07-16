"""API de configuration : zones, masques, positions relais (fichiers INI).

Les POST sauvegardent dans config/*.ini, rechargent l'état en mémoire et
invalident les caches d'affichage concernés (hot-reload sans redémarrage).
"""
import logging

from flask import Blueprint, jsonify, request

from src.core import caches
from src.core.state import state
from utils.constants import (NUM_RELAYS,
                             load_zones_by_camera_from_ini,
                             load_masks_by_camera_from_ini,
                             load_relay_positions_from_ini)
from utils.zone_writer import save_zones_to_ini, save_masks_to_ini, save_relay_positions_to_ini

logger = logging.getLogger(__name__)

zones_api_bp = Blueprint('zones_api', __name__)

ZONES_INI_PATH = 'config/zones.ini'
MASKS_INI_PATH = 'config/masks.ini'
RELAY_POSITIONS_INI_PATH = 'config/relay_positions.ini'

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


@zones_api_bp.route('/set_zones', methods=['POST'])
def set_zones():
    data = request.get_json()
    zones = data.get('zones', [])
    state.alert_manager.set_zones(zones)

    # Vider le cache des overlays car les zones ont changé
    with caches.zone_overlay_lock:
        caches.zone_overlay_cache.clear()
        logger.debug("🗑️ Cache des overlays de zones vidé suite à modification des zones")

    return jsonify({'status': 'ok'})


@zones_api_bp.route('/api/zones/<int:cid>', methods=['GET'])
def get_zones(cid):
    """Retourne les zones polygones de la caméra spécifiée en JSON."""
    zones = state.zones_by_camera.get(cid, [])
    result = []
    for zone in zones:
        if 'polygon' not in zone:
            continue  # Ignorer les zones rect
        result.append({
            'name': zone['name'],
            'polygon': [list(pt) for pt in zone['polygon']],
            'color': list(zone.get('color', (255, 0, 0))),
            'relays': zone.get('relays', []),
            'skip_keypoint_filter': zone.get('skip_keypoint_filter', False),
            'debounce_frames': zone.get('debounce_frames'),
            'debounce_reset_seconds': zone.get('debounce_reset_seconds'),
        })
    return jsonify(result)


@zones_api_bp.route('/api/zones/<int:cid>', methods=['POST'])
def save_zones(cid):
    """Sauvegarde les zones d'une caméra dans zones.ini et recharge."""
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
        state.zones_by_camera = load_zones_by_camera_from_ini(ZONES_INI_PATH)

        # Vider tous les caches
        with caches.zone_overlay_lock:
            caches.zone_overlay_cache.clear()
        with caches.frame_cache_lock:
            caches.frame_cache.clear()
            caches.frame_cache_timestamp.clear()
        caches.zone_color_cache.clear()

        # Mettre à jour l'alert manager avec toutes les zones (toutes caméras)
        state.alert_manager.set_zones(state.zones_by_camera)

        logger.info(f"✅ Zones cam{cid} sauvegardées et rechargées ({len(zones_data)} zones)")
        return jsonify({'status': 'ok', 'zones_count': len(zones_data)})

    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde zones cam{cid}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@zones_api_bp.route('/api/masks/<int:cid>', methods=['GET'])
def get_masks(cid):
    """Retourne les masques polygonaux de la caméra spécifiée en JSON."""
    masks = state.masks_by_camera.get(cid, [])
    result = [
        {'name': m['name'], 'polygon': [list(pt) for pt in m['polygon']]}
        for m in masks
        if 'polygon' in m
    ]
    return jsonify(result)


@zones_api_bp.route('/api/masks/<int:cid>', methods=['POST'])
def save_masks_route(cid):
    """Sauvegarde les masques d'une caméra dans masks.ini et recharge à chaud."""
    data = request.get_json()
    masks_data = data.get('masks', [])

    # Normaliser les noms
    for i, mask in enumerate(masks_data):
        if 'name' not in mask or not mask['name']:
            mask['name'] = f'mask{i + 1}_cam{cid}'

    try:
        save_masks_to_ini(MASKS_INI_PATH, cid, masks_data)
        state.masks_by_camera = load_masks_by_camera_from_ini(MASKS_INI_PATH)

        # Vider le cache masques et le cache frames (affichage + pipeline cohérents)
        with caches.mask_overlay_lock:
            caches.mask_overlay_cache.clear()
        with caches.frame_cache_lock:
            caches.frame_cache.clear()
            caches.frame_cache_timestamp.clear()

        # Hot-reload thread-safe des masques dans chaque thread d'inférence
        if cid in state.inference_threads:
            state.inference_threads[cid].set_masks(state.masks_by_camera.get(cid, []))

        logger.info(f"✅ Masques cam{cid} sauvegardés et rechargés ({len(masks_data)} masque(s))")
        return jsonify({'status': 'ok', 'masks_count': len(masks_data)})

    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde masques cam{cid}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@zones_api_bp.route('/api/relay_positions/<int:cid>', methods=['GET'])
def get_relay_positions(cid):
    """Retourne les positions des icônes de projecteurs pour la caméra spécifiée."""
    positions = state.relay_positions_by_camera.get(cid, {})
    result = {str(relay_id): list(coords) for relay_id, coords in positions.items()}
    return jsonify(result)


@zones_api_bp.route('/api/relay_positions/<int:cid>', methods=['POST'])
def save_relay_positions_route(cid):
    """Sauvegarde les positions des icônes de projecteurs dans relay_positions.ini."""
    data = request.get_json()
    positions_data = data.get('positions', {})
    try:
        # Merger avec les positions existantes (on ne reçoit que les déplacés)
        existing = state.relay_positions_by_camera.get(cid, {})
        merged = {}
        for k, v in existing.items():
            # existing stocke (x, y) tuples — convertir en dict
            if isinstance(v, (list, tuple)):
                merged[str(k)] = {'x': v[0], 'y': v[1]}
            else:
                merged[str(k)] = v
        for rid, pos in positions_data.items():
            merged[str(rid)] = pos
        save_relay_positions_to_ini(RELAY_POSITIONS_INI_PATH, cid, merged)
        state.relay_positions_by_camera = load_relay_positions_from_ini(RELAY_POSITIONS_INI_PATH)
        logger.info(f"✅ Positions relais cam{cid} sauvegardées ({len(positions_data)} entrée(s))")
        return jsonify({'status': 'ok', 'count': len(positions_data)})
    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde positions relais cam{cid}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@zones_api_bp.route('/api/relay-count')
def relay_count():
    """Retourne le nombre de relais physiques disponibles."""
    return jsonify({'count': len(state.relays.relays) or NUM_RELAYS})
