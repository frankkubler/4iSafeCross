"""Mécanismes fail-safe : heartbeat, watchdog, extinction post-démarrage.

Le principe (voir docs/features/failsafe-mode.md) : les relais sont allumés au
démarrage et le restent tant que l'application n'a pas prouvé qu'elle est
opérationnelle (heartbeat émis par le pipeline de détection).
"""
import asyncio
import logging
import threading
import time

from src.core.state import state
from utils.constants import STARTUP_GRACE_PERIOD

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT = 30  # Si pas de heartbeat pendant 30s, considérer comme dysfonctionnel


def update_heartbeat():
    """Appelé régulièrement pour indiquer que l'application fonctionne correctement."""
    with state.heartbeat_lock:
        state.last_heartbeat = time.time()
        state.application_healthy = True


def failsafe_watchdog():
    """Thread surveillant la santé de l'application via heartbeat.
    Si aucun heartbeat reçu pendant HEARTBEAT_TIMEOUT secondes, active le mode fail-safe."""
    logger.info("🔒 Watchdog fail-safe démarré - Surveillance active")

    while True:
        time.sleep(5)  # Vérification toutes les 5 secondes

        with state.heartbeat_lock:
            time_since_heartbeat = time.time() - state.last_heartbeat

            if time_since_heartbeat > HEARTBEAT_TIMEOUT:
                if state.application_healthy:
                    state.application_healthy = False
                    logger.error(f"⚠️  ALERTE FAIL-SAFE : Aucun heartbeat depuis {time_since_heartbeat:.1f}s - Maintien des relais ON")
                    # S'assurer que tous les relais sont ON
                    for i in range(len(state.relays.relays)):
                        if not state.relays.get_relay_state(i):
                            logger.warning(f"🔧 Réactivation du relais {i} en mode fail-safe")
                            state.relays.action_on(i)
            else:
                if not state.application_healthy:
                    state.application_healthy = True
                    logger.info(f"✅ Application de nouveau opérationnelle (heartbeat reçu)")


def start_failsafe_watchdog():
    """Démarre le thread watchdog fail-safe (daemon)."""
    threading.Thread(target=failsafe_watchdog, daemon=True).start()


def startup_relay_off():
    """Éteint les relais après une période de grâce au démarrage si aucune détection n'a eu lieu.

    Le fail-safe allume tous les relais au démarrage. Ce thread attend que la détection soit
    opérationnelle (15s), puis demande l'extinction si aucune zone n'est active.
    La logique interne de _delayed_off_relay (11s + vérification relay_active_zones) protège
    contre l'extinction si une personne est bien détectée pendant la période de grâce.

    Les relais non associés à une zone (ex : relais 3 et 4 si zones.ini ne les couvre pas)
    sont également éteints directement après la période de grâce + 11s de sécurité.
    """
    logger.info(f"⏳ Période de grâce fail-safe : {STARTUP_GRACE_PERIOD}s avant extinction initiale des relais")
    time.sleep(STARTUP_GRACE_PERIOD)
    logger.info("🔓 Période de grâce écoulée — extinction des relais si aucune détection active")
    # Extinction des relais gérés par les zones (via _delayed_off_relay avec vérification active)
    asyncio.run_coroutine_threadsafe(
        state.alert_manager.on_no_more_detection(time.time()),
        state.main_loop
    )
    # Extinction explicite des relais physiques non couverts par les zones (ex : relais 3, 4…)
    managed_relays = set(state.alert_manager.relay_on.keys())
    for i in range(len(state.relays.relays)):
        if i not in managed_relays and state.relays.get_relay_state(i):
            logger.info(f"🔧 Extinction du relais {i} (non géré par les zones) après période de grâce")
            state.relays.action_off(i)


def start_startup_relay_off():
    """Démarre le thread d'extinction post-démarrage (daemon)."""
    threading.Thread(target=startup_relay_off, daemon=True).start()
