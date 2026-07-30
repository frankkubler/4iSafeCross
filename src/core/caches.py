"""Caches d'affichage : overlays de zones/masques, frames JPEG encodées.

État de module partagé entre le générateur MJPEG (src/core/streaming.py) et
les routes d'invalidation (src/web/routes_system.py, routes_zones_api.py).
Chaque cache a son lock ; les helpers d'invalidation les prennent eux-mêmes.
"""
import logging
import threading
import time

from src.core import geometry
from src.core.state import state

logger = logging.getLogger(__name__)

# Cache pour les couleurs des zones par caméra pour optimisation
zone_color_cache = {}
MAX_ZONE_COLOR_CACHE_SIZE = 20  # Limite pour éviter les fuites mémoire

# Cache pour les overlays des zones par caméra
zone_overlay_cache = {}
zone_overlay_lock = threading.Lock()
MAX_ZONE_OVERLAY_CACHE_SIZE = 10  # Limite pour éviter les fuites mémoire (~6 Mo par entrée)

# Cache et lock pour les overlays de masques (affichage GUI uniquement)
mask_overlay_cache = {}
mask_overlay_lock = threading.Lock()
MAX_MASK_OVERLAY_CACHE_SIZE = 10

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

            zones = state.zones_by_camera.get(cid, [])
            # Initialiser le cache des couleurs de zones pour cette caméra si nécessaire
            if cid not in zone_color_cache:
                zone_color_cache[cid] = {
                    zone["name"]: (c[2], c[1], c[0])  # RGB → BGR pour OpenCV
                    for zone in zones
                    for c in [zone.get("color", (255, 0, 0))]
                }
            zone_overlay_cache[cache_key] = geometry.create_zone_overlay(frame_shape, zones)
            logger.debug(f"🎨 Overlay des zones créé pour caméra {cid} (résolution: {frame_shape[1]}x{frame_shape[0]})")

        return zone_overlay_cache[cache_key]


DEFAULT_ZONE_COLOR = (255, 0, 0)  # BGR


def get_zone_color(cid, zone_name):
    """Couleur BGR d'une zone, avec repli sur DEFAULT_ZONE_COLOR.

    Lecture défensive et sous verrou : zone_color_cache n'est peuplé que lors
    d'un défaut de cache d'overlay, alors que invalidate_zones() le vide en
    entier. Un accès direct par index depuis le générateur MJPEG lèverait donc
    KeyError si une sauvegarde de zones s'intercale — ce qui tuait le générateur
    et laissait le flux de la caméra figé jusqu'à reconnexion du navigateur.
    """
    with zone_overlay_lock:
        return zone_color_cache.get(cid, {}).get(zone_name, DEFAULT_ZONE_COLOR)


def invalidate_zones():
    """Invalide les deux caches dérivés de la géométrie des zones.

    Overlays et couleurs sont construits ensemble par get_zone_overlay() ; les
    vider séparément laisse l'un des deux périmé. Renvoie le nombre d'overlays
    supprimés (pour le retour des routes d'invalidation).
    """
    with zone_overlay_lock:
        cleared = len(zone_overlay_cache)
        zone_overlay_cache.clear()
        zone_color_cache.clear()
    return cleared


def get_mask_overlay(frame_shape, cid):
    """Récupère le masque booléen depuis le cache ou le crée si nécessaire."""
    with mask_overlay_lock:
        cache_key = f"{cid}_{frame_shape[0]}_{frame_shape[1]}"
        if cache_key not in mask_overlay_cache:
            if len(mask_overlay_cache) >= MAX_MASK_OVERLAY_CACHE_SIZE:
                oldest_key = next(iter(mask_overlay_cache))
                del mask_overlay_cache[oldest_key]
            masks = state.masks_by_camera.get(cid, [])
            mask_overlay_cache[cache_key] = geometry.create_mask_overlay(frame_shape, masks)
            logger.debug(f"⬛ Overlay masque créé pour caméra {cid} ({len(masks)} masque(s))")
        return mask_overlay_cache[cache_key]


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
