"""Fonctions géométriques pures : zones, masques, overlays, recouvrement.

Aucun état, aucun effet de bord — testable sans hardware ni licence.
"""
import cv2
import numpy as np


def point_in_zone(x, y, zone):
    """Un point est-il dans une zone (polygone ou rectangle) ?

    Règle unique, partagée par la détection de piéton (centre de la bbox) et par
    l'affectation des relais (centre de l'icône de projecteur) : « dans la zone »
    doit vouloir dire la même chose pour l'un et pour l'autre.
    """
    polygon = zone.get("polygon")
    if polygon:
        if len(polygon) < 3:
            return False
        pts = np.array(polygon, dtype=np.int32)
        # cv2.pointPolygonTest attend un tableau Nx2 ; >= 0 inclut le bord.
        return cv2.pointPolygonTest(pts, (int(x), int(y)), False) >= 0
    rect = zone.get("rect")
    if rect:
        x1, y1, x2, y2 = rect
        return x1 <= x <= x2 and y1 <= y <= y2
    return False


def get_zone_for_detection(det, zones):
    # det est un dictionnaire : {"x_min": ..., "y_min": ..., etc.}
    # On prend le centre du rectangle de détection
    x_centre = int((det["x_min"] + det["x_max"]) / 2)
    y_centre = int((det["y_min"] + det["y_max"]) / 2)
    return [zone["name"] for zone in zones if point_in_zone(x_centre, y_centre, zone)]


def derive_zone_relays(zones, relay_positions):
    """``{nom_zone: [relais triés]}`` — le centre de l'icône de projecteur fait foi.

    Un relais appartient à **toutes** les zones qui contiennent son centre : deux
    zones qui se chevauchent partagent donc le relais posé dans leur intersection.
    C'est ce qui permet le multi-zones sur une même caméra sans dupliquer l'icône,
    une seule position étant enregistrée par couple (relais, caméra).

    Args:
        zones: zones d'UNE caméra (dicts avec 'name' et 'polygon' ou 'rect').
        relay_positions: ``{relay_id: (x, y)}`` pour cette même caméra.
    """
    return {
        zone["name"]: sorted(
            relay_id
            for relay_id, (x, y) in (relay_positions or {}).items()
            if point_in_zone(x, y, zone)
        )
        for zone in zones
    }


def zone_relay_mismatches(zones, relay_positions):
    """Écarts entre relais **déclarés** dans zones.ini et relais **dérivés** des positions.

    Sert de garde-fou avant de basculer une configuration sur le modèle
    « position = affectation » : une zone dont le relais est déclaré mais dont
    l'icône a été posée ailleurs perdrait ce relais à la première sauvegarde de
    l'éditeur, sans que personne ne le voie. Retourne une liste de dicts
    ``{zone, declares, derives, perdus, gagnes}``, vide si tout concorde.
    """
    derives = derive_zone_relays(zones, relay_positions)
    ecarts = []
    for zone in zones:
        nom = zone["name"]
        declares = sorted(zone.get("relays", []) or [])
        obtenus = derives.get(nom, [])
        if declares != obtenus:
            ecarts.append({
                "zone": nom,
                "declares": declares,
                "derives": obtenus,
                "perdus": sorted(set(declares) - set(obtenus)),
                "gagnes": sorted(set(obtenus) - set(declares)),
            })
    return ecarts


def iou_overlap(a, b):
    """Retourne max(IoU, part de a contenue dans b) entre deux bboxes."""
    ix1 = max(a["x_min"], b["x_min"])
    iy1 = max(a["y_min"], b["y_min"])
    ix2 = min(a["x_max"], b["x_max"])
    iy2 = min(a["y_max"], b["y_max"])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = (a["x_max"] - a["x_min"]) * (a["y_max"] - a["y_min"])
    area_b = (b["x_max"] - b["x_min"]) * (b["y_max"] - b["y_min"])
    union = area_a + area_b - inter
    iou = inter / union if union > 0 else 0.0
    overlap_ratio = inter / area_a if area_a > 0 else 0.0
    return max(iou, overlap_ratio)


def create_zone_overlay(frame_shape, zones):
    """Crée un overlay transparent avec les zones dessinées une seule fois"""
    h, w = frame_shape[:2]
    overlay = np.zeros((h, w, 3), dtype=np.uint8)

    for i, zone in enumerate(zones):
        color_rgb = zone.get("color", (0, 255, 0))
        color = (color_rgb[2], color_rgb[1], color_rgb[0])  # RGB → BGR pour OpenCV
        if "polygon" in zone:
            # On s'assure que les points sont dans l'image
            pts = [
                (max(0, min(w - 1, int(xy[0]))), max(0, min(h - 1, int(xy[1]))))
                for xy in zone["polygon"]
            ]
            pts_np = np.array([pts], dtype=np.int32)
            cv2.polylines(overlay, pts_np, isClosed=True, color=color, thickness=4)
            # Afficher le nom de la zone au premier point
            cv2.putText(overlay, zone["name"], (pts[0][0], pts[0][1] + 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 3)
        elif "rect" in zone:
            x1, y1, x2, y2 = zone["rect"]
            # S'assurer que la zone ne dépasse pas l'image
            x1 = max(0, min(w - 1, x1))
            y1 = max(0, min(h - 1, y1))
            x2 = max(0, min(w - 1, x2))
            y2 = max(0, min(h - 1, y2))
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 4)
            cv2.putText(overlay, zone["name"], (x1, y1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 3)

    return overlay


def create_mask_overlay(frame_shape, masks):
    """Crée un masque booléen H×W pour les zones à noircir dans la GUI.

    Args:
        frame_shape: Tuple (H, W, ...) de la frame.
        masks: Liste de dicts {'polygon': list of (x, y)}.

    Returns:
        Tableau numpy booléen (H, W) — True = pixel à noircir.
    """
    h, w = frame_shape[:2]
    mask_img = np.zeros((h, w), dtype=np.uint8)
    for mask in masks:
        polygon = mask.get('polygon')
        if not polygon or len(polygon) < 3:
            continue
        pts = [
            (max(0, min(w - 1, int(xy[0]))), max(0, min(h - 1, int(xy[1]))))
            for xy in polygon
        ]
        pts_np = np.array([pts], dtype=np.int32)
        cv2.fillPoly(mask_img, pts_np, 255)
    return mask_img > 0
