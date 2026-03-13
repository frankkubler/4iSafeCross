# 4iSafeCross

**4iSafeCross** est une application de supervision et de détection intelligente pour caméras de surveillance, intégrant la gestion de flux RTSP, la détection d'événements par IA, l'alerte Telegram, et une interface web de contrôle en temps réel, sur machine Nvidia Jetson Orin NX [reServer Indutrial J4012](https://wiki.seeedstudio.com/reServer_Industrial_Getting_Started/)

## Fonctionnalités principales

- **Supervision multi-caméras** (RTSP/IP)
- **Détection d'événements** (mouvement, objets, etc.) via modèles IA (YOLO, RF-DETR)
- **Alertes Telegram** automatiques avec capture d'image
- **Contrôle des relais Yoctopuce** pour actionneurs physiques
- **Interface web** (Flask) : visualisation, activation/désactivation des flux/détections, réglage des seuils, galerie des détections, panneau debug
- **Gestion multi-thread** pour l’inférence et le streaming
- **Statistiques système** : RAM, CPU, disque, IP, état du service

## Structure du projet

```
.

├── app.py                # Serveur principal Flask
├── pyproject.toml        # Métadonnées et dépendances
├── requirements.txt      # Dépendances Python
├── uv.lock               # Fichier de verrouillage uv
├── README.md             # Documentation
├── config/
│   ├── config.ini        # Configuration principale
│   └── zones.ini         # Définition des zones de détection
├── db/
│   └── detections.db     # Base de données des détections
├── detections/           # Captures d'images des détections
├── logs/                 # Logs applicatifs
├── scripts/              # Scripts utilitaires et automation
├── src/                  # Code source Python (modules, gestion, IA, etc.)
├── static/               # Fichiers statiques (CSS, JS, images)
├── templates/
│   └── index.html        # Interface web principale
├── utils/                # Fonctions utilitaires
└── __pycache__/          # Fichiers compilés Python
```

## Installation

### Prérequis

Le PC jetson doit être flashé avec la [méthode 1](https://wiki.seeedstudio.com/reServer_Industrial_Getting_Started/) avec le JetPack 6.1 L4T 36.4 (Attention : le flash doit se faire avec un PC Ubuntu 22.04 (la même identique à celle du JetPack)) 

Le serveur d'inférence doit être installé dans un docker [inf_jetson_rf-detr](https://github.com/4itec-org/inf_jetson_rf-detr)

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
- Identifiants RTSP (`LOGIN`, `PASSWORD`, `HOST`, etc. dans la section [RTSP])
- Seuils de détection (`MOTIONTRESHOLD`, `INF_THRESHOLD` dans la section [APP])
- Token Telegram (`TOKEN`, `CHAT_ID` dans la section [TELEGRAM])

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
  - Lance automatiquement l’application via le script `4isafecross.sh` au démarrage.
  - Gère les logs dans le dossier `logs/`.
  - Exemple d’installation :
    ```sh
    sudo cp 4isafecross.service /etc/systemd/system/
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

## Définition et schéma des zones de détection

Les zones de détection pour chaque caméra sont configurables dans le fichier [`config/zones.ini`](config/zones.ini). Chaque zone peut être définie comme un rectangle (rect) ou un polygone (polygon), selon la forme souhaitée et la résolution de chaque caméra, sans toucher au code Python.

**Exemple de format dans zones.ini** :

```ini
[zone1_cam0]
rect = x1,y1,x2,y2
color = 255,0,255

[zone2_cam0]
polygon = (x1,y1)(x2,y2)(x3,y3)...
color = 0,255,255
```

### Exemple de schéma de zones

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

