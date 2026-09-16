"""La route /alerts_status expose détections et alertes en cours, sans toucher au bus USB.

Deux niveaux distincts : « detection » (une personne est vue dans la zone à l'instant t)
et « alert » (la zone maintient un relais actif — ce que voit le piéton sur le terrain).
"""
import pytest

from src.core.state import state
from src.web import routes_system


class FakeManager:
    def __init__(self, statuts):
        self.statuts = statuts

    def get_status(self, cam_id):
        return self.statuts.get(cam_id, 'offline')


class FakeAlertManager:
    """Expose ce que la route lit : mappage des zones, relais actifs, relais ON."""

    def __init__(self, mapping, relay_active_zones, relay_on):
        self.mapping = mapping
        self.relay_active_zones = relay_active_zones
        self.relay_on = relay_on

    def _get_relay_nums_from_zone(self, nom):
        return self.mapping.get(nom, [])


class RelaysInterdits:
    """Toute lecture du bus USB depuis une route interrogée à 1 Hz est une faute."""

    is_initialized = True

    def get_relay_state(self, index):
        raise AssertionError("/alerts_status ne doit jamais interroger le module relais")


SAVED = ('cam_ids', 'zones_by_camera', 'alert_manager', 'manager', 'relays',
         'shared_detections', 'relays_online', 'camera_failsafe')

A = "rtsp://u:p@172.16.10.169:554/stream1"
B = "rtsp://u:p@172.16.11.91:554/stream1"


@pytest.fixture
def client(monkeypatch):
    from flask import Flask
    saved = {k: getattr(state, k) for k in SAVED}

    state.cam_ids = [A, B]
    state.zones_by_camera = {
        0: [{"name": "zone1_cam0"}, {"name": "zone2_cam0"}],
        1: [{"name": "zone1_cam1"}],
    }
    state.alert_manager = FakeAlertManager(
        mapping={"zone1_cam0": [0, 1], "zone2_cam0": [], "zone1_cam1": [4]},
        relay_active_zones={0: {"zone1_cam0"}, 1: {"zone1_cam0"}, 4: set()},
        relay_on={0: True, 1: True, 4: False},
    )
    state.manager = FakeManager({A: 'online', B: 'offline'})
    state.relays = RelaysInterdits()
    state.relays_online = True
    state.camera_failsafe = {1: True}
    state.shared_detections = {
        0: [{"label": "person", "zones": ["zone1_cam0"]}],
        1: [{"label": "forklift", "zones": ["zone1_cam1"]}],   # ignoré : pas une personne
    }

    app = Flask(__name__)
    app.register_blueprint(routes_system.system_bp)
    yield app.test_client()

    for k, v in saved.items():
        setattr(state, k, v)


def _zones(payload, cam):
    return {z["name"]: z for z in payload["cameras"][cam]["zones"]}


def test_alerte_active_distinguee_de_la_simple_detection(client):
    d = client.get('/alerts_status').get_json()
    z0 = _zones(d, 0)
    assert z0["zone1_cam0"]["alert"] is True
    assert z0["zone1_cam0"]["detection"] is True
    assert z0["zone1_cam0"]["relays"] == [0, 1]
    assert z0["zone1_cam0"]["relays_on"] == [0, 1]
    # Zone sans relais actif ni détection : au repos
    assert z0["zone2_cam0"]["alert"] is False
    assert z0["zone2_cam0"]["detection"] is False


def test_un_chariot_ne_compte_pas_comme_detection(client):
    d = client.get('/alerts_status').get_json()
    assert _zones(d, 1)["zone1_cam1"]["detection"] is False


def test_zone_sans_relais_signalee(client):
    d = client.get('/alerts_status').get_json()
    assert _zones(d, 0)["zone2_cam0"]["relays"] == []


def test_resume_des_alertes_et_etat_camera(client):
    d = client.get('/alerts_status').get_json()
    assert d["alerts_count"] == 1
    assert d["alerts"] == [{"camera": 0, "zone": "zone1_cam0", "relays": [0, 1]}]
    assert d["relays_on"] == [0, 1]
    cam0, cam1 = d["cameras"]
    assert (cam0["index"], cam0["host"], cam0["online"], cam0["failsafe"]) == (0, "172.16.10.169", True, False)
    assert (cam1["index"], cam1["host"], cam1["online"], cam1["failsafe"]) == (1, "172.16.11.91", False, True)
    assert cam0["label"] == "Caméra 0 — 172.16.10.169"


def test_aucun_acces_au_bus_usb(client):
    # RelaysInterdits lève si get_relay_state est appelé : la route doit rester lisible
    # à 1 Hz sans charger la liaison USB de la carte.
    assert client.get('/alerts_status').status_code == 200
