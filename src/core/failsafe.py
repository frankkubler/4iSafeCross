"""Mécanismes fail-safe : heartbeat global et par caméra, watchdog, extinction post-démarrage.

Le principe (voir docs/features/failsafe-mode.md) : les relais sont allumés au
démarrage et le restent tant que l'application n'a pas prouvé qu'elle est
opérationnelle (heartbeat émis par le pipeline de détection).

Deux niveaux :
- **global** — aucun heartbeat depuis HEARTBEAT_TIMEOUT : tous les relais sont
  forcés ON (crash, thread bloqué, perte de toutes les caméras) ;
- **par caméra** — une caméra n'a plus émis de heartbeat depuis HEARTBEAT_TIMEOUT
  alors que d'autres fonctionnent : seuls les relais des zones de CETTE caméra
  sont forcés ON. Sans cela, la perte d'une caméra parmi plusieurs laissait ses
  zones sans surveillance et ses relais éteints.

Tout forçage passe par AlerteManager (force_relays_on / release_forced_relays)
pour que son état interne (relay_on, relay_on_time) reste cohérent avec l'état
physique : c'est ce qui permet l'extinction différée normale au retour du flux.
"""
import asyncio
import logging
import threading
import time

from src.core.state import state
from utils.constants import STARTUP_GRACE_PERIOD

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT = 30  # Si pas de heartbeat pendant 30s, considérer comme dysfonctionnel
WATCHDOG_PERIOD = 5     # Période de vérification du watchdog (s)


def update_heartbeat(cid=None):
    """Appelé par le callback de détection de chaque caméra (index `cid`)."""
    now = time.time()
    with state.heartbeat_lock:
        state.last_heartbeat = now
        state.application_healthy = True
        state.heartbeat_received = True
        if cid is not None:
            state.last_heartbeat_by_cam[cid] = now


def heartbeat_received():
    with state.heartbeat_lock:
        return state.heartbeat_received


def relays_for_camera(cid):
    """Relais associés aux zones de la caméra d'index `cid` (ensemble d'entiers)."""
    relays = set()
    for zone in state.zones_by_camera.get(cid, []):
        relays.update(state.alert_manager._get_relay_nums_from_zone(zone["name"]))
    return relays


def _schedule(coro):
    """Exécute une coroutine d'AlerteManager depuis un thread (boucle asyncio principale)."""
    return asyncio.run_coroutine_threadsafe(coro, state.main_loop)


def check_failsafe(now):
    """Une itération du watchdog. Pure vis-à-vis du temps (`now` injecté) : testable.

    Retourne la liste des actions effectuées, sous forme de tuples
    ('global_on' | 'global_release' | 'camera_on' | 'camera_release', détail).
    """
    actions = []
    with state.heartbeat_lock:
        since_global = now - state.last_heartbeat
        was_healthy = state.application_healthy
        cam_last = {idx: state.last_heartbeat_by_cam.get(idx, state.boot_time)
                    for idx in range(len(state.cam_ids))}
        cam_failsafe = dict(state.camera_failsafe)

    # ── Niveau global ────────────────────────────────────────────────────────
    all_relays = list(range(len(state.relays.relays)))
    if since_global > HEARTBEAT_TIMEOUT:
        if was_healthy:
            with state.heartbeat_lock:
                state.application_healthy = False
            logger.error(f"⚠️  ALERTE FAIL-SAFE : aucun heartbeat depuis {since_global:.1f}s - tous les relais forcés ON")
            state.alert_manager.force_relays_on(all_relays, reason=f"heartbeat global absent depuis {since_global:.0f}s")
            actions.append(('global_on', all_relays))
    elif not was_healthy:
        with state.heartbeat_lock:
            state.application_healthy = True
        logger.info("✅ Application de nouveau opérationnelle (heartbeat reçu) - extinction différée des relais sans détection")
        _schedule(state.alert_manager.release_forced_relays(all_relays, reason="retour du heartbeat global"))
        actions.append(('global_release', all_relays))

    # ── Niveau caméra ────────────────────────────────────────────────────────
    for idx, last in cam_last.items():
        silent = (now - last) > HEARTBEAT_TIMEOUT
        was = cam_failsafe.get(idx, False)
        if silent and not was:
            relays = sorted(relays_for_camera(idx))
            with state.heartbeat_lock:
                state.camera_failsafe[idx] = True
            logger.error(
                f"⚠️  FAIL-SAFE caméra {idx} : aucune image depuis {now - last:.0f}s - "
                f"relais {relays} forcés ON (zones de cette caméra)"
            )
            state.alert_manager.force_relays_on(relays, reason=f"caméra {idx} silencieuse depuis {now - last:.0f}s")
            actions.append(('camera_on', (idx, relays)))
        elif not silent and was:
            relays = sorted(relays_for_camera(idx))
            with state.heartbeat_lock:
                state.camera_failsafe[idx] = False
            logger.info(f"✅ Caméra {idx} de nouveau active - relais {relays} relâchés (extinction différée si aucune détection)")
            _schedule(state.alert_manager.release_forced_relays(relays, reason=f"retour de la caméra {idx}"))
            actions.append(('camera_release', (idx, relays)))
    return actions


def failsafe_watchdog():
    """Thread surveillant la santé de l'application via heartbeat (global et par caméra)."""
    logger.info("🔒 Watchdog fail-safe démarré - Surveillance active (globale + par caméra)")
    while True:
        time.sleep(WATCHDOG_PERIOD)
        try:
            check_failsafe(time.time())
        except Exception as e:  # le watchdog ne doit jamais mourir
            logger.exception(f"Erreur dans le watchdog fail-safe : {e}")


def start_failsafe_watchdog():
    """Démarre le thread watchdog fail-safe (daemon)."""
    threading.Thread(target=failsafe_watchdog, daemon=True).start()


def startup_relay_off():
    """Éteint les relais après une période de grâce au démarrage si aucune détection n'a eu lieu.

    Le fail-safe allume tous les relais au démarrage. Ce thread attend que la détection soit
    opérationnelle, puis demande l'extinction si aucune zone n'est active.
    La logique interne de _delayed_off_relay (11s + vérification relay_active_zones) protège
    contre l'extinction si une personne est bien détectée pendant la période de grâce.

    L'extinction initiale est CONDITIONNÉE à la réception d'au moins un heartbeat : sans
    image caméra, les relais restent ON. Avant ce garde-fou, un démarrage sans caméra
    éteignait les relais à t≈15 s et le watchdog ne les rallumait qu'à t≈30–35 s.

    Les relais non associés à une zone (ex : relais 3 et 4 si zones.ini ne les couvre pas)
    sont également éteints directement après la période de grâce + 11s de sécurité.
    """
    logger.info(f"⏳ Période de grâce fail-safe : {STARTUP_GRACE_PERIOD}s avant extinction initiale des relais")
    time.sleep(STARTUP_GRACE_PERIOD)
    if not heartbeat_received():
        logger.warning(
            "🔒 Aucun heartbeat depuis le démarrage (pas d'image caméra) : extinction initiale "
            "reportée, relais maintenus ON (fail-safe)"
        )
        while not heartbeat_received():
            time.sleep(2)
        logger.info(f"✅ Premier heartbeat reçu - nouvelle période de grâce de {STARTUP_GRACE_PERIOD}s avant extinction initiale")
        time.sleep(STARTUP_GRACE_PERIOD)
    logger.info("🔓 Période de grâce écoulée — extinction des relais si aucune détection active")
    # Extinction des relais gérés par les zones (via _delayed_off_relay avec vérification active)
    _schedule(state.alert_manager.on_no_more_detection(time.time()))
    # Extinction explicite des relais physiques non couverts par les zones (ex : relais 3, 4…)
    managed_relays = set(state.alert_manager.relay_on.keys())
    for i in range(len(state.relays.relays)):
        if i not in managed_relays and state.relays.get_relay_state(i):
            logger.info(f"🔧 Extinction du relais {i} (non géré par les zones) après période de grâce")
            state.relays.action_off(i)


def start_startup_relay_off():
    """Démarre le thread d'extinction post-démarrage (daemon)."""
    threading.Thread(target=startup_relay_off, daemon=True).start()
