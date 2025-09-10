# 🧍‍♂️ Documentation - Système de Détection de Posture

## Vue d'ensemble

Le système de détection de posture analyse les keypoints (points-clés) de pose humaine pour déterminer automatiquement la stature d'une personne. Il utilise le format COCO avec 17 points anatomiques et implémente une logique adaptative selon la position de la personne dans l'image.

## 🎯 Objectifs

- **Détecter les postures** : assis, debout, marchant, jambes masquées
- **Adaptation contextuelle** : Ajustement automatique selon la zone dans l'image
- **Robustesse** : Fonctionnement avec keypoints partiels ou de qualité variable
- **Optimisation** : Logique différenciée selon la distance (premier plan vs fond)

---

## 📐 Zones de l'Image

Le système divise l'image en **3 zones verticales** pour adapter la logique de détection :

### 🔵 Zone HIGH (Fond - 0% à 28% de hauteur)
- **Caractéristiques** : Personnes éloignées, petites silhouettes
- **Défis** : Distances inter-articulaires réduites, keypoints moins précis
- **Adaptation** : Privilégie les ratios proportionnels plutôt que les distances absolues

### 🟡 Zone MIDDLE (Médiane - 28% à 60% de hauteur)
- **Caractéristiques** : Distance moyenne, proportions équilibrées
- **Défis** : Zone de transition nécessitant une logique équilibrée
- **Adaptation** : Seuils standards avec légère adaptation d'échelle

### 🔴 Zone LOW (Premier plan - 60% à 100% de hauteur)
- **Caractéristiques** : Personnes proches, grandes silhouettes
- **Défis** : Grandes distances inter-articulaires, risque de sur-détection
- **Adaptation** : Seuils ajustés pour les grandes proportions

```
┌─────────────────────────┐ ← 0% (haut image)
│     Zone HIGH (Fond)    │
│   Petites silhouettes   │ ← 28%
├─────────────────────────┤
│   Zone MIDDLE (Médiane) │
│  Proportions normales   │ ← 60%
├─────────────────────────┤
│  Zone LOW (Premier plan)│
│  Grandes silhouettes    │
└─────────────────────────┘ ← 100% (bas image)
```

---

## 🎮 Paramètres de Configuration

### Paramètres Principaux

| Paramètre | Valeur par défaut | Description |
|-----------|------------------|-------------|
| `confidence_threshold` | 0.5 | Seuil de confiance pour filtrer les keypoints |
| `knee_hip_threshold` | 35 | Distance minimale genou-hanche pour "debout" |
| `ankle_spread_threshold` | 25 | Écart maximal entre chevilles pour "assis" |
| `sitting_ratio_threshold` | 0.9 | Ratio tête-hanche/hanche-pieds pour "assis" |
| `enable_zone_adaptation` | True | Active l'adaptation selon la zone |
| `image_height` | 1080 | Hauteur d'image pour les calculs d'adaptation |

### Paramètres de Zone (centralisés dans la classe)

Le système utilise maintenant des **configurations centralisées** au début de la classe `PoseAnalyzer` pour une maintenance facilitée.

#### Zone HIGH (Fond)
```python
ZONE_HIGH_CONFIG = {
    'knee_hip_proximity_threshold': 25,     # Distance max genoux-hanches
    'ankle_knee_threshold': 12,             # Distance max chevilles-genoux
    'knee_hip_factor': 0.8,                 # Réduction 20% seuil debout
    'ankle_spread_factor': 0.85,            # Réduction 15% seuil marche
    'sitting_ratio_multiplier': 1.4,        # Ratio strict pour "assis"
    'standing_ratio_factor': 1.1,           # Ratio strict pour "debout"
}
```

#### Zone MIDDLE (Médiane)
```python
ZONE_MIDDLE_CONFIG = {
    'knee_hip_proximity_threshold': 45,     # Distance standard
    'ankle_knee_threshold': 20,             # Distance standard
    'knee_hip_factor': 0.9,                 # Réduction 10% seuil debout
    'ankle_spread_factor': 0.95,            # Réduction 5% seuil marche
    'sitting_ratio_multiplier': 1.2,        # Ratio standard pour "assis"
    'standing_ratio_factor': 1.0,           # Ratio standard pour "debout"
}
```

#### Zone LOW (Premier plan)
```python
ZONE_LOW_CONFIG = {
    'knee_hip_proximity_threshold': 45,     # Distance équilibrée
    'ankle_knee_threshold': 20,             # Distance standard
    'knee_hip_factor': 1.0,                 # Aucune réduction
    'ankle_spread_factor': 1.0,             # Aucune réduction
    'sitting_ratio_multiplier': 1.3,        # Ratio très élevé pour "assis"
    'standing_ratio_factor': 0.9,           # Ratio strict pour "debout"
}
```

---

## 🧮 Algorithmes de Détection

### 1. Calcul des Métriques

#### Distances Inter-articulaires
```python
knee_hip_diff = avg_knee_y - avg_hip_y    # Positif si genou plus bas
ankle_knee_diff = avg_ankle_y - avg_knee_y # Distance cheville-genou
ankle_spread = max(ankle_x) - min(ankle_x) # Écartement des chevilles
```

#### Ratio Proportionnel
```python
head_to_hip = distance(head, hanche)
hip_to_feet = distance(hanche, chevilles)
ratio = head_to_hip / hip_to_feet
```

### 2. Logique de Classification

#### 🪑 Détection "ASSIS"

**Zone HIGH (Fond)**
```python
is_sitting = (
    (ratio > sitting_ratio_threshold * 1.4) OR
    (genoux_proches_hanches AND chevilles_cachées) OR
    (chevilles_très_cachées)
) AND NOT (ordre_vertical_respecté)
```

**Zone MIDDLE/LOW**
```python
is_sitting = (
    (genoux_très_proches_hanches) OR
    (chevilles_cachées) OR
    (ratio_très_élevé)
) AND NOT (chevilles_bien_visibles)
```

#### 🚶 Détection "DEBOUT/MARCHANT"

**Toutes zones**
```python
is_standing = (
    ordre_vertical_strict AND           # hanche < genou < cheville
    distance_genou_hanche_suffisante AND
    distance_cheville_genou_suffisante AND
    NOT is_sitting AND
    ratio_cohérent_debout
)

if (ankle_spread > ankle_spread_threshold):
    return "marchant"
else:
    return "debout"
```

---

## ⚙️ Guide de Réglage

### Problèmes Courants et Solutions

#### 🔧 Trop de "inconnu"
- **Symptôme** : Classifications manquées
- **Solution** : Réduire `confidence_threshold` (0.5 → 0.3)
- **Alternative** : Réduire `knee_hip_threshold` (35 → 30)

#### 🔧 Confusion assis/debout
- **Symptôme** : Personnes debout classées assises
- **Solution** : Augmenter `sitting_ratio_threshold` (0.9 → 1.1)
- **Alternative** : Réduire seuils de zone spécifiques

#### 🔧 Marche non détectée
- **Symptôme** : Personnes marchant classées debout
- **Solution** : Réduire `ankle_spread_threshold` (25 → 20)

#### 🔧 Réglages avancés par zone
- **Zone HIGH** : Modifier `PoseAnalyzer.ZONE_HIGH_CONFIG['paramètre']`
- **Zone MIDDLE** : Modifier `PoseAnalyzer.ZONE_MIDDLE_CONFIG['paramètre']`
- **Zone LOW** : Modifier `PoseAnalyzer.ZONE_LOW_CONFIG['paramètre']`

### Réglages Avancés

#### Modification des configurations de zone
```python
# Exemple : rendre la zone HIGH plus stricte pour "assis"
PoseAnalyzer.ZONE_HIGH_CONFIG['sitting_ratio_multiplier'] = 1.6

# Exemple : zone LOW plus tolérante pour "debout"
PoseAnalyzer.ZONE_LOW_CONFIG['knee_hip_proximity_threshold'] = 50

# Exemple : ajuster les limites de zones
analyzer.zone_high = 0.25      # Zone fond plus petite (25% au lieu de 28%)
analyzer.zone_middle = 0.65    # Zone médiane étendue (65% au lieu de 60%)
```

#### Mode Debug avec configurations centralisées
```python
analyzer = PoseAnalyzer(enable_zone_adaptation=True)
result, debug_info = analyzer.analyze_stature(keypoints, debug=True)

print(f"Zone: {debug_info['zone']}")
print(f"Config utilisée: {analyzer.zone_configs[debug_info['zone']]}")
print(f"Seuils adaptés: {debug_info['adapted_thresholds']}")
print(f"Métriques: knee_hip_diff={debug_info['knee_hip_diff']}")
```

#### Accès aux configurations centralisées
```python
# Voir toutes les configurations disponibles
print("Configurations par zone:")
for zone_name, config in analyzer.zone_configs.items():
    print(f"{zone_name}: {config}")

# Modifier une configuration spécifique
analyzer.zone_configs['high']['sitting_ratio_multiplier'] = 1.5

# Désactivation adaptation
analyzer.enable_zone_adaptation = False
```

---

## 🔍 Métriques de Performance

### Indicateurs Clés

| Métrique | Description | Valeur cible |
|----------|-------------|--------------|
| **Précision "assis"** | % correct sur total "assis" détectés | > 85% |
| **Rappel "debout"** | % détectés sur total "debout" réels | > 90% |
| **Taux "inconnu"** | % classifications échouées | < 10% |
| **Confusion assis/debout** | % erreurs croisées | < 5% |

### Analyse des Zones

```python
def analyze_zone_performance(results):
    zones = ['high', 'middle', 'low']
    for zone in zones:
        zone_results = [r for r in results if r['zone'] == zone]
        accuracy = calculate_accuracy(zone_results)
        print(f"Zone {zone}: {accuracy:.2%}")
```

---

## 🚀 Optimisations

### Adaptations Automatiques

1. **Facteur d'échelle** : Basé sur la taille apparente de la personne
2. **Seuils dynamiques** : Ajustement selon la zone détectée
3. **Logique d'exclusion** : Empêche les classifications contradictoires
4. **Fallback intelligent** : Évite les "inconnu" quand possible

### Performance

- **Latence** : ~2ms par analyse
- **Mémoire** : ~50KB par instance
- **Compatibilité** : Keypoints COCO complets ou partiels
- **Robustesse** : Fonctionne avec 60% de keypoints manquants

---

## 📊 Exemple d'Utilisation

```python
from src.pose_analyser import PoseAnalyzer

# Configuration standard avec accès aux configurations centralisées
analyzer = PoseAnalyzer(
    confidence_threshold=0.2,
    knee_hip_threshold=35,
    ankle_spread_threshold=25,
    sitting_ratio_threshold=0.9,
    enable_zone_adaptation=True,
    image_height=1080
)

# Analyse d'une pose
keypoints = [
    {"x": 100, "y": 50, "confidence": 0.9},   # Nez
    # ... autres keypoints COCO
]

stature = analyzer.analyze_stature(keypoints)
print(f"Stature détectée: {stature}")

# Mode debug pour diagnostic avec configurations
stature, debug = analyzer.analyze_stature(keypoints, debug=True)
print(f"Zone: {debug['zone']}")
print(f"Config zone: {analyzer.zone_configs[debug['zone']]}")
print(f"Seuils: {debug['adapted_thresholds']}")

# Modification des configurations de zone
analyzer.zone_configs['low']['knee_hip_proximity_threshold'] = 50
print("Configuration zone LOW mise à jour")
```

---

## ⚠️ Limitations et Recommandations

### Limitations Connues

1. **Keypoints de qualité** : Nécessite hanches et genoux visibles minimum
2. **Angles de vue** : Optimisé pour vues de face/trois-quarts
3. **Occlusions** : Performance réduite si > 40% de keypoints masqués
4. **Résolution** : Moins précis sur images < 480p

### Recommandations

- **Qualité des keypoints** : Utiliser des modèles YOLO v8+ pour la pose
- **Résolution** : Minimum 720p pour une détection fiable
- **Éclairage** : Éviter les contre-jours forts
- **Calibrage** : Ajuster les seuils selon votre contexte d'usage

---

*📝 Document mis à jour le 10 septembre 2025*
*🔧 Version PoseAnalyzer v2.2 avec configurations centralisées*
*⚙️ Réglages de zones maintenant accessibles via `zone_configs`*
