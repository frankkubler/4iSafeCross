# Filtre anti-faux positifs par keypoints (YOLO-Pose)

## Problème

Le modèle de détection principal (`4isafecross_2.engine`) détectait l'arrière des
chariots élévateurs comme des `person`. Ces faux positifs déclenchaient des alertes
inutiles et des activations visuelles de projections erronées.

---

## Solution

Ajout d'une inférence YOLO-Pose en cascade sur chaque détection `person` :
si le modèle de pose ne trouve aucun keypoint humain visible dans la bounding box,
la détection est considérée comme un faux positif et **n'est pas alertée**.
Les bounding boxes restent affichées dans le flux vidéo pour tous les objets.

---

## Architecture des modifications

### 1. `inf_jetson_yolo/inference_server.py` — Inférence pose (serveur Jetson)

**Modèle chargé :**
```python
model_pose = YOLO("models/yolo11n-pose-dynamic-half.engine", task="pose")
```

**Flux pour chaque détection `person` :**

1. Extraction du crop de la bounding box avec un padding de 30 px.
2. Rejet des crops trop petits (`w * h ≤ 1000 px²`).
3. Pose d'un **sentinel** `pose = []` **avant** l'inférence (voir patron ci-dessous).
4. Inférence `model_pose.predict(crop, conf=0.05, iou=0.3, half=True)`.
5. Si des keypoints sont trouvés : repositionnement dans le repère image original
   et ajout au champ `pose` de la détection au format `[[x, y, conf], ...]` (17 points COCO).

**Patron sentinel (important) :**
```python
#  pose absent / None  → modèle non exécuté (crop trop petit) → fail-safe, alerte autorisée
#  pose = []           → modèle a tourné mais 0 personne      → faux positif, alerte bloquée
#  pose = [[x,y,c]...] → keypoints trouvés                   → comptage des visibles
detections[-1]["pose"] = []          # sentinel posé AVANT l'inférence
if cropped.size > 0:
    pose_results = model_pose.predict(cropped[:, :, ::-1], conf=0.05, iou=0.3, ...)
    if pose_result.keypoints is not None and pose_result.keypoints.xy.shape[0] > 0:
        detections[-1]["pose"] = [[float(kx), float(ky), float(kc)] for ...]
```

**Pourquoi `conf=0.05` ?** Les crops sont bien plus petits que la résolution
d'entraînement du modèle ; un seuil standard (0.2–0.5) ferait rater des détections
légitimes. La valeur 0.05 + `iou=0.3` donne le meilleur rappel sur ce cas d'usage.

---

### 2. `4iSafeCross/src/alert_manager.py` — Filtre côté application

**Méthode `should_trigger_alert_for_detection(detection)`** :

| Valeur de `pose` | Signification | Décision |
|---|---|---|
| absent / `None` | Crop trop petit ou serveur sans modèle pose | **Laisser passer** (fail-safe) |
| `[]` | Modèle a tourné, 0 personne détectée | **Bloquer** (faux positif) |
| `[[x,y,c], ...]` | Keypoints trouvés | Compter les visibles (`conf ≥ 0.40`), bloquer si `< 4` |

```python
KP_CONF_THRESHOLD = 0.40
KP_MIN_VISIBLE = 4

pose = detection.get("pose")          # None si absent (pas get("pose", []))
if pose is not None:
    visible_kp = sum(1 for kp in pose if len(kp) >= 3 and float(kp[2]) >= KP_CONF_THRESHOLD)
    if visible_kp < KP_MIN_VISIBLE:
        self.logger.debug(f"Faux positif écarté — {visible_kp} kp visible(s), seuil = {KP_MIN_VISIBLE}")
        return False
if not detection.get("zones"):
    return False
return True
```

**Seuils calibrés (v2) :**
- `conf ≥ 0.40` : élimine les keypoints “hallucinés” sur des structures non humaines
- Minimum **4 keypoints** visibles : un chariot peut générer 2-3 kp parasites à conf > 0.40, pas 4+

**Pourquoi augmenter depuis 0.25 / min 1 ?** Cas réel observé (2026-03-19 15:52) :
un chariot élévateur détecté comme `person` (face latérale rouge) générait
6 keypoints visibles à conf ≥ 0.25 (kp5,6,8,11,12,14), dont seulement 3 à conf ≥ 0.40.
Avec les nouveaux seuils : 3 < 4 → **bloqué** ✓

---

### 3. `4iSafeCross/app.py` — Correction boucle de déclenchement

**Bug corrigé :** le bloc de filtrage keypoints et l'appel `on_detection` se trouvaient
**à l'intérieur** de la boucle `for zone_name in zone_names_list:`. Avec N zones
configurées, `on_detection` était appelé N fois pour la même frame, générant N alertes
identiques.

**Correction :** le filtrage et `on_detection` ont été sortis de la boucle zones.
La boucle ne gère plus que le suivi d'état `previous_detection` par zone.

```
for zone_name in zone_names_list:   ← boucle zones
    ├─ MAJ previous_detection        ← reste dans la boucle ✓
    └─ on_no_more_detection          ← reste dans la boucle ✓

# HORS de la boucle zones — appelé 1 seule fois par frame
detections_person_with_zone = [det for det in detections_person
                                if should_trigger_alert_for_detection(det)]
if detections_person_with_zone:
    on_detection(...)                ← 1 appel par frame ✓
```

---

## Affichage vidéo

Les bounding boxes sont dessinées depuis `shared_detections[cid]`, qui contient
**toutes** les détections brutes (personnes réelles, faux positifs, chariots…),
**avant** tout filtrage keypoints. Le filtre n'agit que sur le déclenchement
d'alerte (Telegram, relais, enregistrement), pas sur la visualisation.

---

## Résultats observés (logs de validation)

- Arrière de chariot élévateur → `pose=[]` → alerte **bloquée** ✓
- Personne réelle → `pose` avec 13 keypoints visibles → alerte **déclenchée** ✓
- Avant correction boucle : 6 alertes identiques pour 1 seule détection (6 zones configurées)
- Après correction : 1 alerte par piéton détecté par frame ✓

---

## Fichiers modifiés

| Fichier | Modification |
|---|---|
| `inf_jetson_yolo/inference_server.py` | Ajout inférence pose en cascade, sentinel `pose=[]`, `conf=0.05` |
| `inf_jetson_yolo/docker-compose.yml` | Suppression directive `ports:` incompatible avec `network_mode: host` |
| `4iSafeCross/src/alert_manager.py` | `should_trigger_alert_for_detection()` — logique keypoints |
| `4iSafeCross/app.py` | Correction boucle zones (déclenchement alerte hors boucle) |
