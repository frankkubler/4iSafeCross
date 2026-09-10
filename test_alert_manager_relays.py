"""Tests de l'AlerteManager face à un module relais qui refuse les commandes.

Avant ce correctif, une YAPI_Exception levée par action_on tuait la coroutine
on_detection sans trace : l'alerte était affichée à l'écran mais jamais signalée
physiquement. Ici le pilote retourne False, l'AlerteManager le journalise, garde
un état interne côté sûr et retente à la détection suivante ; au retour du module
le watchdog demande une resynchronisation de l'état physique.
"""
import asyncio
import logging
from datetime import datetime, timedelta

import pytest

from src import alert_manager as am_module
from src.alert_manager import AlerteManager

LOGGER = "src.alert_manager.AlerteManager"
ZONES = {0: [{"name": "zone1_cam0", "relays": [0, 1]}, {"name": "zone2_cam0", "relays": [2]}]}


class FakeRelays:
    """Pilote factice : `ok` pilote la réussite des commandes, `commands` les trace."""

    def __init__(self, ok=True):
        self.ok = ok
        self.commands = []
        self.physical = {}

    def action_on(self, index=0):
        self.commands.append(("on", index))
        if self.ok:
            self.physical[index] = True
        return self.ok

    def action_off(self, index=0):
        self.commands.append(("off", index))
        if self.ok:
            self.physical[index] = False
        return self.ok

    def get_relay_state(self, index):
        return self.physical.get(index) if self.ok else None


@pytest.fixture
def manager(monkeypatch):
    # Pas de SQLite pendant les tests : la base est un détail de persistance.
    monkeypatch.setattr(am_module, "init_db", lambda: None)
    monkeypatch.setattr(am_module, "purge_old_relay_events", lambda: 0)
    events = []
    monkeypatch.setattr(am_module, "insert_relay_event", lambda *a: events.append(a))
    relays = FakeRelays()
    am = AlerteManager(relays, zones_by_camera=ZONES)
    # État après l'extinction initiale : relais OFF, prêts à s'allumer sur détection.
    for n in am.relay_on:
        am.relay_on[n] = False
        am.relay_on_time[n] = None
    am.events = events
    yield am
    am.recording_executor.shutdown(wait=False)


def detection(zone="zone1_cam0"):
    return [{"label": "person", "zones": [zone], "x_min": 0, "y_min": 0, "x_max": 1, "y_max": 1}]


def errors(caplog):
    return [r for r in caplog.records if r.levelno >= logging.ERROR and r.name == LOGGER]


def test_activation_refusee_est_visible_et_retentee(manager, caplog):
    manager.relays.ok = False
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        asyncio.run(manager.on_detection(1000.0, None, detection(), 0))
        asyncio.run(manager.on_detection(1000.1, None, detection(), 0))
    # Pas d'exception, état interne côté sûr : le relais n'est PAS considéré allumé.
    assert manager.relay_on[0] is False and manager.relay_on[1] is False
    assert manager.relay_on_time[0] is None, "pas d'horodatage d'allumage pour un relais resté OFF"
    assert "zone1_cam0" in manager.relay_active_zones[0], "la zone reste active : retentée plus tard"
    # Chaque détection retente la commande…
    assert manager.relays.commands.count(("on", 0)) == 2
    # …mais l'ERROR n'est émise qu'une fois par relais tant que la panne dure.
    msgs = [r.getMessage() for r in errors(caplog)]
    assert len(msgs) == 2 and all("IMPOSSIBLE" in m and "PAS signalée physiquement" in m for m in msgs)
    assert any("Relais 0" in m for m in msgs) and any("Relais 1" in m for m in msgs)


def test_retour_du_module_active_et_journalise(manager, caplog):
    manager.relays.ok = False
    asyncio.run(manager.on_detection(1000.0, None, detection(), 0))
    manager.relays.ok = True
    with caplog.at_level(logging.INFO, logger=LOGGER):
        asyncio.run(manager.on_detection(1001.0, None, detection(), 0))
    assert manager.relay_on[0] is True and manager.relay_on[1] is True
    assert manager.relays.physical == {0: True, 1: True}
    msgs = [r.getMessage() for r in caplog.records]
    assert any("de nouveau acceptées" in m for m in msgs)
    assert any("Activation du relais pour la zone zone1_cam0 (relais numéro 0)" in m for m in msgs)


def test_extinction_refusee_garde_le_relais_on_et_reprogramme(manager, caplog):
    async def scenario():
        manager.relay_on[0] = True
        manager.relay_on_time[0] = datetime.now() - timedelta(seconds=20)
        manager.relays.ok = False
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await manager._delayed_off_relay(0)
        # Côté sûr : le relais est toujours supposé ON, aucun événement enregistré…
        assert manager.relay_on[0] is True
        assert manager.events == []
        assert ("off", 0) in manager.relays.commands
        # …et une nouvelle tentative est programmée (11 s après l'échec).
        retry = manager.relay_timer_task.get(0)
        assert retry is not None and not retry.done()
        retry.cancel()
        try:
            await retry
        except asyncio.CancelledError:
            pass
    asyncio.run(scenario())
    assert any("extinction après fin de détection" in r.getMessage() for r in errors(caplog))


def test_extinction_reussie_inchangee(manager):
    async def scenario():
        manager.relay_on[0] = True
        manager.relay_on_time[0] = datetime.now() - timedelta(seconds=20)
        await manager._delayed_off_relay(0)
    asyncio.run(scenario())
    assert manager.relay_on[0] is False
    assert len(manager.events) == 1 and manager.events[0][0] == "relay_0"


def test_forcage_failsafe_refuse_ne_leve_pas(manager, caplog):
    manager.relays.ok = False
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        manager.force_relays_on([0, 1, 4], reason="test")   # 4 : hors zones
    assert manager.relay_on[0] is False and manager.relay_on[1] is False
    assert len(errors(caplog)) == 3


def test_resync_reapplique_l_etat_voulu(manager, caplog):
    manager.relay_on.update({0: True, 1: False, 2: True})
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert manager.resync_relays(reason="retour du module") == 0
    assert set(manager.relays.commands) == {("on", 0), ("off", 1), ("on", 2)}
    assert any("Resynchronisation des relais" in r.getMessage() for r in caplog.records)


def test_resync_compte_les_echecs(manager):
    manager.relay_on.update({0: True, 1: False, 2: True})
    manager.relays.ok = False
    assert manager.resync_relays() == 3
    assert manager._relays_failed == {0, 1, 2}
