"""
Outils de contexte véhicule:
- Calcul d'IoU entre boîtes
- Estimation de l'occlusion des jambes d'une personne par des véhicules
- Inférence d'un indicateur "dans_vehicule" pour chaque personne

Les boîtes sont au format [x_min, y_min, x_max, y_max] en pixels.
"""
from __future__ import annotations

from typing import Iterable, List, Dict, Tuple


def iou(box_a: Iterable[float], box_b: Iterable[float]) -> float:
    x1a, y1a, x2a, y2a = box_a
    x1b, y1b, x2b, y2b = box_b
    inter_x1 = max(x1a, x1b)
    inter_y1 = max(y1a, y1b)
    inter_x2 = min(x2a, x2b)
    inter_y2 = min(y2a, y2b)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    area_a = max(0.0, x2a - x1a) * max(0.0, y2a - y1a)
    area_b = max(0.0, x2b - x1b) * max(0.0, y2b - y1b)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _clip_box_to_frame(box: Iterable[float], w: int, h: int) -> List[float]:
    x1, y1, x2, y2 = box
    x1 = max(0.0, min(float(w - 1), float(x1)))
    y1 = max(0.0, min(float(h - 1), float(y1)))
    x2 = max(0.0, min(float(w - 1), float(x2)))
    y2 = max(0.0, min(float(h - 1), float(y2)))
    return [x1, y1, x2, y2]


def _rect_area(box: Iterable[float]) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _intersection_area(a: Iterable[float], b: Iterable[float]) -> float:
    x1a, y1a, x2a, y2a = a
    x1b, y1b, x2b, y2b = b
    inter_x1 = max(x1a, x1b)
    inter_y1 = max(y1a, y1b)
    inter_x2 = min(x2a, x2b)
    inter_y2 = min(y2a, y2b)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    return (inter_x2 - inter_x1) * (inter_y2 - inter_y1)


def leg_region(person_box: Iterable[float], frame_w: int, frame_h: int, leg_frac: float = 0.45) -> List[float]:
    """
    Retourne la sous-région des jambes pour une personne: la partie inférieure de la bbox.
    leg_frac: fraction de la hauteur à considérer comme jambes (0.3-0.5 recommandé).
    """
    x1, y1, x2, y2 = person_box
    height = max(0.0, y2 - y1)
    if height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    y_leg1 = y2 - leg_frac * height
    leg_box = [x1, y_leg1, x2, y2]
    return _clip_box_to_frame(leg_box, frame_w, frame_h)


def leg_occlusion_fraction(person_box: Iterable[float], vehicle_boxes: Iterable[Iterable[float]], frame_size: Tuple[int, int], leg_frac: float = 0.45) -> float:
    """
    Calcule la fraction de la région jambe recouverte par au moins un véhicule.
    Approche: somme des recouvrements tronquée à l'aire de la région jambe (approximation de l'union).
    frame_size: (w, h)
    """
    w, h = frame_size
    leg_box = leg_region(person_box, w, h, leg_frac)
    leg_area = _rect_area(leg_box)
    if leg_area <= 0:
        return 0.0
    covered = 0.0
    for vbox in vehicle_boxes:
        inter = _intersection_area(leg_box, vbox)
        if inter <= 0:
            continue
        # Évite double-compte grossier
        add = min(inter, max(0.0, leg_area - covered))
        covered += add
        if covered >= leg_area:
            return 1.0
    return max(0.0, min(1.0, covered / leg_area))


def infer_in_vehicle_context(
    detections: List[List],
    frame_size: Tuple[int, int],
    person_class_id: int = 1,
    vehicle_class_ids: Tuple[int, ...] = (3, 6, 7, 8),
    iou_threshold: float = 0.35,
    leg_occ_threshold: float = 0.4,
) -> Dict[int, Dict]:
    """
    Analyse les détections pour déterminer si chaque personne est probablement dans un véhicule.
    Retourne un dict: tracker_id_person -> { 'is_in_vehicle': bool, 'max_iou': float, 'leg_occ': float, 'vehicle_tracker_id': int | None }

    detections: liste d'items [x1,y1,x2,y2,confidence,class_id,tracker_id,personne_type]
    """
    w, h = frame_size
    persons = []
    vehicles = []
    for det in detections:
        if len(det) < 7:
            continue
        x1, y1, x2, y2, conf, cls_id, trk_id = det[:7]
        box = _clip_box_to_frame([float(x1), float(y1), float(x2), float(y2)], w, h)
        if int(cls_id) == person_class_id:
            persons.append((trk_id, box))
        elif int(cls_id) in vehicle_class_ids:
            vehicles.append((trk_id, box))

    vehicle_boxes = [b for _, b in vehicles]
    results: Dict[int, Dict] = {}
    for p_trk, p_box in persons:
        best_iou = 0.0
        best_v_trk = None
        for v_trk, v_box in vehicles:
            i = iou(p_box, v_box)
            if i > best_iou:
                best_iou = i
                best_v_trk = v_trk
        leg_occ = leg_occlusion_fraction(p_box, vehicle_boxes, frame_size=(w, h)) if vehicle_boxes else 0.0
        is_in_vehicle = (best_iou >= iou_threshold) and (leg_occ >= leg_occ_threshold)
        results[int(p_trk)] = {
            'is_in_vehicle': bool(is_in_vehicle),
            'max_iou': float(best_iou),
            'leg_occ': float(leg_occ),
            'vehicle_tracker_id': int(best_v_trk) if best_v_trk is not None else None,
        }
    return results
