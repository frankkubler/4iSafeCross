# Installation sur machine de production — image Docker depuis le registry GitLab

> **Périmètre** : ce qu'il faut faire sur un boîtier **après le flash JetPack 7.2**
> ([flash-jetson-reserver-j4012-jetpack72.md](flash-jetson-reserver-j4012-jetpack72.md))
> et **avant le passage en état RUN** (`scripts/harden-run.sh`). Tout ce document
> s'exécute **à distance**, depuis le PC de maintenance : le gel des paquets firmware et
> l'installation de TigerVNC sont les deux seules étapes qui se font devant le boîtier.
> Cible : *reServer Industrial J4012* (Orin NX 16 Go), L4T r39.2, Ubuntu 24.04 arm64.
>
> L'application tourne **en conteneur** en production. L'image est construite par la CI
> GitLab et récupérée depuis le registry privé
> `registry.gitlab.4itec.ddns.net/frank-k/4isafecross`.

---

## 0. Chaîne complète d'un boîtier neuf

| Étape | Document |
|---|---|
| 1. Flash JetPack 7.2 + IP de maintenance | [flash-jetson-reserver-j4012-jetpack72.md](flash-jetson-reserver-j4012-jetpack72.md) |
| 2. Gel des paquets firmware (carte Seeed) — **avant tout apt** | [install-system-deps.md](install-system-deps.md) § « Carte porteuse Seeed » |
| 3. Accès de maintenance (TigerVNC + UFW) — *dernière étape sur site* | [scripts-deploiement.md](scripts-deploiement.md) § « `install_vnc_jetson.sh` » |
| 4. Matériel / OS (autosuspend, PoE, affichage, réseau caméras) | [scripts-deploiement.md](scripts-deploiement.md) § « Ordre d'installation recommandé » (étapes 3 à 6) |
| **5. Dépendances + serveurs d'inférence + déploiement du conteneur** | **ce document** |
| 6. IHM HTTPS (Caddy) + UFW | [scripts-deploiement.md](scripts-deploiement.md) § « IHM en HTTPS (Caddy) » |
| 7. Passage en RUN + attestation de recette | `scripts/harden-run.sh`, `CYBER_AUDIT.md` |
| 8. Mises à jour ultérieures / rollback | [maj-l4t-hors-ligne.md](maj-l4t-hors-ligne.md) |

---

## 1. Dépendances système

### 1.1 Ce qu'il faut installer — selon le mode d'exécution

Deux modes d'exécution existent, et **ils n'ont pas les mêmes prérequis** :

| Mode | Usage | Dépendances hôte |
|---|---|---|
| **Conteneur** (production) | Boîtier livré | **Docker + runtime NVIDIA uniquement.** GStreamer, PyGObject, CUDA, TensorRT sont **dans l'image** |
| **Sources** (développement, diagnostic) | Poste de dev, mise au point sur cible | GStreamer + PyGObject + `uv` sur l'hôte → [install-system-deps.md](install-system-deps.md) |

> N'installez **pas** la pile GStreamer/PyGObject de [install-system-deps.md](install-system-deps.md)
> sur un boîtier de production qui n'exécute que le conteneur : c'est de la surface
> d'attaque et des paquets à maintenir pour rien (`CS-123-03`).
> Les paquets `gst-inspect-1.0` restent utiles au diagnostic sur cible — le choix
> se documente au dossier de recette.

### 1.2 Geler les paquets firmware AVANT toute opération apt

La carte porteuse Seeed n'est pas reconnue par le payload updater NVIDIA : toute mise à
jour de `nvidia-l4t-bootloader` casse l'état dpkg du boîtier. Appliquer le gel décrit dans
[install-system-deps.md](install-system-deps.md) § « Carte porteuse Seeed » **avant** le
premier `apt install` :

```bash
sudo apt-mark hold nvidia-l4t-bootloader nvidia-l4t-bsp
sudo tee /etc/apt/preferences.d/10-nvidia-l4t-freeze <<'EOF'
Package: nvidia-l4t-bootloader nvidia-l4t-bsp nvidia-l4t-xusb-firmware
Pin: release *
Pin-Priority: -1
EOF
```

### 1.3 Docker, plugin Compose et runtime NVIDIA

JetPack fournit déjà `docker` et `nvidia-container-toolkit`. À compléter/vérifier :

```bash
# Plugin Compose v2 (commande « docker compose », sans tiret)
sudo apt install docker-compose-v2      # ou docker-compose-plugin selon le dépôt

# L'utilisateur d'exploitation doit pouvoir piloter Docker sans sudo
sudo usermod -aG docker "$USER"         # se déconnecter/reconnecter ensuite

# Docker démarre au boot (indispensable : c'est lui qui relance le conteneur)
sudo systemctl enable --now docker
```

Contrôles :

```bash
docker --version
docker compose version                  # v2.x attendu
docker info | grep -i runtimes          # doit lister « nvidia »
```

Si `nvidia` n'apparaît pas :

```bash
sudo apt install nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Test d'injection GPU dans un conteneur (le runtime doit exposer les nœuds Tegra et les
bibliothèques du BSP) :

```bash
sudo docker run --rm --runtime nvidia \
  registry.gitlab.4itec.ddns.net/frank-k/4isafecross:latest-arm64 \
  sh -c 'ls /dev/nvhost-gpu /dev/nvmap && ls /usr/lib/aarch64-linux-gnu/tegra | head -5'
```

> L'image `4isafecross` **ne contient pas de framework d'inférence** (ni torch, ni
> TensorRT) : la détection est déportée sur des conteneurs dédiés (§7). La validation GPU
> de bout en bout se fait donc sur ces conteneurs et par le décodage NVDEC des flux
> caméras (§9).

> **Pare-feu** : le conteneur tourne en `network_mode: host`. Les règles UFW posées par
> `install_vnc_jetson.sh` s'appliquent donc normalement — on évite le piège classique du
> réseau `bridge`, où Docker court-circuite UFW en écrivant directement dans `iptables`.
> Ne pas basculer ce service en mode `bridge` avec `ports:` sans revoir le filtrage.

---

## 2. Arborescence de déploiement sur le boîtier

`docker-compose-arm64.yml` référence deux chemins **relatifs** (`.env` et `./licenses`) :
la commande `docker compose` doit donc toujours être lancée depuis le répertoire de
déploiement. Convention retenue :

```
/opt/4isafecross/                     # répertoire de déploiement (root:root, 750)
├── docker-compose-arm64.yml          # copié depuis le dépôt
├── .env                              # secrets — chmod 600, JAMAIS versionné
└── licenses/
    ├── 4isafecross.lic               # licence liée au machine-id du boîtier
    ├── public_key.pem
    ├── license_state.json            # créés/mis à jour par l'application
    └── license_state.key

/data/4isafecross/                    # état mutable, survit aux MAJ d'image
├── config/    ├── db/    ├── detections/    ├── dataset/    └── logs/
```

Mise en place :

```bash
sudo mkdir -p /opt/4isafecross/licenses
sudo chmod 750 /opt/4isafecross
# depuis le PC de maintenance :
#   scp docker-compose-arm64.yml user-4itec@192.168.3.122:/tmp/
sudo cp /tmp/docker-compose-arm64.yml /opt/4isafecross/

# Le fichier du dépôt pointe `latest-arm64` : le figer sur le tag de version livré
sudo sed -i 's|:latest-arm64|:v3.0.0-arm64|' /opt/4isafecross/docker-compose-arm64.yml
grep -n 'image:' /opt/4isafecross/docker-compose-arm64.yml
```

> Le dépôt Git **n'a pas à être cloné** sur un boîtier de production : seuls le fichier
> compose, `.env` et `licenses/` sont nécessaires. Un clone ne se justifie qu'en mise au
> point (exécution depuis les sources).

---

## 3. Récupérer l'image depuis le registry GitLab

### 3.1 Tags publiés par la CI

| Contexte | Tag |
|---|---|
| Tag Git (livraison) | `<tag>-arm64` **et** `latest-arm64` |
| Branche `main` | `latest-arm64` |
| Autre branche | `<slug-de-branche>-arm64` |
| Toute exécution | `<sha-court>-arm64` |

**En production, on déploie un tag de version figé** (`v3.0.0-arm64`), jamais `latest-arm64` :
`latest` rend le parc non reproductible et casse l'exigence d'identité de version
(`CS-1141-01`). `latest-arm64` reste acceptable en mise au point.

### 3.2 Mode connecté (mise au point, fenêtre de connectivité déclarée)

Créer un **deploy token GitLab** dédié au parc, portée **`read_registry` uniquement**
(*Settings → Repository → Deploy tokens*) — jamais un compte personnel ni un token
`write_registry`.

```bash
cd /opt/4isafecross

# Connexion (le token est lu sur stdin, il n'apparaît pas dans l'historique shell)
read -rsp "Deploy token: " GL_TOKEN; echo
echo "$GL_TOKEN" | sudo docker login registry.gitlab.4itec.ddns.net \
    -u <nom-du-deploy-token> --password-stdin
unset GL_TOKEN

sudo docker pull registry.gitlab.4itec.ddns.net/frank-k/4isafecross:v3.0.0-arm64

# Relever et consigner le digest — c'est LUI qui identifie la version déployée
sudo docker image inspect --format '{{index .RepoDigests 0}}' \
    registry.gitlab.4itec.ddns.net/frank-k/4isafecross:v3.0.0-arm64
```

> **Après le déploiement, se déconnecter du registry** :
> ```bash
> sudo docker logout registry.gitlab.4itec.ddns.net
> ```
> `~/.docker/config.json` (et `/root/.docker/config.json`) stocke le token en **base64,
> pas chiffré** : un boîtier livré ne doit conserver aucun accès au registry
> (`CS-127-01/02`). À vérifier à la recette :
> ```bash
> sudo grep -c auths /root/.docker/config.json 2>/dev/null || echo "aucun credential"
> ```

### 3.3 Mode hors ligne (RUN — le boîtier n'a aucun accès Internet)

L'image est transférée par support amovible, comme les paquets système
([maj-l4t-hors-ligne.md](maj-l4t-hors-ligne.md) §5) :

```bash
# Sur la machine relais 4itec (connectée)
docker pull registry.gitlab.4itec.ddns.net/frank-k/4isafecross:v3.0.0-arm64
docker save registry.gitlab.4itec.ddns.net/frank-k/4isafecross:v3.0.0-arm64 \
  -o 4isafecross_v3.0.0-arm64.tar
sha256sum 4isafecross_v3.0.0-arm64.tar > 4isafecross_v3.0.0-arm64.tar.sha256

# Sur le boîtier
sha256sum -c /media/<support>/4isafecross_v3.0.0-arm64.tar.sha256   # doit être OK
sudo docker load -i /media/<support>/4isafecross_v3.0.0-arm64.tar
sudo docker images | grep 4isafecross
```

Conserver le `.tar` de la **version précédente** sur le support : c'est le rollback de la
couche applicative ([maj-l4t-hors-ligne.md](maj-l4t-hors-ligne.md) §6.1).

---

## 4. Amorcer l'état persistant `/data/4isafecross`

`config/` et `db/` sont des bind-mounts. Un montage sur un répertoire hôte **vide masque
le contenu de l'image** : sans amorçage, `config/` est vide et l'application ne démarre pas.

```bash
IMAGE=registry.gitlab.4itec.ddns.net/frank-k/4isafecross:v3.0.0-arm64

sudo mkdir -p /data/4isafecross/{config,db,detections,dataset,logs}

# Copie de la configuration et de la base par défaut depuis l'image (1re fois seulement)
sudo docker run --rm --entrypoint tar "$IMAGE" -C /app -c config db \
  | sudo tar -C /data/4isafecross -x

ls /data/4isafecross/config     # doit contenir config.ini et les fichiers de zones
```

Puis **renseigner `config/config.ini`** (adresses RTSP des caméras, zones, seuils) avant
exploitation. Ne jamais réexécuter cette copie sur un boîtier déjà en service : elle
écraserait la géométrie des zones du site.

---

## 5. Fichier `.env` (obligatoire)

Le conteneur **refuse de démarrer** sans `SAFECROSS_AUTH_USER` / `SAFECROSS_AUTH_PASSWORD`
(`CS-1144-01` : l'IHM permet de modifier les zones de sécurité et de couper la détection).

```bash
sudo cp /tmp/.env.example /opt/4isafecross/.env
sudo nano /opt/4isafecross/.env      # RTSP_LOGIN/PASSWORD + SAFECROSS_AUTH_USER/PASSWORD
sudo chmod 600 /opt/4isafecross/.env
sudo chown root:root /opt/4isafecross/.env
```

Mots de passe **uniques par boîtier**, stockés au coffre-fort 4itec. `TELEGRAM_*` n'est
renseigné qu'en mise au point (retiré par `harden-run.sh` à la livraison).

---

## 6. Licence

L'application vérifie une licence RSA au démarrage et **s'arrête** si elle est absente ou
invalide. La licence est liée au `/etc/machine-id` du boîtier (monté en lecture seule dans
le conteneur).

```bash
# 1. Relever l'identifiant machine du boîtier
cat /etc/machine-id

# 2. Générer la licence avec 4icheck_license_manager (poste 4itec), puis la déposer
sudo cp /tmp/4isafecross.lic /opt/4isafecross/licenses/4isafecross.lic
sudo chmod 640 /opt/4isafecross/licenses/4isafecross.lic
```

Chemin lu par l'application : `licenses/4isafecross.lic` relatif à `/app`
(`src/core/bootstrap.py:112`), surchargeable par `SAFECROSS_LICENSE`. Le répertoire doit
rester **inscriptible** par le conteneur : `license_state.json` / `license_state.key`
(anti-retour d'horloge) y sont réécrits à chaque démarrage.

---

## 7. Serveurs d'inférence (conteneurs séparés)

4iSafeCross **ne fait pas l'inférence lui-même** : il interroge en HTTP, sur la boucle
locale, des serveurs de détection déployés dans leurs propres conteneurs sur le même
boîtier.

| Serveur | Endpoint attendu | Clé `config.ini` | Dépôt |
|---|---|---|---|
| RF-DETR | `http://127.0.0.1:8002` | `URL_RFDETR` (`[APP]`) | [inf_jetson_rf-detr](https://github.com/4itec-org/inf_jetson_rf-detr) |
| YOLO | `http://127.0.0.1:8004` | `URL_YOLO` (`[APP]`) | [inf_jetson_yolo](https://github.com/4itec-org/inf_jetson_yolo) |

Points d'attention :

- Ces conteneurs sont déployés **avant** 4isafecross, en `network_mode: host` et
  `runtime: nvidia`, et doivent écouter sur `127.0.0.1` (jamais sur `0.0.0.0` : le port
  serait exposé au segment caméras et au segment maintenance).
- Les **moteurs TensorRT (`.engine`) sont liés à la version du BSP** : un moteur exporté
  sur une autre version de JetPack/TensorRT ne se charge pas. Après toute montée de
  version L4T, les moteurs doivent être **réexportés** sur la cible.
- Suivre les procédures de déploiement propres à chaque dépôt (Dockerfile, tags d'image,
  export des moteurs) — elles ne sont pas dupliquées ici.

Contrôle avant de démarrer 4isafecross :

```bash
sudo docker ps --format '{{.Names}}\t{{.Status}}'      # les serveurs doivent être Up
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8004/
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8002/
sudo ss -lntp | grep -E ':(8002|8004)'                 # doit être lié à 127.0.0.1
```

---

## 8. Contrôles à faire AVANT le premier `up`

`docker-compose-arm64.yml` déclare des chemins hôte qui doivent exister, sans quoi le
démarrage échoue avec un message peu explicite :

```bash
ls -l /dev/video0 /dev/video1     # section « devices: » du compose
ls -l /etc/enctune.conf           # monté en lecture seule
ls -ld /tmp/argus_socket          # socket caméras MIPI (nvargus)
```

| Chemin | Si absent |
|---|---|
| `/dev/video0`, `/dev/video1` | **Commenter les lignes correspondantes** de `devices:` — le boîtier n'utilise que des caméras IP/RTSP, ces nœuds n'existent que si un capteur USB/MIPI est branché. Sinon : `error gathering device information` au démarrage |
| `/etc/enctune.conf` | `sudo touch /etc/enctune.conf` (Docker créerait sinon un **répertoire** à la place) |
| `/tmp/argus_socket` | Inutile sans caméra MIPI CSI — la ligne peut être commentée |

Vérifier aussi qu'aucun autre service n'occupe le port `5050` :

```bash
sudo ss -lntp | grep 5050
systemctl is-enabled 4isafecross.service 2>/dev/null
```

> ⚠️ **`4isafecross.service` (exécution depuis les sources/binaire) et le conteneur sont
> mutuellement exclusifs** : les deux servent l'IHM sur `127.0.0.1:5050`. Sur un boîtier
> déployé en Docker, `4isafecross.service` doit être **désactivé** :
> `sudo systemctl disable --now 4isafecross.service`.

---

## 9. Démarrage

```bash
cd /opt/4isafecross
sudo docker compose -f docker-compose-arm64.yml up -d

# État et santé (healthcheck /health toutes les 30 s)
sudo docker compose -f docker-compose-arm64.yml ps
sudo docker inspect --format '{{.State.Health.Status}}' 4isafecross   # → healthy

# Journaux applicatifs
sudo docker compose -f docker-compose-arm64.yml logs -f --tail=100
```

Le conteneur porte `restart: unless-stopped` : avec `docker.service` activé au boot, il
redémarre automatiquement après une coupure secteur. **Aucune unité systemd dédiée n'est
nécessaire.**

### Vérifications fonctionnelles

```bash
curl -s http://127.0.0.1:5050/health                 # 200
curl -s http://127.0.0.1:5050/failsafe_status        # état du relais fail-safe
curl -k -u "$SAFECROSS_AUTH_USER" https://192.168.3.122/   # IHM via Caddy (depuis le PC de maintenance)
```

Puis, avant de refermer l'intervention : **une acquisition caméra réelle** (flux visible
dans l'IHM, décodage NVDEC via `nvv4l2decoder`) et **un cycle d'alerte relais** complet.

---

## 10. Mise à jour de l'image applicative

```bash
cd /opt/4isafecross

# 1. Sauvegarder l'image courante (rollback) — voir maj-l4t-hors-ligne.md §6.4
sudo docker save "$(sudo docker inspect --format '{{.Config.Image}}' 4isafecross)" \
  -o /media/<support>/backup/4isafecross_<tag_courant>-arm64.tar

# 2. Recopier le fichier compose DU DÉPÔT à la version livrée, puis pointer le tag.
#    Une image seule ne suffit pas : montages, devices et variables évoluent avec
#    elle (ex. v3.0.2+ : /dev/bus/usb pour la carte relais). Le 2026-09-14, une image
#    à jour lancée avec un compose ancien a laissé la carte relais injoignable après
#    la première ré-énumération USB, sans aucune erreur au démarrage.
sudo cp docker-compose-arm64.yml docker-compose-arm64.yml.bak-$(date +%F)
sudo cp /tmp/docker-compose-arm64.yml docker-compose-arm64.yml     # copie scp depuis le dépôt (§2)
sudo sed -i 's|:latest-arm64|:<nouveau-tag>-arm64|' docker-compose-arm64.yml
grep -n 'image:' docker-compose-arm64.yml      # vérifier le tag effectivement référencé
sudo docker compose -f docker-compose-arm64.yml config >/dev/null && echo "compose valide"
diff docker-compose-arm64.yml.bak-$(date +%F) docker-compose-arm64.yml   # relire ce qui change

# 3. Recréer le conteneur — config/, db/, detections/, logs/ sont préservés (bind-mounts)
sudo docker compose -f docker-compose-arm64.yml up -d
```

> **La version affichée dans l'IHM suit l'image automatiquement** : elle provient de la
> variable d'environnement `APP_VERSION`, injectée au build par la CI avec le tag Git
> (`ARG APP_VERSION` dans le `Dockerfile`). En exécution depuis les sources, elle est lue
> dans `pyproject.toml` (`[project] version`). Elle n'est **jamais** lue dans
> `config/config.ini` : ce fichier est un bind-mount du site, figé au premier
> déploiement, qui resterait sur l'ancienne valeur. Aucune édition manuelle n'est donc
> nécessaire après une mise à jour d'image ; une clé `APP_VERSION` résiduelle dans le
> `config.ini` d'un boîtier déjà déployé est simplement ignorée.
>
> Relever la version réellement déployée, sans passer par l'IHM :
> ```bash
> sudo docker inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' 4isafecross
> sudo docker exec 4isafecross printenv APP_VERSION
> ```

Rollback : remettre l'ancien tag dans le fichier compose et relancer `up -d`.
Consigner l'opération au registre des mises à jour
([maj-l4t-hors-ligne.md](maj-l4t-hors-ligne.md) §7).

---

## 11. Déploiement scripté — `scripts/deploy-jetson.sh`

[`deploy-jetson.sh`](../../scripts/deploy-jetson.sh) **pilote `docker compose`** : il
enchaîne exactement les gestes des § 3.2, 4, 5 et 9 — login registry (jeton lu sur stdin),
`compose pull`, amorçage de `/data/4isafecross` au premier déploiement, contrôle de
`.env`, `compose up -d`, attente du healthcheck, relevé du digest, `docker logout`.
Le conteneur qu'il produit **est** celui du fichier compose : mêmes périphériques, mêmes
montages, même rotation de logs. Il n'y a plus deux méthodes, il y en a une, scriptée.

```bash
cd /opt/4isafecross
./scripts/deploy-jetson.sh v3.0.1-arm64            # connecté (mise au point)
OFFLINE=1 ./scripts/deploy-jetson.sh v3.0.1-arm64  # boîtier livré, image chargée par docker load (§ 3.3)
```

Le tag déployé est écrit dans `.env` (`SAFECROSS_TAG`), que `docker compose` lit
automatiquement : les `compose ps` / `logs` / `up` ultérieurs visent la même image. Un
conteneur `4isafecross` hérité d'un ancien `docker run` est retiré au passage, sinon il
bloquerait `compose up` par collision de nom.

---

## 12. Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| `unauthorized: authentication required` au `pull` | Deploy token expiré, révoqué ou mauvaise portée | Regénérer un token `read_registry`, refaire `docker login` |
| `no such host: registry.gitlab.4itec.ddns.net` | Boîtier hors ligne (état RUN normal) | Passer par `docker save`/`load` (§3.3) |
| Détections et zones affichées sur la **mauvaise caméra** (la vue « Camera 1 » montre la .61 avec les zones de `cam0`), relais déclenchés à contretemps | Image antérieure au correctif d'ordre des caméras : l'index suivait l'ordre de réponse RTSP au démarrage, pas `config.ini` | Déployer une image récente ; vérifier le libellé `Camera N — <hôte>` de chaque vue, et le log `Caméras (index = position dans config.ini)`. Si une zone a été enregistrée sous le mauvais `_cam` pendant un tel démarrage, la redessiner ([failsafe-mode.md](../features/failsafe-mode.md), « Caméra absente au démarrage ») |
| Alertes affichées mais **relais muets** ; log `MODULE RELAIS INJOIGNABLE` ; `/health` en 503 ; `dmesg` : `usb 1-2.3: USB disconnect` toutes les 2 s tant que le conteneur tourne | La carte Yoctopuce a été ré-énumérée (nouveau numéro USB) et le conteneur ne voit pas le nouveau nœud `/dev/bus/usb/001/NNN` : la bibliothèque la réinitialise en boucle. Image antérieure au montage `/dev/bus/usb` ou compose modifié | Vérifier que `docker exec 4isafecross ls /dev/bus/usb/001/` liste le même numéro que `lsusb \| grep 24e0` ; sinon rétablir le montage `/dev/bus/usb:/dev/bus/usb` dans le compose et relancer. Détails : [failsafe-mode.md](../features/failsafe-mode.md), Scénario 6 |
| `error gathering device information … /dev/video0` | Nœud vidéo absent | Commenter la ligne dans `devices:` (§8) |
| L'application s'arrête : `Licence invalide … destinée à la machine '…'` | Licence générée pour un autre `machine-id` | Regénérer la licence avec le `machine-id` du boîtier (§6) |
| L'application s'arrête au démarrage sans erreur de licence | `SAFECROSS_AUTH_USER`/`PASSWORD` absents de `.env` | Compléter `.env` (§5) |
| IHM accessible mais aucune détection | Serveur d'inférence arrêté, ou moteur `.engine` incompatible avec le BSP | `docker ps`, `curl http://127.0.0.1:8004/`, réexporter les moteurs (§7) |
| IHM inaccessible mais conteneur `healthy` | Caddy arrêté, ou UFW sans règle pour le sous-réseau de maintenance | `systemctl status caddy`, `sudo ufw status numbered` |
| Zones de sécurité perdues après une MAJ | Bind-mounts absents (conteneur lancé sans `-v /data/...`) | Relancer via le fichier compose ; restaurer `config/` depuis la sauvegarde |
| `nvidia` absent de `docker info` | `nvidia-container-toolkit` non configuré | `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker` |
| `apt` bloqué (`2 not fully installed`) | `postinst` de `nvidia-l4t-bootloader` (carte Seeed) | [install-system-deps.md](install-system-deps.md) § « Carte porteuse Seeed » |
| `Aucune image reçue pour rtsp://… en 15s après la mise en PLAYING` en boucle, `/health` → `cameras_online: 0` | Le port 554 accepte la connexion TCP mais aucun flux RTSP n'est servi (caméra en initialisation, mauvais chemin de flux, autre équipement sur l'IP) | Sonde GStreamer hors application (§ 12.2) ; vérifier `STREAM` et les identifiants dans `/data/4isafecross/config/config.ini` |
| `MODULE RELAIS INJOIGNABLE` en boucle alors que `dmesg` montre la carte revenir (`New USB device found`) | Hot-plug invisible dans le conteneur : `/run/udev` non monté (libyapi → libusb/libudev), ou `/dev/bus/usb` non monté (nœud figé) | Les deux montages sont dans le compose du dépôt — recopier le compose et **recréer** le conteneur ; vérifier `docker exec 4isafecross ls /run/udev /dev/bus/usb/001/` |
| `createContainer hook #2: exit status 2` + `panic: slice bounds out of range` dans `cudacompat` | Hook CDI `cudacompat` du container-toolkit : il parse l'en-tête ELF de `/usr/local/cuda/compat` de l'image et panique | Voir § 12.1 ci-dessous — image ≥ `v3.0.1-arm64`, ou désactivation du hook |


### 12.1 Panique du hook `cudacompat` au démarrage du conteneur

```
Error response from daemon: failed to create task for container: ...
error running createContainer hook #2: exit status 2, stderr: panic: runtime error:
slice bounds out of range [:73] with capacity 71
  .../nvidia-cdi-hook/cudacompat.GetCUDACompatElfHeaderFromReader
```

**Cause.** L'image applicative dérive de `nvcr.io/nvidia/cuda:13.2.1-runtime-ubuntu24.04`,
qui embarque un répertoire de *forward compatibility* CUDA. **Sur arm64 il s'appelle
`/usr/local/cuda/compat_orin`**, et non `compat` comme sur sbsa/x86 — c'est le piège de
cette panne. Le container-toolkit le détecte et lance le hook `cudacompat`, qui lit
l'en-tête ELF de la bibliothèque pour comparer sa version à celle du driver hôte. Ce
parsing échoue et le hook **panique sans être rattrapé** : la création du conteneur est
refusée, l'application n'est jamais lancée.

Ces bibliothèques ne servent à rien ici : le driver CUDA est injecté depuis le BSP L4T de
l'hôte (`/etc/nvidia-container-runtime/host-files-for-container.d/drivers.csv`), et cette
image n'embarque aucun framework d'inférence. L'hôte, lui, n'a pas de répertoire de
compat — le fichier fautif vient donc bien de l'image.

**Correctif retenu.** Les images `v3.0.1-arm64` et suivantes suppriment le répertoire à la
construction — rien à faire sur le boîtier, il suffit de déployer cette version.

**Contournement sur une image antérieure** (`v3.0.0-arm64`) : refabriquer localement
l'image sans le répertoire fautif. Le build est natif sur le boîtier, donc quasi
instantané (une seule couche de suppression).

```bash
cd /opt/4isafecross

# Le build ne doit PAS passer par le runtime nvidia, sinon il déclenche le même hook
docker info | grep -i 'Default Runtime'      # doit indiquer « runc »

# Dockerfile sur stdin, sans contexte de build : /opt/4isafecross (avec .env et
# licenses/) n'est pas envoyé au daemon.
printf 'FROM registry.gitlab.4itec.ddns.net/frank-k/4isafecross:v3.0.0-arm64\nRUN rm -rf /usr/local/cuda/compat*\n' \
  | sudo docker build -t 4isafecross:v3.0.0-nocompat -

sudo sed -i 's|image: .*4isafecross:.*|image: 4isafecross:v3.0.0-nocompat|' docker-compose-arm64.yml
sudo docker compose -f docker-compose-arm64.yml up -d
```

Si `Default Runtime` vaut `nvidia`, le `RUN` échouerait de la même façon : passer alors
par un conteneur explicitement en `runc`, puis figer le résultat.

```bash
sudo docker run --runtime runc --name fixcompat --entrypoint rm \
  registry.gitlab.4itec.ddns.net/frank-k/4isafecross:v3.0.0-arm64 -rf /usr/local/cuda/compat_orin
sudo docker commit --change 'ENTRYPOINT []' \
  --change 'CMD ["/app/.venv/bin/python","run.py"]' \
  fixcompat 4isafecross:v3.0.0-nocompat
sudo docker rm fixcompat
```

> ⚠️ **Deux contournements qui ne marchent PAS** (vérifiés sur toolkit 1.19.1 /
> JetPack 7.2, à ne pas retenter) :
>
> - `nvidia-ctk config --in-place --set features.disable-cuda-compat-lib-hook=true`
>   puis redémarrage de Docker : la clé est bien écrite dans
>   `/etc/nvidia-container-runtime/config.toml`, le hook s'exécute quand même. Avec
>   `mode = "auto"` sur Jetson, la spécification CDI est construite à la volée par le
>   runtime et il n'existe aucun `/etc/cdi/nvidia.yaml` à régénérer (seul un
>   `nvidia-pva.yaml` est présent).
> - Masquer le répertoire par un `tmpfs` dans le fichier compose : sans effet. Le hook
>   n'ouvre pas le chemin dans le namespace de montage du conteneur, mais le rootfs par
>   son chemin sur l'hôte (`root.path` de l'état OCI) — le montage ne le masque donc pas.
>
> - Supprimer `/usr/local/cuda/compat` **sans le glob** : sans effet, ce chemin n'existe
>   pas sur arm64. Vérifier le nom réel avant tout, il varie selon l'architecture :
>   `docker run --rm --runtime runc --entrypoint ls <image> -la /usr/local/cuda/`
>
> Le répertoire doit réellement disparaître **de l'image**, ce que fait la `v3.0.1`.

Pour confirmer le diagnostic, l'image démarre normalement **sans** le runtime NVIDIA —
le hook n'est alors pas appelé :

```bash
sudo docker run --rm --entrypoint ls \
  registry.gitlab.4itec.ddns.net/frank-k/4isafecross:v3.0.0-arm64 -la /usr/local/cuda/
```


### 12.2 Le port RTSP répond mais aucune image n'arrive

Symptôme : le conteneur est `healthy`, l'IHM répond, `/health` renvoie
`cameras_online: 0` avec `cameras_total` > 0, et les logs bouclent sur
`Aucune image reçue pour rtsp://… en 15s après la mise en PLAYING`.

**Pourquoi l'application démarre quand même.** Le test de démarrage
(`_wait_for_rtsp_streams`) et le test de reconnexion sont un simple `connect()` TCP sur le
port 554 : ils prouvent qu'un équipement écoute, pas qu'un flux RTSP est servi ni décodable.
Une caméra en cours d'initialisation, un NVR, ou tout matériel ayant récupéré l'IP passent
ce test. Les deux hôtes sont alors retenus dans `state.cam_ids`, l'IHM démarre, et chaque
thread caméra relance son pipeline en boucle — il rattrapera le flux **sans redémarrage** dès
qu'il sera réellement servi.

**Trancher en 20 s, sans toucher à l'application** — la sonde [scripts/rtsp_probe.py](../../scripts/rtsp_probe.py)
lance exactement le pipeline de production (même URL, même chaîne GStreamer) et remonte ce
que l'application ne loggue pas :

```bash
docker exec -i 4isafecross /app/.venv/bin/python - < scripts/rtsp_probe.py
```

| Sortie de la sonde | Cause | Suite |
|---|---|---|
| `BUS ERROR +12.5s : Could not read from resource … Could not receive message` puis `AUCUNE IMAGE` | TCP accepté, aucun dialogue RTSP derrière | Côté caméra/réseau : caméra pas encore en service, ou autre équipement sur l'IP |
| `BUS ERROR` immédiat `401 Unauthorized` / `404 Not Found` | Identifiants, ou `STREAM` (chemin du flux) faux | Corriger `[RTSP]` dans `/data/4isafecross/config/config.ini`, puis `docker compose restart` |
| `PREMIÈRE IMAGE après N s` avec N > `RTSP_FIRST_FRAME_TIMEOUT` | Caméra lente à négocier / GOP long | Augmenter `RTSP_FIRST_FRAME_TIMEOUT` dans `[APP]` (15 s par défaut) |
| `PREMIÈRE IMAGE après N s`, N < seuil, débit > 0 | Le flux fonctionne | Le problème est ailleurs (inférence, zones) : `docker logs`, `/failsafe_status` |

> Toute modification de `[RTSP]` (hôtes, identifiants, chemin de flux) exige un redémarrage
> du conteneur : la liste des caméras est construite une seule fois au boot.

---

## 13. Checklist de recette (à joindre au dossier)

- [ ] JetPack 7.2 / L4T r39.2 — empreinte de l'image de flash consignée (`CS-1141-01`)
- [ ] Paquets `nvidia-l4t-bootloader` / `nvidia-l4t-bsp` gelés, `apt-get check` OK
- [ ] `docker info` → runtime `nvidia` présent ; `docker.service` activé au boot
- [ ] Image déployée par **digest** consigné (pas seulement le tag)
- [ ] `docker logout` effectué — aucun credential registry dans `/root/.docker/config.json`
- [ ] `.env` en `600`, mots de passe uniques au boîtier, déposés au coffre-fort
- [ ] Licence valide, liée au `machine-id` du boîtier
- [ ] `/data/4isafecross/{config,db,logs}` amorcés et peuplés ; `config.ini` renseigné
- [ ] `4isafecross.service` désactivé (déploiement conteneur)
- [ ] Serveurs d'inférence démarrés, liés à `127.0.0.1` (`8002` / `8004`)
- [ ] Conteneur `healthy`, IHM HTTPS accessible depuis le seul sous-réseau de maintenance
- [ ] Acquisition caméra réelle + cycle d'alerte relais vérifiés
- [ ] `harden-run.sh` exécuté, sortie jointe au dossier de recette

---

## 14. Références

- [flash-jetson-reserver-j4012-jetpack72.md](flash-jetson-reserver-j4012-jetpack72.md) — flash initial
- [install-system-deps.md](install-system-deps.md) — dépendances GStreamer/PyGObject (exécution depuis les sources) + gel firmware Seeed
- [scripts-deploiement.md](scripts-deploiement.md) — services systemd, VNC, UFW, Caddy, ordre d'installation
- [maj-l4t-hors-ligne.md](maj-l4t-hors-ligne.md) — mises à jour hors ligne, rollback, registre
- `CYBER_AUDIT.md` — exigences Stellantis référencées ici
