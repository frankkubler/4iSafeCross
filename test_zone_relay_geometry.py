"""L'affectation d'un relais à une zone se dérive de la position de son icône.

Modèle retenu (2026-09-16) : une position par couple (relais, caméra) — format
relay_positions.ini inchangé — et le CENTRE de l'icône fait foi. Un relais sert
plusieurs zones d'une même caméra si ces zones se chevauchent et qu'il est posé
dans leur intersection ; sur des caméras différentes, les positions sont
indépendantes.
"""
import pytest

from src.core.geometry import (derive_zone_relays, get_zone_for_detection,
                               point_in_zone, zone_relay_mismatches)

# Deux carrés qui se chevauchent sur [40,60] × [40,60]
GAUCHE = {"name": "zoneG", "polygon": [(0, 0), (60, 0), (60, 60), (0, 60)]}
DROITE = {"name": "zoneD", "polygon": [(40, 40), (100, 40), (100, 100), (40, 100)]}
RECT = {"name": "zoneR", "rect": (0, 0, 10, 10)}


def test_point_in_zone_polygone_et_rectangle():
    assert point_in_zone(30, 30, GAUCHE) is True
    assert point_in_zone(90, 90, GAUCHE) is False
    assert point_in_zone(5, 5, RECT) is True
    assert point_in_zone(50, 5, RECT) is False


def test_point_in_zone_sur_le_bord_est_dedans():
    assert point_in_zone(0, 0, GAUCHE) is True     # sommet
    assert point_in_zone(60, 30, GAUCHE) is True   # arête


def test_point_in_zone_degenere():
    assert point_in_zone(1, 1, {"name": "z", "polygon": [(0, 0), (5, 5)]}) is False  # < 3 points
    assert point_in_zone(1, 1, {"name": "z"}) is False                                # ni polygone ni rect
    assert point_in_zone(1, 1, {"name": "z", "polygon": []}) is False


def test_un_relais_dans_l_intersection_sert_les_deux_zones():
    derive = derive_zone_relays([GAUCHE, DROITE], {1: (50, 50)})
    assert derive == {"zoneG": [1], "zoneD": [1]}, "chevauchement : le relais sert les deux"


def test_un_relais_hors_intersection_ne_sert_qu_une_zone():
    derive = derive_zone_relays([GAUCHE, DROITE], {0: (10, 10), 2: (90, 90)})
    assert derive == {"zoneG": [0], "zoneD": [2]}


def test_un_relais_hors_de_toute_zone_ne_sert_rien():
    assert derive_zone_relays([GAUCHE, DROITE], {3: (500, 500)}) == {"zoneG": [], "zoneD": []}


def test_relais_tries_et_sans_position_ignores():
    derive = derive_zone_relays([GAUCHE], {4: (10, 10), 0: (20, 20), 2: (999, 999)})
    assert derive["zoneG"] == [0, 4]


def test_aucune_position_enregistree():
    assert derive_zone_relays([GAUCHE], {}) == {"zoneG": []}
    assert derive_zone_relays([GAUCHE], None) == {"zoneG": []}


# ── Garde-fou : écarts entre déclaré et dérivé ───────────────────────────────

def test_aucun_ecart_quand_position_et_declaration_concordent():
    zones = [dict(GAUCHE, relays=[1]), dict(DROITE, relays=[1])]
    assert zone_relay_mismatches(zones, {1: (50, 50)}) == []


def test_ecart_detecte_quand_l_icone_est_posee_ailleurs():
    zones = [dict(GAUCHE, relays=[0, 1]), dict(DROITE, relays=[])]
    ecarts = zone_relay_mismatches(zones, {0: (10, 10), 1: (90, 90)})
    assert len(ecarts) == 2
    perdu = next(e for e in ecarts if e["zone"] == "zoneG")
    assert perdu["declares"] == [0, 1] and perdu["derives"] == [0]
    assert perdu["perdus"] == [1] and perdu["gagnes"] == []
    gagne = next(e for e in ecarts if e["zone"] == "zoneD")
    assert gagne["perdus"] == [] and gagne["gagnes"] == [1]


def test_zone_sans_cle_relays_traitee_comme_vide():
    ecarts = zone_relay_mismatches([GAUCHE], {})
    assert ecarts == []


# ── Cohérence avec la détection de piéton ────────────────────────────────────

def test_meme_regle_que_pour_une_detection():
    """Un piéton dont le centre de bbox est au même point que l'icône est vu dans
    exactement les mêmes zones : une seule définition de « dans la zone »."""
    det = {"x_min": 40, "y_min": 40, "x_max": 60, "y_max": 60}   # centre (50, 50)
    zones_det = get_zone_for_detection(det, [GAUCHE, DROITE])
    derive = derive_zone_relays([GAUCHE, DROITE], {1: (50, 50)})
    assert zones_det == [z for z, relais in derive.items() if relais]
