#!/usr/bin/env python3
"""
Script de test pour vérifier que le nouveau format de détections fonctionne correctement.
"""

import sys
import os

# Ajouter le répertoire src au path pour importer les modules
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# Importer les fonctions à tester
from app import get_zone_for_detection


def test_get_zone_for_detection():
    """Test de la fonction get_zone_for_detection avec le nouveau format dictionnaire."""
    
    # Définir une zone de test
    zones = [
        {
            "name": "zone_test",
            "rect": [10, 10, 100, 100],
            "color": (255, 0, 0)
        },
        {
            "name": "zone_polygon",
            "polygon": [[200, 200], [300, 200], [300, 300], [200, 300]],
            "color": (0, 255, 0)
        }
    ]
    
    # Test avec l'ancien format (indices numériques) - ne devrait plus fonctionner
    print("=== Test avec nouveau format (dictionnaire) ===")
    
    # Détection dans la zone rect
    det_dict = {
        "x_min": 20,
        "y_min": 20,
        "x_max": 40,
        "y_max": 40,
        "confidence": 0.9,
        "class_id": 1,
        "tracker_id": 123,
        "personne_type": "pieton"
    }
    
    result = get_zone_for_detection(det_dict, zones)
    print(f"Détection dans zone rect: {result}")
    assert "zone_test" in result, f"Attendu 'zone_test' dans {result}"
    
    # Détection dans la zone polygon
    det_dict2 = {
        "x_min": 240,
        "y_min": 240,
        "x_max": 260,
        "y_max": 260,
        "confidence": 0.8,
        "class_id": 1,
        "tracker_id": 456,
        "personne_type": "pieton"
    }
    
    result2 = get_zone_for_detection(det_dict2, zones)
    print(f"Détection dans zone polygon: {result2}")
    assert "zone_polygon" in result2, f"Attendu 'zone_polygon' dans {result2}"
    
    # Détection hors de toutes les zones
    det_dict3 = {
        "x_min": 500,
        "y_min": 500,
        "x_max": 520,
        "y_max": 520,
        "confidence": 0.7,
        "class_id": 1,
        "tracker_id": 789,
        "personne_type": "pieton"
    }
    
    result3 = get_zone_for_detection(det_dict3, zones)
    print(f"Détection hors zones: {result3}")
    assert len(result3) == 0, f"Attendu liste vide, reçu {result3}"
    
    print("✅ Tous les tests sont passés!")


def test_detection_filtering():
    """Test du filtrage des détections par class_id et personne_type."""
    
    detections = [
        {
            "x_min": 10, "y_min": 10, "x_max": 30, "y_max": 30,
            "confidence": 0.9, "class_id": 1, "tracker_id": 1,
            "personne_type": "pieton"
        },
        {
            "x_min": 40, "y_min": 40, "x_max": 60, "y_max": 60,
            "confidence": 0.8, "class_id": 1, "tracker_id": 2,
            "personne_type": "sitting_in_vehicle"
        },
        {
            "x_min": 70, "y_min": 70, "x_max": 90, "y_max": 90,
            "confidence": 0.7, "class_id": 2, "tracker_id": 3,
            "personne_type": ""
        }
    ]
    
    # Filtrer pour les piétons uniquement (class_id == 1 ET personne_type == "pieton")
    detections_person = [det for det in detections if det.get("class_id") == 1 and det.get("personne_type") == "pieton"]
    
    print(f"=== Test filtrage des détections ===")
    print(f"Détections totales: {len(detections)}")
    print(f"Détections piétons: {len(detections_person)}")
    print(f"Détection piéton: {detections_person[0] if detections_person else 'Aucune'}")
    
    assert len(detections_person) == 1, f"Attendu 1 piéton, reçu {len(detections_person)}"
    assert detections_person[0]["tracker_id"] == 1, f"Attendu tracker_id=1, reçu {detections_person[0]['tracker_id']}"
    
    print("✅ Test filtrage réussi!")


if __name__ == "__main__":
    try:
        test_get_zone_for_detection()
        test_detection_filtering()
        print("\n🎉 Tous les tests sont passés avec succès!")
        print("Le nouveau format de détections (dictionnaires) fonctionne correctement.")
    except Exception as e:
        print(f"\n❌ Erreur lors des tests: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
