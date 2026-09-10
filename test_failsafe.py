"""Tests du watchdog fail-safe (src/core/failsafe.check_failsafe) — logique pure, temps injecté.

Faux AlerteManager et faux relais ; vraie boucle asyncio dans un thread pour les
relâchements (release_forced_relays est planifié via run_coroutine_threadsafe).
"""
import asyncio
import logging
import threading
import time
from types import SimpleNamespace

import pytest

from src.core import failsafe
from src.core.state import state

T0 = 1_000.0
TIMEOUT = failsafe.HEARTBEAT_TIMEOUT  # 30 s


class FakeAlertManager:
    def __init__(self, mapping):
        self.mapping = mapping
        self.forced = []      # [(relais triés, raison)]
        self.released = []    # [(relais triés, raison)]
        self.resynced = []    # raisons des resynchronisations demandées

    def _get_relay_nums_from_zone(self, name):
        return self.mapping[name]

    def force_relays_on(self, relays, reason=""):
        self.forced.append((sorted(relays), reason))

    async def release_forced_relays(self, relays, reason=""):
        self.released.append((sorted(relays), reason))

    def resync_relays(self, reason=""):
        self.resynced.append(reason)
        return 0


SAVED = ('cam_ids', 'zones_by_camera', 'alert_manager', 'relays', 'main_loop',
         'last_heartbeat', 'application_healthy', 'boot_time',
         'last_heartbeat_by_cam', 'camera_failsafe', 'heartbeat_received',
         'relays_online')


@pytest.fixture
def env():
    saved = {k: getattr(state, k) for k in SAVED}
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    state.main_loop = loop
    state.relays = SimpleNamespace(relays=[None, None, None])       # 3 relais physiques
    state.cam_ids = ['rtsp://a', 'rtsp://b']
    state.zones_by_camera = {0: [{'name': 'zA'}], 1: [{'name': 'zB'}]}
    am = FakeAlertManager({'zA': [0, 1], 'zB': [2]})
    state.alert_manager = am
    state.boot_time = T0
    state.last_heartbeat = T0
    state.application_healthy = True
    state.heartbeat_received = False
    state.last_heartbeat_by_cam = {0: T0, 1: T0}
    state.camera_failsafe = {}
    state.relays_online = True

    def flush():
        """Attend l'exécution des coroutines déjà planifiées sur la boucle."""
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop).result(timeout=2)

    def beat(idx, at):
        state.last_heartbeat = max(state.last_heartbeat, at)
        state.last_heartbeat_by_cam[idx] = at

    yield SimpleNamespace(am=am, flush=flush, beat=beat)

    loop.call_soon_threadsafe(loop.stop)
    for k, v in saved.items():
        setattr(state, k, v)


def test_rien_a_faire_quand_tout_est_frais(env):
    assert failsafe.check_failsafe(T0 + 10) == []
    assert env.am.forced == [] and env.am.released == []
    assert state.application_healthy is True


def test_perte_une_camera_force_ses_relais_seulement(env):
    env.beat(0, T0 + 40)                          # cam 0 vivante, cam 1 muette depuis T0
    actions = failsafe.check_failsafe(T0 + 45)
    assert actions == [('camera_on', (1, [2]))]
    assert env.am.forced == [([2], env.am.forced[0][1])]
    assert 'caméra 1' in env.am.forced[0][1]
    assert state.camera_failsafe[1] is True
    assert state.application_healthy is True      # le niveau global n'est pas concerné
    # idempotence : un second passage ne reforce rien
    assert failsafe.check_failsafe(T0 + 50) == []
    assert len(env.am.forced) == 1


def test_retour_camera_relache_ses_relais(env):
    env.beat(0, T0 + 40)
    failsafe.check_failsafe(T0 + 45)              # cam 1 en fail-safe
    env.beat(1, T0 + 60)                          # la caméra 1 revient
    actions = failsafe.check_failsafe(T0 + 61)
    assert actions == [('camera_release', (1, [2]))]
    env.flush()
    assert env.am.released == [([2], env.am.released[0][1])]
    assert state.camera_failsafe[1] is False


def test_perte_totale_force_tout_puis_relache_au_retour(env):
    actions = failsafe.check_failsafe(T0 + TIMEOUT + 1)
    kinds = [a[0] for a in actions]
    assert kinds == ['global_on', 'camera_on', 'camera_on']
    assert state.application_healthy is False
    assert ([0, 1, 2], actions[0][1] and env.am.forced[0][1]) and env.am.forced[0][0] == [0, 1, 2]
    assert {a[1][0] for a in actions[1:]} == {0, 1}

    env.beat(0, T0 + 40); env.beat(1, T0 + 40)
    actions = failsafe.check_failsafe(T0 + 41)
    assert [a[0] for a in actions] == ['global_release', 'camera_release', 'camera_release']
    env.flush()
    assert env.am.released[0][0] == [0, 1, 2]
    assert state.application_healthy is True
    assert state.camera_failsafe == {0: False, 1: False}


def test_camera_jamais_demarree_est_evaluee_depuis_le_boot(env):
    state.last_heartbeat_by_cam = {0: T0 + 20}    # cam 1 n'a jamais émis
    state.last_heartbeat = T0 + 20
    actions = failsafe.check_failsafe(T0 + 35)
    assert actions == [('camera_on', (1, [2]))]
    assert state.application_healthy is True


def test_relais_partage_entre_deux_cameras_est_force_par_prudence(env):
    env.am.mapping = {'zA': [0, 1], 'zB': [1, 2]}
    env.beat(0, T0 + 40)
    actions = failsafe.check_failsafe(T0 + 45)
    assert actions == [('camera_on', (1, [1, 2]))]


def test_relays_for_camera_fait_l_union_des_zones(env):
    state.zones_by_camera = {0: [{'name': 'zA'}, {'name': 'zB'}]}
    assert failsafe.relays_for_camera(0) == {0, 1, 2}
    assert failsafe.relays_for_camera(7) == set()


def test_update_heartbeat_marque_recu_et_par_camera(env):
    state.application_healthy = False
    before = time.time()
    failsafe.update_heartbeat(1)
    assert state.heartbeat_received is True
    assert failsafe.heartbeat_received() is True
    assert state.application_healthy is True
    assert state.last_heartbeat_by_cam[1] >= before
    assert state.last_heartbeat >= before


class _StopWatchdog(BaseException):
    """Hors de la hiérarchie Exception : traverse le `except Exception` du watchdog."""


def test_watchdog_ne_meurt_pas_sur_exception(env, monkeypatch):
    # 1er passage : check_failsafe lève une Exception → le watchdog doit la journaliser
    # et continuer. 2e passage : on sort de la boucle infinie via une BaseException.
    calls = {'n': 0}
    def boom(now):
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError("relais indisponible")
        raise _StopWatchdog
    monkeypatch.setattr(failsafe, 'check_failsafe', boom)
    monkeypatch.setattr(failsafe.time, 'sleep', lambda s: None)
    with pytest.raises(_StopWatchdog):
        failsafe.failsafe_watchdog()
    assert calls['n'] == 2  # la RuntimeError n'a pas tué la boucle


# ── Module relais injoignable / de retour ────────────────────────────────────

def _relays_with_health(flag):
    """Pilote factice exposant check_health (le vrai : YoctoMultiRelay.check_health)."""
    return SimpleNamespace(relays=[None, None, None], check_health=lambda: flag['online'],
                           last_error='commande relais 0 perdue : Device not connected')


def test_module_relais_perdu_puis_de_retour_resynchronise(env, caplog):
    flag = {'online': True}
    state.relays = _relays_with_health(flag)
    assert failsafe.check_failsafe(T0 + 10) == []
    assert state.relays_online is True

    flag['online'] = False
    with caplog.at_level(logging.ERROR, logger='src.core.failsafe'):
        assert failsafe.check_failsafe(T0 + 15) == [('relays_lost', None)]
    assert state.relays_online is False
    assert any('MODULE RELAIS INJOIGNABLE' in r.getMessage() for r in caplog.records)
    assert failsafe.check_failsafe(T0 + 20) == [], "panne persistante : pas de nouvelle action"
    assert env.am.resynced == []

    flag['online'] = True
    assert failsafe.check_failsafe(T0 + 25) == [('relays_back', 0)]
    assert state.relays_online is True
    assert env.am.resynced == ['retour du module relais'], "état physique réappliqué au retour"


def test_pilote_sans_check_health_est_ignore(env):
    # Doubles de test et pilotes factices : pas de surveillance, pas d'erreur.
    assert failsafe.check_relay_module() == []
    assert state.relays_online is True


def test_schedule_journalise_une_exception_de_coroutine(env, caplog):
    async def boom():
        raise RuntimeError("commande relais perdue")

    with caplog.at_level(logging.ERROR, logger='src.core.async_bridge'):
        fut = failsafe._schedule(boom())
        with pytest.raises(RuntimeError):
            fut.result(timeout=2)
        env.flush()
    msgs = [r.getMessage() for r in caplog.records if r.name == 'src.core.async_bridge']
    assert len(msgs) == 1 and 'boom' in msgs[0] and 'commande relais perdue' in msgs[0]
