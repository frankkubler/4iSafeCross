"""Le mappage zone → relais est porté par la clé « relays » de zones.ini, pas par le nom.

Piège corrigé (2026-09-16) : une zone enregistrée sans relais coché n'écrivait pas la
clé, le chargeur posait une liste vide, et l'AlerteManager retombait sur le mappage
historique PAR NOM (zone1*/zone3* → 0,1,2 ; zone2*/zone4*/zone5* → 1). Or l'éditeur
renumérote les zones à chaque suppression : décocher tous les relais d'une zone lui en
attribuait, et lesquels dépendait de sa position dans la liste.
"""
import pytest

from src import alert_manager as am_module
from src.alert_manager import AlerteManager
from utils.constants import load_zones_by_camera_from_ini
from utils.zone_writer import save_zones_to_ini

TRI = [(10, 10), (100, 10), (50, 100)]


def _manager(monkeypatch, zones_by_camera):
    monkeypatch.setattr(am_module, "init_db", lambda: None)
    monkeypatch.setattr(am_module, "purge_old_relay_events", lambda: 0)
    monkeypatch.setattr(am_module, "insert_relay_event", lambda *a: None)

    class Relays:
        def action_on(self, i=0): return True
        def action_off(self, i=0): return True
        def get_relay_state(self, i): return False

    return AlerteManager(Relays(), zones_by_camera=zones_by_camera)


# ── chargeur ──────────────────────────────────────────────────────────────────

def test_le_chargeur_distingue_cle_vide_et_cle_absente(tmp_path):
    ini = tmp_path / "zones.ini"
    ini.write_text(
        "[zone1_cam0]\npolygon = (10, 10), (100, 10), (50, 100)\ncolor = 255,0,0\nrelays = 0, 2\n"
        "[zone2_cam0]\npolygon = (10, 10), (100, 10), (50, 100)\ncolor = 0,255,0\nrelays =\n"
        "[zone3_cam0]\npolygon = (10, 10), (100, 10), (50, 100)\ncolor = 0,0,255\n",
        encoding="utf-8",
    )
    zones = {z["name"]: z for z in load_zones_by_camera_from_ini(str(ini))[0]}
    assert zones["zone1_cam0"]["relays"] == [0, 2]
    assert zones["zone2_cam0"]["relays"] == []          # clé présente, vide : aucun relais
    assert "relays" not in zones["zone3_cam0"]           # clé absente : fichier hérité


# ── écrivain ──────────────────────────────────────────────────────────────────

def test_l_ecrivain_ecrit_toujours_la_cle_meme_vide(tmp_path):
    ini = tmp_path / "zones.ini"
    save_zones_to_ini(str(ini), 0, [
        {"name": "zone1_cam0", "polygon": TRI, "color": [255, 0, 0], "relays": [3, 4]},
        {"name": "zone2_cam0", "polygon": TRI, "color": [0, 255, 0], "relays": []},
    ])
    texte = ini.read_text(encoding="utf-8")
    assert "relays = 3,4" in texte
    assert texte.count("relays") == 2, "la clé doit figurer dans les deux sections"
    zones = {z["name"]: z for z in load_zones_by_camera_from_ini(str(ini))[0]}
    assert zones["zone1_cam0"]["relays"] == [3, 4]
    assert zones["zone2_cam0"]["relays"] == []


def test_l_ecrivain_preserve_les_autres_cameras(tmp_path):
    ini = tmp_path / "zones.ini"
    save_zones_to_ini(str(ini), 1, [{"name": "zone1_cam1", "polygon": TRI, "color": [1, 2, 3], "relays": [4]}])
    save_zones_to_ini(str(ini), 0, [{"name": "zone1_cam0", "polygon": TRI, "color": [1, 2, 3], "relays": []}])
    par_cam = load_zones_by_camera_from_ini(str(ini))
    assert par_cam[1][0]["relays"] == [4]
    assert par_cam[0][0]["relays"] == []


# ── mappage ───────────────────────────────────────────────────────────────────

def test_une_liste_vide_explicite_ne_pilote_aucun_relais(monkeypatch):
    am = _manager(monkeypatch, {0: [{"name": "zone1_cam0", "relays": []}]})
    assert am._get_relay_nums_from_zone("zone1_cam0") == []
    assert am.relay_on == {}, "aucun relais géré : rien à initialiser"


def test_la_liste_explicite_prime_sur_le_nom(monkeypatch):
    am = _manager(monkeypatch, {0: [{"name": "zone1_cam0", "relays": [4]}]})
    assert am._get_relay_nums_from_zone("zone1_cam0") == [4]      # et non [0, 1, 2]


def test_le_repli_par_nom_ne_sert_qu_aux_zones_sans_cle(monkeypatch):
    am = _manager(monkeypatch, {0: [{"name": "zone1_cam0"}, {"name": "zone2_cam0"}, {"name": "zone7_cam0"}]})
    assert am._get_relay_nums_from_zone("zone1_cam0") == [0, 1, 2]
    assert am._get_relay_nums_from_zone("zone2_cam0") == [1]
    assert am._get_relay_nums_from_zone("zone7_cam0") == []


def test_la_renumerotation_ne_change_plus_les_relais(monkeypatch, tmp_path):
    """Scénario éditeur : on supprime zone1, zone2 devient zone1. Ses relais explicites
    restent [1] — avant, sa liste vide la faisait retomber sur le nom : [1] → [0, 1, 2]."""
    ini = tmp_path / "zones.ini"
    save_zones_to_ini(str(ini), 0, [
        {"name": "zone1_cam0", "polygon": TRI, "color": [1, 2, 3], "relays": [0]},
        {"name": "zone2_cam0", "polygon": TRI, "color": [1, 2, 3], "relays": [1]},
    ])
    # Suppression de la première zone, renumérotation comme le fait renumberZones()
    save_zones_to_ini(str(ini), 0, [{"name": "zone1_cam0", "polygon": TRI, "color": [1, 2, 3], "relays": [1]}])
    am = _manager(monkeypatch, load_zones_by_camera_from_ini(str(ini)))
    assert am._get_relay_nums_from_zone("zone1_cam0") == [1]
    assert set(am.relay_on) == {1}
