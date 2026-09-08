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

# 2. Charger/récupérer la nouvelle image (§3.2 ou §3.3), puis pointer le nouveau tag
sudo sed -i 's|:v3\.0\.0-arm64|:<nouveau-tag>-arm64|' docker-compose-arm64.yml
grep -n 'image:' docker-compose-arm64.yml      # vérifier le tag effectivement référencé

# 3. Recréer le conteneur — config/, db/, detections/, logs/ sont préservés (bind-mounts)
sudo docker compose -f docker-compose-arm64.yml up -d
```

> **La version affichée dans l'IHM suit l'image automatiquement** : elle provient de la
> variable d'environnement `APP_VERSION`, injectée au build par la CI avec le tag Git
> (`ARG APP_VERSION` dans le `Dockerfile`) et non de `config/config.ini` — ce dernier est
> un bind-mount du site, figé au premier déploiement, qui resterait sur l'ancienne valeur.
> Aucune édition manuelle n'est donc nécessaire après une mise à jour d'image.
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

## 11. Alternative scriptée — `scripts/deploy-jetson.sh`

[`deploy-jetson.sh`](../../scripts/deploy-jetson.sh) automatise login + pull + amorçage de
`/data` + lancement, mais avec un **`docker run` dont les options divergent du fichier
compose** : il monte `/dev` en entier au lieu de la liste `devices:`, et n'applique ni
`ipc: host`, ni `runtime`/`deploy` GPU déclaratif, ni les montages `enctune`/`argus`.

**La référence de production est le fichier compose** (§9). `deploy-jetson.sh` reste utile
pour un déploiement rapide en mise au point ; ne pas mélanger les deux méthodes sur un même
boîtier (le conteneur créé par `docker run` n'est pas géré par `docker compose`).

---

## 12. Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| `unauthorized: authentication required` au `pull` | Deploy token expiré, révoqué ou mauvaise portée | Regénérer un token `read_registry`, refaire `docker login` |
| `no such host: registry.gitlab.4itec.ddns.net` | Boîtier hors ligne (état RUN normal) | Passer par `docker save`/`load` (§3.3) |
| `error gathering device information … /dev/video0` | Nœud vidéo absent | Commenter la ligne dans `devices:` (§8) |
| L'application s'arrête : `Licence invalide … destinée à la machine '…'` | Licence générée pour un autre `machine-id` | Regénérer la licence avec le `machine-id` du boîtier (§6) |
| L'application s'arrête au démarrage sans erreur de licence | `SAFECROSS_AUTH_USER`/`PASSWORD` absents de `.env` | Compléter `.env` (§5) |
| IHM accessible mais aucune détection | Serveur d'inférence arrêté, ou moteur `.engine` incompatible avec le BSP | `docker ps`, `curl http://127.0.0.1:8004/`, réexporter les moteurs (§7) |
| IHM inaccessible mais conteneur `healthy` | Caddy arrêté, ou UFW sans règle pour le sous-réseau de maintenance | `systemctl status caddy`, `sudo ufw status numbered` |
| Zones de sécurité perdues après une MAJ | Bind-mounts absents (conteneur lancé sans `-v /data/...`) | Relancer via le fichier compose ; restaurer `config/` depuis la sauvegarde |
| `nvidia` absent de `docker info` | `nvidia-container-toolkit` non configuré | `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker` |
| `apt` bloqué (`2 not fully installed`) | `postinst` de `nvidia-l4t-bootloader` (carte Seeed) | [install-system-deps.md](install-system-deps.md) § « Carte porteuse Seeed » |

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
