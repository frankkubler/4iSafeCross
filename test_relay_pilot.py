"""Tests du pilote de relais Yoctopuce (src/relay_pilot.py) avec une bibliothèque simulée.

Contrat vérifié : aucune commande n'échoue en silence, la panne est journalisée
en ERROR (puis rappelée sans inonder), le retour du module est constaté par
check_health et journalisé, et une carte absente au démarrage est reprise.
"""
import logging

import pytest
from yoctopuce.yocto_api import YAPI, YAPI_Exception
from yoctopuce.yocto_relay import YRelay

from src import relay_pilot

LOGGER = "src.relay_pilot.YoctoMultiRelay"


class FakeRelay:
    """Double d'un YRelay : `fail` simule un module qui ne répond plus."""

    def __init__(self):
        self.state = YRelay.STATE_A
        self.fail = False
        self._next = None

    def set_state(self, value):
        if self.fail:
            raise YAPI_Exception(YAPI.DEVICE_NOT_FOUND, "Device not connected")
        self.state = value

    def get_state(self):
        # Les getters Yoctopuce ne lèvent pas : ils renvoient INVALID hors ligne.
        return YRelay.STATE_INVALID if self.fail else self.state

    def isOnline(self):
        return not self.fail

    def nextRelay(self):
        return self._next


class FakeLib:
    """Pilote YAPI/YRelay simulé, branché par monkeypatch sur le module relay_pilot."""

    def __init__(self, relays, register_ok=True):
        self.relays = relays
        self.register_ok = register_ok
        self.register_calls = 0
        self.update_calls = 0
        # Chaînage FirstRelay → nextRelay dans l'ordre inverse (le pilote fait reverse()).
        for a, b in zip(relays, relays[1:]):
            b._next = a

    def RegisterHub(self, url, errmsg=None):
        self.register_calls += 1
        if not self.register_ok:
            errmsg.value = "hub USB indisponible"
            return YAPI.IO_ERROR
        return YAPI.SUCCESS

    def UpdateDeviceList(self, errmsg=None):
        self.update_calls += 1
        return YAPI.SUCCESS

    def FirstRelay(self):
        return self.relays[-1] if self.relays else None


@pytest.fixture
def lib(monkeypatch):
    def install(relays, register_ok=True):
        fake = FakeLib(relays, register_ok)
        monkeypatch.setattr(relay_pilot.YAPI, "RegisterHub", fake.RegisterHub)
        monkeypatch.setattr(relay_pilot.YAPI, "UpdateDeviceList", fake.UpdateDeviceList)
        monkeypatch.setattr(relay_pilot.YRelay, "FirstRelay", fake.FirstRelay)
        return fake
    return install


def errors(caplog):
    return [r for r in caplog.records if r.levelno >= logging.ERROR and r.name == LOGGER]


def test_init_enumere_les_relais_dans_l_ordre(lib):
    relays = [FakeRelay() for _ in range(3)]
    lib(relays)
    pilot = relay_pilot.YoctoMultiRelay()
    assert pilot.is_initialized and pilot.is_online
    assert pilot.relays == relays
    assert pilot.states == [None, None, None]


def test_commande_reussie_retourne_true_et_journalise(lib, caplog):
    lib([FakeRelay()])
    pilot = relay_pilot.YoctoMultiRelay()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert pilot.action_on(0) is True
    assert pilot.states[0] == YRelay.STATE_B
    assert any("Relais 0 -> état" in r.getMessage() for r in caplog.records)
    assert pilot.get_relay_state(0) == YRelay.STATE_B


def test_commande_perdue_retourne_false_et_trace_une_erreur(lib, caplog):
    relay = FakeRelay()
    lib([relay])
    pilot = relay_pilot.YoctoMultiRelay()
    relay.fail = True
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        assert pilot.action_on(0) is False      # pas d'exception qui remonte
        assert pilot.action_on(0) is False
        assert pilot.get_relay_state(0) is None
    assert pilot.is_online is False
    assert pilot.failed_commands == 3
    assert "commande relais 0" in pilot.last_error or "lecture relais 0" in pilot.last_error
    errs = errors(caplog)
    assert len(errs) == 1, "une seule ERROR : les échecs suivants sont throttlés"
    assert "MODULE RELAIS INJOIGNABLE" in errs[0].getMessage()


def test_panne_persistante_rappelee_apres_l_intervalle(lib, caplog, monkeypatch):
    relay = FakeRelay()
    lib([relay])
    pilot = relay_pilot.YoctoMultiRelay()
    relay.fail = True
    clock = {"t": 1000.0}
    monkeypatch.setattr(relay_pilot.time, "time", lambda: clock["t"])
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        pilot.action_on(0)
        clock["t"] += pilot.FAILURE_LOG_INTERVAL - 1
        pilot.action_on(0)
        assert len(errors(caplog)) == 1
        clock["t"] += 2
        pilot.action_on(0)
    assert len(errors(caplog)) == 2
    assert "3 commande(s) perdue(s)" in errors(caplog)[1].getMessage()


def test_retour_du_module_journalise_et_remet_les_compteurs(lib, caplog):
    relay = FakeRelay()
    lib([relay])
    pilot = relay_pilot.YoctoMultiRelay()
    relay.fail = True
    pilot.action_on(0)
    relay.fail = False
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert pilot.action_on(0) is True
    assert pilot.is_online and pilot.failed_commands == 0
    assert any("de nouveau joignable après 1 commande" in r.getMessage() for r in caplog.records)


def test_check_health_rafraichit_la_liste_et_constate_l_etat(lib):
    relays = [FakeRelay(), FakeRelay()]
    fake = lib(relays)
    pilot = relay_pilot.YoctoMultiRelay()
    assert pilot.check_health() is True
    assert fake.update_calls == 1, "UpdateDeviceList est indispensable pour voir revenir un module ré-énuméré"
    relays[1].fail = True
    assert pilot.check_health() is False
    assert pilot.is_online is False
    relays[1].fail = False
    assert pilot.check_health() is True
    assert pilot.is_online is True


def test_carte_absente_au_demarrage_puis_reprise_par_check_health(lib, caplog):
    fake = lib([])
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        pilot = relay_pilot.YoctoMultiRelay()
    assert pilot.is_initialized is False
    assert "aucun relais trouvé" in errors(caplog)[0].getMessage()
    assert pilot.action_on(0) is False          # pas d'exception, juste False
    assert pilot.get_relay_state(0) is None

    fake.relays = [FakeRelay()]                  # la carte est branchée
    assert pilot.check_health() is True
    assert pilot.is_initialized and len(pilot.relays) == 1
    assert pilot.action_on(0) is True


def test_hub_indisponible_ne_leve_pas(lib):
    lib([FakeRelay()], register_ok=False)
    pilot = relay_pilot.YoctoMultiRelay()
    assert pilot.is_initialized is False
    assert "hub Yoctopuce" in pilot.last_error
    assert pilot.set_relay(0, YRelay.STATE_B) is False


def test_index_invalide(lib, caplog):
    lib([FakeRelay()])
    pilot = relay_pilot.YoctoMultiRelay()
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        assert pilot.action_on(7) is False
        assert pilot.get_relay_state(7) is None
    assert all("Index de relais invalide" in r.getMessage() for r in errors(caplog))
    assert pilot.is_online, "un index invalide est une erreur de programme, pas une panne du module"
