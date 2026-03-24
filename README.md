# 4iSafeCross

**4iSafeCross** est un système de sécurité industrielle basé sur la vision par ordinateur, conçu pour détecter la présence de piétons dans les zones de circulation de chariots élévateurs et déclencher des alertes physiques (relais) et numériques (Telegram).

Déployé sur **Nvidia Jetson Orin NX** ([reServer Industrial J4012](https://wiki.seeedstudio.com/reServer_Industrial_Getting_Started/)), il traite en temps réel les flux RTSP de caméras fixes, effectue l'inférence IA via des serveurs dédiés et pilote des relais Yoctopuce pour activer des avertisseurs lumineux ou sonores.

## Fonctionnalités principales

- **Supervision multi-caméras** (RTSP/IP) avec décodage GStreamer accéléré matériellement (nvv4l2decoder Jetson)
- **Détection d'événements** par IA (YOLO11m / RF-DETR) via serveurs d'inférence dédiés sur HTTP
- **3 filtres anti-faux-positifs** en cascade : keypoints de pose, debounce temporel multi-frames, détection du conducteur (`driver`)
- **Mode fail-safe** : relais maintenus ON au démarrage, watchdog heartbeat, timer minimum d'allumage
- **Alertes Telegram** avec capture annotée (boîtes, zones, stature)
- **Pilotage de relais Yoctopuce** multi-canaux (avertisseurs lumineux/sonores) mappés par zone
- **Interface web Flask** : flux vidéo en direct, éditeur de zones/masques graphique, galerie des détections, statistiques système
- **Collecte automatique de dataset** intégrée (4 stratégies : temporel, événement, fond, hard-negatives)
- **Base de données SQLite** des événements (détections + activations relais)

## Structure du projet

```
4iSafeCross/
├── app.py                    # Application Flask principale (point d'entrée)
├── pyproject.toml            # Métadonnées et dépendances (uv)
├── requirements.txt          # Dépendances Python
├── config/
│   ├── config.ini            # Configuration principale (RTSP, IA, Telegram, relais…)
│   ├── zones.ini             # Zones de détection par caméra (polygones / rectangles)
│   ├── masks.ini             # Masques d'exclusion (zones noircies avant traitement)
│   └── relay_positions.ini   # Position des icônes de projecteurs sur le canvas web
├── db/
│   └── detections.db         # Base SQLite (détections + événements relais)
├── detections/               # Captures annotées lors des alertes
├── dataset/                  # Images et labels collectés automatiquement
├── logs/                     # Logs applicatifs (rotation logrotate)
├── src/
│   ├── alert_manager.py      # Gestion des alertes, relais, timers async
│   ├── bot_aiogram.py        # Bot Telegram (aiogram 3.x)
│   ├── camera_manager.py     # Capture RTSP via GStreamer (H.264, HW decoder)
│   ├── collect_dataset.py    # Thread de collecte automatique de dataset
│   ├── context_vehicle.py    # Analyse IoU personne/véhicule (contexte conducteur)
│   ├── detection_db.py       # Schéma et insertions SQLite
│   ├── inference.py          # Thread d'inférence IA (YOLO + pose)
│   ├── motion.py             # Détection de mouvement MOG2
│   ├── pose_analyser.py      # Analyse de stature par keypoints COCO
│   └── relay_pilot.py        # Contrôle des relais Yoctopuce (USB)
├── utils/
│   ├── constants.py          # Chargement de config.ini → constantes Python
│   ├── utils.py              # Fonctions génériques (IP, Docker, logs, sauvegarde frame)
│   ├── zone_writer.py        # Sérialisation zones/masques vers INI
│   └── coco_classes.py       # Correspondance ID → nom de classe COCO
├── static/                   # Ressources web (CSS, JS, Fabric.js, icônes)
├── templates/                # Templates Jinja2 Flask (index, zone_editor, preview…)
└── scripts/                  # Scripts systemd, déploiement Jetson, logrotate
```

## Pipeline de détection

### Vue d'ensemble

```
Caméra RTSP
     │  GStreamer (nvv4l2decoder H.264 HW)
     ▼
CameraManager  ──── frame brute (1080p)
     │
     ├── _apply_masks()          # Pixels masqués → 0 (config/masks.ini)
     │
     ├── MOG2 detect_motion()    # Détection de mouvement (seuil MOTIONTHRESHOLD)
     │         │ mouvement détecté ?
     │         ▼
     │   POST /infer (YOLO)      # Serveur inférence HTTP (port 8002)
     │   + POST /pose (YOLOv8-pose)
     │         │
     │         ▼
     │   Détections brutes : forklift | driver | person | …
     │         │
     │         ▼
     │   ┌──────────────────────────────────────────────────┐
     │   │        3 filtres anti-faux-positifs               │
     │   │                                                    │
     │   │  1. Keypoints de pose                             │
     │   │     pose=[]     → rejet (faux +, chariot)         │
     │   │     kp < 4      → rejet (conf < 0.40)             │
     │   │     kp ≥ 4      → OK                              │
     │   │                                                    │
     │   │  2. Debounce temporel (configurable par zone)    │
     │   │     N frames consécutives (défaut N=2)            │
     │   │     délai de reset (défaut 0.8 s)                 │
     │   │     → configurable dans zones.ini par zone        │
     │   │                                                    │
     │   │  3. Label driver                                  │
     │   │     label='driver' → jamais d'alerte              │
     │   └──────────────────────────────────────────────────┘
     │         │ personne confirmée dans une zone ?
     │         ▼
     │   AlerteManager.on_detection()
     │         │
     │         ├── Relais Yoctopuce ON (zone → relais config/zones.ini)
     │         ├── Timer minimum d'allumage (11 s par défaut)
     │         ├── Alerte Telegram (image annotée)
     │         └── Sauvegarde frame (detections/)
     │
     └── gen_frames()            # Flux MJPEG vers interface web
```

### Modes de détection (`DETECTION` dans config.ini)

| Mode | Classes surveillées | Usage |
|---|---|---|
| `simple` | `person` uniquement (COCO class 0) | Environnement sans chariot |
| `extended` | `person` + `forklift` + autres COCO | Surveillance générale |
| `transfert` | Classes custom entraînées : `forklift(0)`, `driver(1)`, `person(2)`, `bus`, `truck`, `car` | **Mode production** — modèle réentraîné site |

En mode `transfert`, seul `label='person'` déclenche des alertes. `label='driver'` est filtré en aval : l'opérateur assis sur son chariot ne génère pas d'alerte.

### Filtres anti-faux-positifs

#### 1. Filtre keypoints de pose

Avant toute alerte, `should_trigger_alert_for_detection()` vérifie les keypoints COCO-17 retournés par le modèle de pose :

```
pose = []          → modèle a tourné, aucun corps détecté → rejet (faux positif)
pose = [[x,y,c]…] → compter les keypoints visibles (conf ≥ 0.40)
                     < 4 kp visibles → rejet (probable structure métallique)
                     ≥ 4 kp visibles → alerte autorisée
pose absent/None   → fail-safe, alerte autorisée
```

**Justification du seuil 4 kp / 0.40** : un chariot élévateur peut générer 2 à 3 keypoints parasites à confiance > 0.40 par réflexion sur les barres métalliques. Un vrai corps humain en génère toujours plus de 4.

##### Bypass du filtre keypoints : `skip_keypoint_filter`

Certaines zones peuvent requérir une détection même lorsque le modèle de pose ne voit pas de corps complet (personne partiellement hors-champ, occlusion, vitesse de traversée élevée). Dans ce cas, activez `skip_keypoint_filter` **par zone** dans `config/zones.ini` :

```ini
[zone1_cam0]
skip_keypoint_filter = true
```

Lorsque ce paramètre est `true`, les rejets sur `pose=[]` ou `kp < 4` sont ignorés pour cette zone spécifique. Les autres filtres (debounce, label `driver`) restent actifs.

> **Note diagnostic** : lorsque le filtre est bypassé, un message `Filtre keypoints bypassé zones=[…]` apparaît au niveau INFO dans les logs. Un message `Faux positif écarté — pose=[] zones=[] skip_flags=[…]` indique qu'une détection a été rejetée, avec le contexte complet des zones et de leur configuration.

#### 2. Debounce temporel (configurable par zone)

Le debounce est configurable globalement (dans `app.py`) **et par zone** (dans `config/zones.ini`) :

| Paramètre | Valeur globale | Rôle |
|---|---|---|
| `PERSON_DEBOUNCE_FRAMES` / `debounce_frames` | `2` | Nombre de frames valides consécutives requises avant de déclencher l'alerte |
| `PERSON_RESET_SECONDS` / `debounce_reset_seconds` | `0.8 s` | Délai après lequel le compteur se réinitialise en l'absence de détection |

Si une zone définit ses propres valeurs dans `zones.ini`, elles priment sur les constantes globales. Une valeur absente ou vide utilise la valeur globale.

**Configuration dans zones.ini :**

```ini
[zone1_cam0]
polygon = …
relays = 1
debounce_frames = 5       # Optionnel — 5 frames requises avant alerte (défaut : 2)
debounce_reset_seconds = 2.0  # Optionnel — 2 s sans détection pour reset (défaut : 0.8)
```

Ces valeurs sont également éditables directement dans l'**éditeur graphique** (`/zone_editor/<cam_id>`) via deux champs numériques par zone dans le panneau latéral.

Une détection isolée sur une seule frame est ignorée. L'alerte ne se déclenche que si la même zone contient une personne valide sur **N frames successives**.

**Pourquoi un reset temporel et non par frame ?** MOG2 peut émettre des callbacks vides (`[]`) à 50 ms d'intervalle entre deux inférences réelles distantes de 300–500 ms. Sans reset temporel, ces callbacks vides réinitialisent le compteur à chaque fois, empêchant le debounce de dépasser 1 même lors d'une présence continue. La fenêtre de 0.8 s absorbe jusqu'à ~16 callbacks vides sans pénaliser la réactivité.

Ce filtre protège contre les fausses détections transitoires lors de l'entrée d'un chariot dans le champ (la silhouette du conducteur peut être brièvement classifiée `person` avant que le modèle identifie `driver`).

#### 3. Label `driver`

Toute détection avec `label='driver'` est exclue de la boucle d'alerte. Seul `label='person'` (piéton à pied) est traité.

### Mode fail-safe

Le système est conçu pour **alerter en cas de doute** plutôt que de rater une détection réelle :

| Situation | Comportement |
|---|---|
| Démarrage application | Tous les relais passent à **ON** immédiatement |
| Absence de heartbeat > 30 s | Watchdog réactive tous les relais à **ON** |
| Alerte déclenchée | Timer minimum : relais reste ON au moins **11 s** même si la personne quitte la zone |
| `pose=None` (timeout serveur pose) | Fail-safe : alerte autorisée sans vérification keypoints |

### Câblage des relais Yoctopuce (NC vs NO)

Le module Yocto-MaxRelay expose pour chaque canal deux modes de fermeture de contact :

| État logiciel | Bobine | Contact NO | Contact NC |
|---|---|---|---|
| `STATE_B` (`action_on`) | Excitée | Fermé | Ouvert |
| `STATE_A` (`action_off`) | Désexcitée | Ouvert | **Fermé** |

Un relais câblé en **NC (Normally Closed)** présente un état de contact fermé (`True`) lorsque la bobine est **désexcitée** (`action_off` → `STATE_A`). C'est le comportement attendu côté Yocto : `get_relay_state()` retourne `True` après extinction pour un relais NC. Ceci n'est pas un bug — la cohérence avec le monde physique dépend du câblage de chaque canal.

> Sur le déploiement Chaunay : relais 0 et 2 câblés en **NC**, relais 1 câblé en **NO**. Les logs `Relais N → état True` après extinction sont attendus pour 0 et 2.


### Prérequis

Le PC jetson doit être flashé avec la [méthode 1](https://wiki.seeedstudio.com/reServer_Industrial_Getting_Started/) avec le JetPack 6.1 L4T 36.4 (Attention : le flash doit se faire avec un PC Ubuntu 22.04 (la même identique à celle du JetPack)) 

Le serveur d'inférence doit être installé dans un docker [inf_jetson_rf-detr](https://github.com/4itec-org/inf_jetson_rf-detr)

Le serveur d'inférence doit être installé dans un docker [inf_jetson_yolo] (https://github.com/4itec-org/inf_jetson_yolo)

### Environnement
- Python 3.10.12
- [uv](https://github.com/astral-sh/uv) (gestionnaire de dépendances ultra-rapide)
- Accès réseau aux caméras RTSP/IP

### Récupération du code

Clonez le dépôt GitHub :

```sh
git clone <url-du-depot-github>
cd 4iSafeCross
```

### Installation des dépendances

```sh
uv sync
```

### Configuration

Modifiez les paramètres dans [`config/config.ini`](config/config.ini) :
- Identifiants RTSP (`LOGIN`, `PASSWORD`, `HOST`, etc. dans la section `[RTSP]`)
- Seuils de détection (`MOTIONTHRESHOLD`, `INF_THRESHOLD` dans la section `[APP]`)
- Activation Telegram (`TELEGRAM_ENABLED` dans la section `[TELEGRAM]`)

#### Credentials sensibles — Token Telegram

Le token du bot Telegram et l'identifiant du groupe de supervision **ne doivent pas être écrits dans `config.ini`** (risque d'exposition dans le dépôt Git).

Ils sont lus en priorité depuis des **variables d'environnement** :

```
TELEGRAM_TOKEN=<token_du_bot>
TELEGRAM_CHAT_ID=<id_du_groupe>
```

**Procédure de configuration sur le boîtier :**

```sh
# 1. Créer le fichier .env depuis le modèle fourni
cp .env.example .env

# 2. Renseigner les valeurs réelles
nano .env

# 3. Restreindre les permissions (lecture uniquement par user-4itec)
chmod 600 .env
```

Le fichier `.env` est chargé automatiquement par le service systemd via `EnvironmentFile` (voir section [Services systemd](#services-systemd-et-scripts-bash-associés)). Il est exclu du dépôt Git (`.gitignore`).

### Rendre les scripts exécutables

Avant d’exécuter les scripts `.sh`, pensez à leur donner les droits d’exécution :
```sh
chmod +x *.sh
```
Ou pour un script spécifique :
```sh
chmod +x 4isafecross.sh 
```

### Lancement

Pour lancer l'application en production avec Waitress :

```sh
uv run waitress-serve --threads=4 --host=0.0.0.0 --port=5050 app:app
```

Ou utilisez le script d'automatisation fourni :

```sh
bash 4isafecross.sh
```

L’interface web sera accessible sur [http://localhost:5050](http://localhost:5050).

## Utilisation

- **Interface web** : contrôle des flux vidéo, activation/désactivation de la détection, réglage des seuils, consultation des alertes et galerie d’images.
- **Bot Telegram** : recevez des alertes, demandez une capture en envoyant `/take` ou l’état du système avec `/status`.

## Déploiement Docker

Un exemple de `Dockerfile` est fourni pour un déploiement en conteneur.

```sh
docker build -t 4isafecross .
docker run -p 5000:5000 --env-file .env 4isafecross
```

## Services systemd et scripts Bash associés

Le projet fournit plusieurs fichiers `.service` pour automatiser le lancement de l’application et la configuration de l’environnement au démarrage du système, ainsi que des scripts Bash associés :

### Fichiers systemd

- **4isafecross.service** :
  - Lance automatiquement l'application au démarrage.
  - Charge les variables d'environnement depuis `.env` via `EnvironmentFile` (credentials Telegram, etc.).
  - Gère les logs dans le dossier `logs/`.
  - Exemple d'installation :
    ```sh
    # Créer et remplir le fichier .env AVANT de démarrer le service
    cp .env.example /home/user-4itec/4iSafeCross/.env
    nano /home/user-4itec/4iSafeCross/.env
    chmod 600 /home/user-4itec/4iSafeCross/.env

    sudo cp scripts/4isafecross.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable 4isafecross.service
    sudo systemctl start 4isafecross.service
    ```

- **set-poe-gpio.service** :
  - Exécute le script `set_poe_gpio.sh` au boot pour configurer les GPIO du POE.

- **check-dummy-display.service** :
  - Exécute le script `switch-display.sh` pour configurer un écran virtuel ou vérifier la présence d’un écran HDMI.

### Scripts Bash

- **4isafecross.sh** :
  - Script principal de lancement de l’application avec `uv` et `waitress-serve`.
  - Peut être utilisé manuellement ou via le service systemd.

- **set_poe_gpio.sh** :
  - Configure les GPIO nécessaires à l’alimentation POE.

- **switch-display.sh** :
  - Configure un écran virtuel (dummy) si aucun écran HDMI n’est détecté.

Adaptez les chemins et utilisateurs dans les fichiers `.service` selon votre environnement.

## Schéma des ports RJ45, adresses IP et fonctions associées

Ci-dessous, un tableau récapitulatif des ports réseau (RJ45) du système, avec leur configuration IP et leur usage :

```
+-----------+-------------------+------------------------------------------+
|   Port    |    Adresse IP     |                Fonction                  |
+-----------+-------------------+------------------------------------------+
|  eth0     | DHCP              | Accès internet / réseau principal        |
|  eth1     | 192.168.2.100     | Caméra 1 (Entrée principale)             |
|  eth2     | 192.168.3.122     | Connexion directe RDP (maintenance)      |
|  eth3     | (non utilisé)     | Libre / extension future                 |
|  eth4     | (non utilisé)     | Libre / extension future                 |
+-----------+-------------------+------------------------------------------+
```

- **eth0** : Connecté au réseau principal, permet l'accès internet, la supervision distante et la communication avec Telegram.
- **eth1** : Port dédié à la caméra principale (sur sous-réseau isolé pour la vidéo).
- **eth2** : Port réservé à la maintenance (connexion RDP directe, accès d'urgence ou debug).
- **eth3/eth4** : Disponibles pour ajout de caméras ou autres usages (à configurer selon besoin).

> Adaptez les adresses IP et fonctions selon votre architecture réseau réelle. Utilisez des VLAN ou des sous-réseaux séparés pour la sécurité et la performance.

### Repérage visuel des ports RJ45

Schéma simplifié pour repérer physiquement les ports RJ45 à l’arrière de la machine :

```
+---------------------------------------------------+
|  +-----+ +-----+ +-----+ +-----+ +-----+          |
|  |eth0 | |eth1 | |eth2 | |eth3 | |eth4 |          |
|  +-----+ +-----+ +-----+ +-----+ +-----+          |
+---------------------------------------------------+
   |       |       |       |       |
   |       |       |       |       +-- Port le plus à droite (eth4)
   |       |       |       +---------- eth3
   |       |       +----------------- eth2
   |       +------------------------ eth1
   +------------------------------- Port le plus à gauche (eth0)
```

- **eth0** est toujours le port le plus à gauche lorsque vous regardez l’arrière de la machine.
- L’ordre des ports va de gauche à droite : eth0, eth1, eth2, eth3, eth4.
- **eth0** DHCP pour l'accès internet et la supervision distante.(connecter à un routeur ou switch)
- **eth1** Les adresses IP fixes des caméras utilisées par défaut sont :
> - Caméra 0 : 192.168.2.156
> - Caméra 1 : 192.168.2.157
> Vous pouvez modifier ces adresses dans le fichier [`config/zones.ini`](config/zones.ini), variable `RTSP_HOST`.
- **eth2** est réservé pour la connexion RDP de maintenance, avec l’adresse IP 192.168.3.122. (masque 255.255.255.0) user : user-4itec / mdp : 4itec2025!

## Gestion de la rotation des logs (logrotate)

Pour éviter que les fichiers de logs ne saturent le disque, un fichier de configuration logrotate est fourni : `4isafecross.logrotate`.

- Exemple de configuration (à adapter selon votre chemin d'installation) :

```logrotate
/home/user-4itec/github/4iSafeCross/logs/service_stdout.log
/home/user-4itec/github/4iSafeCross/logs/service_stderr.log {
    su root root
    size 10M
    rotate 5
    compress
    missingok
    notifempty
    copytruncate
}
```

**Installation** :
1. Copier le fichier dans `/etc/logrotate.d/` :
   ```sh
   sudo cp 4isafecross.logrotate /etc/logrotate.d/
   ```
2. Tester la rotation manuellement :
   ```sh
   sudo logrotate -f /etc/logrotate.d/4isafecross.logrotate
   ```

> Adaptez les chemins et droits selon votre environnement. Cette configuration garde 5 archives compressées de 10 Mo maximum chacune.

## Zones de détection et masques

### Éditeur graphique

L'interface `/zone_editor/<cam_id>` permet de dessiner et modifier les zones et les masques directement sur un snapshot de la caméra, sans éditer manuellement les fichiers INI.

- **Mode Zones** (bouton "📌 Mode : Zones") : dessin de polygones de détection colorés. Chaque zone peut avoir des relais associés déclenchés lors d'une détection.
- **Mode Masques** (bouton "⬛ Mode : Masques") : dessin de polygones de masquage noir. Les zones masquées sont exclues **en amont du pipeline complet** — ni la détection de mouvement (MOG2), ni l'inférence IA ne traitent les pixels masqués.

**Dessin d'un nouveau polygone :**

| Action | Résultat |
|---|---|
| Clic gauche | Ajouter un point au polygone en cours |
| Clic droit | Fermer le polygone (minimum 3 points) |
| `Shift` + clic gauche | Contraindre le segment à l'horizontale ou la verticale |
| `Échap` | Annuler le dessin en cours |

**Sélection et édition d'un polygone existant :**

| Action | Résultat |
|---|---|
| Clic sur un polygone | Sélectionner (contour épaissi) |
| 2e clic sur le polygone sélectionné | Entrer en mode édition des sommets — des poignées circulaires apparaissent sur chaque sommet |
| Glisser une poignée | Déplacer le sommet en temps réel (les arêtes suivent) |
| Clic en dehors du polygone | Terminer l'édition, polygone redessiné avec les nouvelles coordonnées |
| `Échap` | Terminer l'édition des sommets |
| `Delete` | Supprimer le polygone sélectionné (désactivé pendant l'édition des sommets) |

**Options par zone dans le panneau latéral :**

| Champ | Description |
|---|---|
| Cases à cocher *Relais* | Active/désactive les relais associés à la zone |
| Case à cocher *🚶 Piétons certains* | Bypass du filtre keypoints de pose (`skip_keypoint_filter`) |
| Champ *Débounce frames* | Nombre de frames positives avant alerte (vide = valeur globale `2`) |
| Champ *Reset (s)* | Délai de remise à zéro du compteur (vide = valeur globale `0.8`) |

**Boutons :**

| Bouton | Résultat |
|---|---|
| "Sauvegarder" | Enregistre zones **et** masques simultanément |
| "Réinitialiser" | Recharge l'état depuis les fichiers INI |
| "Rafraîchir snapshot" | Capture une nouvelle image de la caméra |

Les modifications sont persistées immédiatement dans `config/zones.ini` et `config/masks.ini` et prennent effet sans redémarrage de l'application.

---

### Définition manuelle des zones de détection

Les zones de détection sont stockées dans [`config/zones.ini`](config/zones.ini). Chaque zone peut être définie comme un rectangle (`rect`) ou un polygone (`polygon`), selon la forme souhaitée et la résolution de chaque caméra, sans toucher au code Python.

**Exemple de format dans zones.ini** :

```ini
[zone1_cam0]
rect = x1,y1,x2,y2
color = 255,0,255
relays = 0,1
debounce_frames = 3
debounce_reset_seconds = 1.5

[zone2_cam0]
polygon = (x1,y1)(x2,y2)(x3,y3)...
color = 0,255,255
skip_keypoint_filter = true
# debounce_frames et debounce_reset_seconds absents → valeurs globales (2 et 0.8)
```

#### Paramètres disponibles par zone

| Paramètre | Valeur | Description |
|---|---|---|
| `rect` | `x1,y1,x2,y2` | Zone rectangulaire (coin haut-gauche → bas-droit) |
| `polygon` | `(x1,y1)(x2,y2)…` | Zone polygonale (≥ 3 sommets) |
| `color` | `R,G,B` | Couleur d'affichage de la zone dans l'interface web |
| `relays` | `0,1,2,…` | Indices des relais activés lors d'une détection dans cette zone |
| `skip_keypoint_filter` | `true` / `false` (défaut) | Bypass du filtre keypoints de pose pour cette zone (voir §Filtres anti-faux-positifs) |
| `debounce_frames` | entier ≥ 1 (défaut : `2`) | Frames valides consécutives requises avant de déclencher l'alerte — surcharge la constante globale |
| `debounce_reset_seconds` | décimal ≥ 0.1 (défaut : `0.8`) | Délai (en secondes) sans détection avant remise à zéro du compteur — surcharge la constante globale |

#### Exemple de schéma de zones

**Caméra 0 (1920x1080)**
```
   +x→-------------------------------+
   y zone1_cam0                      |
   ↓ (x1=0, y1=0, x2=1920, y2=480)   |
   +---------------------------------+
   |         zone2_cam0              |
   | (x1=0, y1=360, x2=1920, y2=840) |
   +---------------------------------+
   |               zone3_cam0        |
   | (x1=0, y1=600, x2=1920, y2=1080)|
   +---------------------------------+
```

- Les coordonnées sont au format `(x1, y1, x2, y2)` :
    - `(x1, y1)` = coin supérieur gauche
    - `(x2, y2)` = coin inférieur droit
- Les flèches (→, ↓) indiquent le sens croissant des axes X et Y.

---

### Définition manuelle des masques

Les masques sont stockés dans [`config/masks.ini`](config/masks.ini). Un masque est un polygone qui rend une zone de l'image **totalement invisible** pour l'application : les pixels couverts sont mis à zéro (noir) avant tout traitement.

**Exemple de format dans masks.ini** :

```ini
[mask1_cam0]
polygon = (x1,y1)(x2,y2)(x3,y3)(x4,y4)

[mask2_cam0]
polygon = (x1,y1)(x2,y2)(x3,y3)
```

> Les masques n'ont ni couleur ni relais associés — seul le champ `polygon` est utilisé.

**Comportement en pipeline :**

```
frame brute (caméra)
        │
        ▼
  _apply_masks()          ← pixels masqués = 0 (noir) sur une copie de la frame
        │
        ▼
  get_mog2_motion_info()  ← MOG2 ne voit pas les zones masquées
        │
        ▼
  POST /infer (YOLO)      ← l'IA ne voit pas les zones masquées
        │
        ▼
  gen_frames() overlay    ← affichage web : zones noires sur le flux vidéo
```

Les masques sont rechargés à chaud sans redémarrage lorsqu'ils sont sauvegardés via l'éditeur graphique ou l'API REST (`POST /api/masks/<cam_id>`).

## Configuration du niveau de log

Le niveau de log de l’application peut être modifié dans le fichier [`config/config.ini`](config/config.ini), sans toucher au code Python.

**Exemple de section dans config.ini** :

```ini
[logging]
level = INFO  # ou DEBUG, WARNING, ERROR
```

Adaptez la valeur selon le niveau de détail souhaité pour les logs.


## Désactivation de l'autosuspend USB

Pour éviter les coupures intempestives des périphériques USB (caméras, clés, etc.), un script `disable-autosuspend.sh` est fourni. Il désactive l'autosuspend globalement au niveau du noyau.

### Utilisation

1. Exécutez le script avec les droits administrateur :
   ```sh
   sudo bash disable-autosuspend.sh
   ```
2. Redémarrez la machine pour que la modification prenne effet.

Après redémarrage, vérifiez la prise en compte du paramètre avec :
```sh
cat /proc/cmdline
```
Vous devez voir à la fin de la ligne : `usbcore.autosuspend=-1`

> Remarque : s'il y a plusieurs entrées `autosuspend`, le noyau utilisera la dernière occurrence.

Ce script ajoute le paramètre `usbcore.autosuspend=-1` à la fin du fichier `/boot/extlinux/extlinux.conf`.

> Vérifiez que le chemin du fichier de configuration correspond à votre distribution (Jetson, etc.).

## Création de l'exécutable avec Nuitka

### Compilation locale

Pour compiler l'application en un exécutable autonome localement sur le Jetson, utilisez Nuitka :

```sh
uv run nuitka --standalone \
  --include-data-dir=config=config \
  --include-data-dir=templates=templates \
  --include-data-dir=static=static \
  --include-data-dir=db=db \
  --include-data-dir=logs=logs \
  --include-data-file=.venv/lib/python3.10/site-packages/yoctopuce/cdll/libyapi-aarch64.so=yoctopuce/cdll/libyapi-aarch64.so \
  --output-dir=dist \
  app.py
```

Le dossier `dist/app.dist/` contiendra l'exécutable et tous les fichiers nécessaires.

### Compilation automatique avec GitLab CI/CD

Pour compiler automatiquement l'exécutable ARM64 via **GitLab CI/CD** (sans avoir besoin du Jetson), consultez le guide complet : **[GITLAB_CI_BUILD.md](GITLAB_CI_BUILD.md)**

**Déclenchement rapide :**
```bash
# Via push
git push origin main

# Via tag (crée automatiquement une release)
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0

# Ou manuellement via l'interface GitLab CI/CD > Pipelines > Run Pipeline
```

L'exécutable compilé sera disponible dans les artefacts du pipeline, prêt à être déployé sur votre Jetson Orin NX.

**Prérequis :** Votre GitLab auto-hébergé doit avoir un Runner configuré avec Docker et les privilèges activés. Voir [GITLAB_CI_BUILD.md](GITLAB_CI_BUILD.md) pour les détails de configuration.  

## Collecte automatique de dataset

L'application embarque un système de collecte d'images passif et non-intrusif (`DatasetCollectionThread`) qui s'exécute en parallèle des flux vidéo sans générer de charge supplémentaire : il réutilise les frames déjà décodées, les détections YOLO déjà calculées et les masques MOG2 déjà appliqués par les threads d'inférence principaux.

### Activation

Dans `config/config.ini`, passer le flag à `true` :

```ini
DATASET_COLLECTION = true
```

### Paramètres de configuration

| Paramètre | Valeur par défaut | Description |
|---|---|---|
| `DATASET_COLLECTION` | `false` | Active / désactive la collecte |
| `DATASET_COLLECTION_INTERVAL` | `10` | Intervalle temporel (minutes) — stratégie 1 |
| `DATASET_COLLECTION_START_HOUR` | `5` | Heure de début de collecte |
| `DATASET_COLLECTION_END_HOUR` | `23` | Heure de fin de collecte |
| `DATASET_COLLECTION_MAX_PER_CLASS_PER_HOUR` | `30` | Quota max d'images par classe et par heure |
| `DATASET_OUTPUT_DIR` | `dataset` | Dossier de sortie |
| `DATASET_BG_ENABLED` | `true` | Active la stratégie 3 (fond statique) |
| `DATASET_BG_INTERVAL` | `30` | Intervalle pour les images de fond (minutes) |
| `DATASET_HARD_NEG_ENABLED` | `true` | Active la stratégie 4 (négatifs difficiles) |
| `DATASET_HARD_NEG_CONFIDENCE` | `0.35` | Seuil bas de confiance pour l'inférence secondaire |

### Stratégies de collecte

Quatre stratégies se déclenchent en cascade à chaque cycle :

| # | Nom | Condition | Label généré |
|---|---|---|---|
| 1 | `temporal` | Toutes les N minutes (plage horaire) | Labels YOLO des détections présentes |
| 2 | `event` | Détection active + délai 5 s + quota non atteint | Labels YOLO de l'événement |
| 3 | `background` | Aucune détection **et** aucun mouvement MOG2 | Fichier label vide (fond pur) |
| 4 | `hard_neg` | Mouvement MOG2 **sans** détection principale → ré-inférence à seuil bas | Fichier label vide (faux positif potentiel) |

> **Stratégie 3 — `background`** : capture des scènes statiques (poteaux, dalles, clôtures) qui servent à apprendre ce qu'il ne faut pas détecter.  
> **Stratégie 4 — `hard_neg`** : capture les cas où MOG2 détecte un changement (variation de luminosité, reflet) mais sans objet réel — typiquement les faux positifs de poteaux en contre-jour.

### Correspondance des classes

| ID dataset | Classe |
|---|---|
| `0` | `forklift` (chariot élévateur) |
| `1` | `driver` (conducteur) |
| `2` | `person` (piéton) |

### Structure de sortie

```
dataset/
├── images/
│   └── raw/
│       ├── cam0_20240115_143022_event.jpg
│       ├── cam0_20240115_143027_background.jpg
│       └── ...
├── labels/
│   └── raw/
│       ├── cam0_20240115_143022_event.txt   # YOLO format : class_id cx cy w h
│       ├── cam0_20240115_143027_background.txt  # vide — image négative
│       └── ...
├── train/images/  val/images/  test/images/
├── train/labels/  val/labels/  test/labels/
├── sampling_log.csv   # Historique complet des captures
└── dataset.yaml       # Configuration YOLO (nc=3, chemins)
```

### Flux de travail recommandé

1. **Collecter** : activer `DATASET_COLLECTION = true` pendant 1 à 5 jours de fonctionnement normal
2. **Vérifier les labels** : ouvrir les images dans [Label Studio](https://labelstud.io/) ou [Roboflow](https://roboflow.com/) et corriger les annotations erronées
3. **Découper en train/val/test** :
   ```sh
   uv run scripts/collect_dataset.py --split
   ```
   Répartition par défaut : 70 % train · 20 % val · 10 % test
4. **Fine-tuner YOLO** :
   ```sh
   yolo train data=dataset/dataset.yaml model=yolo11m.pt epochs=50 imgsz=640
   ```

> ⚠️ **Important** : ne pas exécuter `DatasetCollector` (mode autonome) en même temps que `app.py`. Utilisez exclusivement `DatasetCollectionThread` (intégré dans `app.py`) pour éviter de dupliquer les pipelines GStreamer, les appels YOLO et les détecteurs MOG2.

## Auteurs

- 4itec

## Licence

Ce projet est privé et réservé à un usage exclusif.

