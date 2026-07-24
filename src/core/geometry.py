"""Fonctions géométriques pures : zones, masques, overlays, recouvrement.

Aucun état, aucun effet de bord — testable sans hardware ni licence.
"""
import cv2
import numpy as np


def get_zone_for_detection(det, zones):
    # det est un dictionnaire : {"x_min": ..., "y_min": ..., etc.}
    # On prend le centre du rectangle de détection
    x_centre = int((det["x_min"] + det["x_max"]) / 2)
    y_centre = int((det["y_min"] + det["y_max"]) / 2)
    matched_zones = []
    for zone in zones:
        if "polygon" in zone:
            pts = np.array(zone["polygon"], dtype=np.int32)
            # cv2.pointPolygonTest attend un tableau Nx2
            inside = cv2.pointPolygonTest(pts, (x_centre, y_centre), False)
            if inside >= 0:
                matched_zones.append(zone["name"])
        elif "rect" in zone:
            x1, y1, x2, y2 = zone["rect"]
            if x1 <= x_centre <= x2 and y1 <= y_centre <= y2:
                matched_zones.append(zone["name"])
    return matched_zones


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
