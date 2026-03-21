# Détection de mouvement — Documentation

## Vue d'ensemble

La détection de mouvement est assurée par la classe `MotionDetector` ([src/motion.py](src/motion.py)).  
Elle est utilisée comme **garde d'entrée** avant chaque inférence IA : si aucun mouvement n'est détecté, la frame est ignorée, économisant ~100 ms par inférence.

### Pipeline de traitement (par frame)

```
Frame BGR
    │
    ▼
[Gaussian Blur 5×5]  ← optionnel, atténue bruit capteur
    │
    ▼
[MOG2 Background Subtractor]  ← modèle de fond adaptatif
    │
    ▼
[Threshold binaire > 200]  ← élimine les ombres (valeur 127)
    │
    ▼
[MORPH_OPEN 5×5]   ← supprime les artefacts ponctuels
[DILATE 3×3 ×2]    ← regroupe les zones proches
[MORPH_CLOSE 3×3]  ← remplit les trous dans les silhouettes
    │
    ▼
[Filtrage des contours]
  - Exclure area < min_contour_area
  - Optionnel : exclure aspect ratio h/w < 0.3 (artefacts plats)
    │
    ▼
[Critère de déclenchement brut]
  total_significant_area > MOTIONTHRESHOLD
  OU largest_contour_area > MOTION_MIN_SINGLE_CONTOUR
    │
    ▼
[Hystérésis temporelle]
  ON  : confirmed si motion_raw True  ≥ MOTION_ON_FRAMES  consécutives
  OFF : confirmed si motion_raw False ≥ MOTION_OFF_FRAMES consécutives
    │
    ▼
motion_confirmed (bool) + ROI (région d'intérêt)
```

---

## Paramètres configurables

Tous les paramètres sont dans [config/config.ini](config/config.ini), section `[APP]`.  
Ils peuvent aussi être modifiés **en temps réel** via l'API REST sans redémarrage.

### Paramètres MOG2 (modèle de fond)

| Paramètre | Défaut | Effet |
|---|---|---|
| `FGBG_HISTORY` | `500` | Nombre de frames pour apprendre le fond. **↑ = fond s'adapte plus lentement** → un piéton lent n'est pas absorbé. **↓ = s'adapte vite** mais rate les objets lents. |
| `FGBG_VAR_THRESHOLD` | `16` | Sensibilité aux variations de luminosité. **↑ = moins sensible** → moins de FP par changements de lumière. **↓ = plus sensible** → détecte des mouvements plus subtils. |
| `FGBG_DETECT_SHADOWS` | `true` | Détecte les ombres (codées à 127) séparément des objets. **Recommandé `true`** : évite que les ombres soient comptées comme du mouvement. |

### Seuils de déclenchement

| Paramètre | Défaut | Effet |
|---|---|---|
| `MOTIONTHRESHOLD` | `10000` | Somme des surfaces des contours significatifs pour déclencher. **↑ = moins sensible**. **↓ = plus sensible**, risque de FP. |
| `MOTION_MIN_SINGLE_CONTOUR` | `3000` | Surface minimale d'**un seul** contour pour déclencher indépendamment du total. Permet de détecter un piéton lointain isolé même si `MOTIONTHRESHOLD` n'est pas atteint. |

### Filtrage des contours

| Paramètre | Défaut | Effet |
|---|---|---|
| `MOTIONTHRESHOLD` (via `min_contour_area`) | `30` px² | Surface minimale pour qu'un contour soit pris en compte. Réglable via API (`min_area`). |
| `MOTION_ASPECT_FILTER` | `false` | Active le filtre h/w < 0.3 : exclut les contours très plats (vibrations caméra horizontales). Désactivé par défaut pour ne pas casser les cas existants. |

### Hystérésis temporelle

| Paramètre | Défaut | Effet |
|---|---|---|
| `MOTION_ON_FRAMES` | `2` | Frames consécutives avec mouvement brut détecté pour **confirmer ON**. **↑ = moins de FP** mais réponse plus lente. |
| `MOTION_OFF_FRAMES` | `5` | Frames consécutives sans mouvement pour **confirmer OFF**. **↑ = la détection reste active plus longtemps** après disparition du mouvement → évite les coupures pendant un passage. |

### Pré-traitement

| Paramètre | Défaut | Effet |
|---|---|---|
| `MOTION_GAUSSIAN_BLUR` | `true` | Applique un flou gaussien 5×5 avant MOG2. Réduit le bruit capteur (~2 ms sur Jetson). **Désactiver si la performance est critique** et que la caméra est stable. |

---

## Problèmes courants et réglages

### Scénario 1 — Piéton lointain non détecté (faux négatif)

Le piéton génère peu de pixels → le total ne dépasse pas `MOTIONTHRESHOLD`.

**Solutions (par ordre d'impact) :**
1. Baisser `MOTION_MIN_SINGLE_CONTOUR` : `3000 → 1500`
2. Baisser `FGBG_VAR_THRESHOLD` : `16 → 10`
3. Baisser `MOTIONTHRESHOLD` : `10000 → 5000`
4. Baisser `MOTION_ON_FRAMES` : `2 → 1` (confirmation immédiate)

### Scénario 2 — Faux mouvement sans personne (faux positif)

Causes typiques : vibrations caméra, changements de lumière (nuages/soleil), reflets.

**Solutions (par ordre d'impact) :**
1. Augmenter `FGBG_VAR_THRESHOLD` : `16 → 20`
2. Augmenter `MOTION_ON_FRAMES` : `2 → 3`
3. Augmenter `MOTIONTHRESHOLD` : `10000 → 15000`
4. Activer `MOTION_ASPECT_FILTER = true` (si les artefacts sont horizontaux)
5. Augmenter `FGBG_HISTORY` : `500 → 800`

### Scénario 3 — Mouvement coupé pendant un passage (clignotement)

La détection s'active/s'éteint rapidement pendant qu'une personne traverse.

**Solution :** Augmenter `MOTION_OFF_FRAMES` : `5 → 10`

---

## Réglage en temps réel via l'API REST

Sans redémarrer l'application, tous les paramètres sont modifiables à chaud :

```bash
# Changer la sensibilité MOG2 pour la caméra 0
curl -X POST http://localhost:5000/set_motion_param/0 \
  -H "Content-Type: application/json" \
  -d '{"param": "varThreshold", "value": 20}'

# Modifier l'hystérésis
curl -X POST http://localhost:5000/set_motion_param/0 \
  -H "Content-Type: application/json" \
  -d '{"param": "motion_on_frames", "value": 3}'

# Activer le filtre aspect ratio
curl -X POST http://localhost:5000/set_motion_param/0 \
  -H "Content-Type: application/json" \
  -d '{"param": "aspect_filter", "value": true}'

# Modifier le seuil de pixels
curl -X POST http://localhost:5000/set_motion_param/0 \
  -H "Content-Type: application/json" \
  -d '{"param": "white_pixels_threshold", "value": 7000}'
```

### Paramètres disponibles via API

| `param` | Type | Description |
|---|---|---|
| `white_pixels_threshold` | int | Seuil total des contours significatifs |
| `varThreshold` | int | Sensibilité MOG2 |
| `history` | int | Historique MOG2 |
| `detectShadows` | bool | Détection ombres MOG2 |
| `padding` | int | Marge autour du ROI (pixels) |
| `min_area` | int | Surface minimale d'un contour |
| `motion_on_frames` | int | Frames pour confirmer ON |
| `motion_off_frames` | int | Frames pour confirmer OFF |
| `gaussian_blur` | bool | Activer le flou gaussien |
| `aspect_filter` | bool | Activer le filtre h/w |
| `min_single_contour` | int | Surface minimale d'un seul contour |

---

## Diagnostic avec les logs DEBUG

Activer le niveau DEBUG pour le module `src.motion` affiche par frame :

```
motion_raw=True | white_px=8432 | sig_area=6200 | largest=5800
| consec_on=2 | consec_off=0 | confirmed=True
```

| Champ | Signification |
|---|---|
| `motion_raw` | Décision brute (avant hystérésis) |
| `white_px` | Pixels blancs totaux dans le masque |
| `sig_area` | Somme des surfaces des contours significatifs |
| `largest` | Surface du plus grand contour |
| `consec_on` | Compteur de frames avec mouvement brut |
| `consec_off` | Compteur de frames sans mouvement |
| `confirmed` | État final retourné à l'inférence |

Pour activer dans [config/config.ini](config/config.ini) :
```ini
[logging]
level = DEBUG
```

---

## Performances (Jetson Orin / Nano)

| Étape | Temps estimé |
|---|---|
| Gaussian Blur 5×5 (1080p) | ~2 ms |
| MOG2 apply | ~5-8 ms |
| Morphologie + contours | ~2 ms |
| Total détection de mouvement | **~10-12 ms** |
| Inférence IA (si mouvement) | ~100 ms |

Le gain principal provient du **gate** : sans mouvement, l'inférence IA est entièrement sautée.
