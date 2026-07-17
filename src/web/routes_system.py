"""Supervision système : fail-safe, ressources, caches, galerie de détections."""
import glob
import logging
import os
import re
import time

import psutil
from flask import Blueprint, jsonify, request, send_from_directory

from src.core import caches, failsafe
from src.core.state import state
from src.core.gpu_metrics import get_gpu_metrics
from src.core.system_metrics import get_resource_metrics
from src.web.app_factory import PROJECT_ROOT
from utils.utils import get_non_local_ips, get_docker_info, get_service_status

logger = logging.getLogger(__name__)

system_bp = Blueprint('system', __name__)

# Chemin absolu : send_from_directory résout les chemins relatifs contre le
# root_path Flask (désormais src/web/), pas contre la racine projet.
DETECTIONS_DIR = str(PROJECT_ROOT / 'detections')


@system_bp.route('/failsafe_status')
def failsafe_status():
    """Endpoint pour vérifier l'état du système fail-safe."""
    with state.heartbeat_lock:
        time_since_heartbeat = time.time() - state.last_heartbeat

    relay_states = {}
    for i in range(len(state.relays.relays)):
        relay_states[f"relay_{i}"] = state.relays.get_relay_state(i)

    return jsonify({
        'application_healthy': state.application_healthy,
        'last_heartbeat_seconds_ago': round(time_since_heartbeat, 2),
        'heartbeat_timeout': failsafe.HEARTBEAT_TIMEOUT,
        'failsafe_mode': 'ACTIVE' if not state.application_healthy else 'STANDBY',
        'relay_states': relay_states,
        'relays_initialized': state.relays.is_initialized,
        'message': 'Système opérationnel' if state.application_healthy else '⚠️  MODE FAIL-SAFE ACTIF - Alertes maintenues ON'
    })


@system_bp.route('/debug_info')
def debug_info():
    # Métriques CPU/mémoire app + conteneur + hôte (non bloquant).
    metrics = get_resource_metrics()
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

    payload = {
        # Champs hôte historiques conservés (rétro-compat du contrat JSON).
        'ram_used': metrics.get('host_ram_used_mb'),
        'ram_total': metrics.get('host_ram_total_mb'),
        'cpu_percent': metrics.get('host_cpu_percent'),
        'disk_used': round(disk.used / 1024 / 1024 / 1024, 2),
        'disk_total': round(disk.total / 1024 / 1024 / 1024, 2),
        'disk_percent': disk.percent,
        'ip': ip_str,
        'docker_info': docker_info,
        'service_status': service_status,
        'load_avg': f"{load1} / {load5} / {load15}",
    }
    # Nouveaux champs : empreinte de l'application et du conteneur.
    payload.update(metrics)
    # Charge GPU (Jetson/AMD/Intel), None si aucun GPU détecté.
    payload['gpu'] = get_gpu_metrics()
    return jsonify(payload)


@system_bp.route('/detections_thumbs')
def detections_thumbs():
    """Retourne les 10 dernières captures avec métadonnées (caméra, date/heure)."""
    try:
        files = glob.glob(os.path.join(DETECTIONS_DIR, '*.jpg'))
        files.sort(key=os.path.getctime, reverse=True)
        result = []
        for f in files[:20]:
            filename = os.path.basename(f)
            cam_id = None
            display_date = None
            m = re.match(r'cam_(\w+)_(\d{8})_(\d{6})', filename)
            if m:
                cam_id = m.group(1)
                d, t = m.group(2), m.group(3)
                display_date = f"{d[6:8]}/{d[4:6]}/{d[0:4]} à {t[0:2]}:{t[2:4]}:{t[4:6]}"
            result.append({'filename': filename, 'cam_id': cam_id, 'display_date': display_date})
        return jsonify({'images': result})
    except Exception as e:
        return jsonify({'images': [], 'error': str(e)})


@system_bp.route('/detections/<filename>')
def serve_detection_image(filename):
    # Sert une image du dossier detections
    return send_from_directory(DETECTIONS_DIR, filename)


@system_bp.route('/cache_stats')
def cache_stats():
    """Endpoint pour obtenir les statistiques du cache de frames"""
    current_time = time.time()
    with caches.frame_cache_lock:
        cache_info = {}
        total_size = 0
        expired_count = 0

        for cam_id, frame_data in caches.frame_cache.items():
            timestamp = caches.frame_cache_timestamp.get(cam_id, 0)
            age_ms = (current_time - timestamp) * 1000
            size_bytes = len(frame_data)
            total_size += size_bytes
            is_fresh = age_ms < caches.FRAME_CACHE_DURATION * 1000

            if not is_fresh:
                expired_count += 1

            cache_info[cam_id] = {
                'age_ms': round(age_ms, 1),
                'size_bytes': size_bytes,
                'size_kb': round(size_bytes / 1024, 1),
                'is_fresh': is_fresh,
                'expired': age_ms > caches.FRAME_CACHE_DURATION * 1000
            }

        # Calculer les statistiques de performance
        total_requests = caches.cache_performance_stats['hits'] + caches.cache_performance_stats['misses']
        hit_rate = (caches.cache_performance_stats['hits'] / max(total_requests, 1)) * 100
        avg_generation_time = caches.cache_performance_stats['total_generation_time'] / max(caches.cache_performance_stats['misses'], 1)

        stats = {
            'cache_duration_ms': caches.FRAME_CACHE_DURATION * 1000,
            'frame_quality': caches.FRAME_QUALITY_OPTIMIZED,
            'total_entries': len(caches.frame_cache),
            'expired_entries': expired_count,
            'total_size_bytes': total_size,
            'total_size_kb': round(total_size / 1024, 1),
            'hit_rate_percent': round(hit_rate, 1),
            'average_generation_time_ms': round(avg_generation_time, 1),
            'total_requests': total_requests,
            'cameras': cache_info
        }

    return jsonify(stats)


@system_bp.route('/api/inference/stats')
def inference_stats():
    """Endpoint pour obtenir les statistiques d'optimisation de l'inférence."""
    stats = {}

    # Récupérer les stats de tous les threads d'inférence actifs
    for cid, inference_thread in state.inference_threads.items():
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


@system_bp.route('/clear_frame_cache', methods=['POST'])
def clear_frame_cache():
    """Force le nettoyage du cache de frames"""
    with caches.frame_cache_lock:
        cache_size = len(caches.frame_cache)
        caches.frame_cache.clear()
        caches.frame_cache_timestamp.clear()
        logger.debug(f"🗑️ Cache de frames vidé manuellement ({cache_size} entrées supprimées)")

    return jsonify({'status': 'ok', 'cleared_entries': cache_size})


@system_bp.route('/clear_zone_cache', methods=['POST'])
def clear_zone_cache():
    """Vide le cache des overlays de zones"""
    with caches.zone_overlay_lock:
        cache_size = len(caches.zone_overlay_cache)
        caches.zone_overlay_cache.clear()
        logger.debug(f"🗑️ Cache des overlays de zones vidé manuellement ({cache_size} entrées supprimées)")

    return jsonify({'status': 'ok', 'cleared_entries': cache_size})


@system_bp.route('/shutdown')
def shutdown():
    state.manager.release()
    return "Cameras released"


@system_bp.route('/quit', methods=['POST'])
def quit_server():
    state.manager.release()
    func = request.environ.get('werkzeug.server.shutdown')
    if func is not None:
        func()
    else:
        os._exit(0)
    return 'Serveur arrêté.'
