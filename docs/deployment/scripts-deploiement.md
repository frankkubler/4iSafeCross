# Scripts et services de déploiement — 4iSafeCross

Ce document décrit l'ensemble des scripts Bash et fichiers systemd fournis dans le
dossier [`scripts/`](../../scripts/) pour automatiser le déploiement, la
configuration matérielle et la maintenance du boîtier Jetson.

---

## Vue d'ensemble

| Fichier | Type | Rôle |
|---|---|---|
| [`4isafecross.service`](../../scripts/4isafecross.service) | systemd | Démarre l'application au boot (binaire ou Python) |
| [`set-poe-gpio.service`](../../scripts/set-poe-gpio.service) | systemd | Active l'alimentation PoE (GPIO) au boot |
| [`check-dummy-display.service`](../../scripts/check-dummy-display.service) | systemd | Bascule écran réel / virtuel selon présence HDMI |
| [`4isafecross.sh`](../../scripts/4isafecross.sh) | Bash | Lance l'app manuellement (waitress-serve + uv) |
| [`deploy-jetson.sh`](../../scripts/deploy-jetson.sh) | Bash | Déploie l'image Docker depuis le registry GitLab |
| [`disable-autosuspend.sh`](../../scripts/disable-autosuspend.sh) | Bash | Désactive l'USB autosuspend (Yoctopuce) |
| [`set_poe_gpio.sh`](../../scripts/set_poe_gpio.sh) | Bash | Positionne le GPIO PoE (utilisé par le service) |
| [`switch-display.sh`](../../scripts/switch-display.sh) | Bash | Logique de détection HDMI / activation dummy Xorg |
| [`install_xrdp_jetson.sh`](../../scripts/install_xrdp_jetson.sh) | Bash | TigerVNC + XFCE + UFW + Fail2ban sur Jetson |
| [`4isafecross.logrotate`](../../scripts/4isafecross.logrotate) | logrotate | Rotation des logs applicatifs (10 Mo × 5) |

---

## Services systemd

### `4isafecross.service`

Lance automatiquement l'application au démarrage, après `network.target` et
`systemd-udev-settle.service` (périphériques USB prêts).

- Charge les variables d'environnement depuis `.env` via `EnvironmentFile`
  (credentials Telegram, etc.).
- Redémarre automatiquement en cas d'échec (`Restart=always`, délai 3 s).
- Écrit les logs dans `logs/service_stdout.log` et `logs/service_stderr.log`.

**Deux modes disponibles** (commenter/décommenter dans le fichier `.service`) :

| Mode | `ExecStart` | Usage |
|---|---|---|
| **Binaire** (production) | `/home/user-4itec/4iSafeCross/app.bin` | Déploiement Cython compilé |
| **Python** (développement) | `.../scripts/4isafecross.sh` | Source Python via uv |

**Installation :**

```sh
# 1. Créer et remplir le fichier .env AVANT de démarrer le service
cp .env.example /home/user-4itec/4iSafeCross/.env
nano /home/user-4itec/4iSafeCross/.env
chmod 600 /home/user-4itec/4iSafeCross/.env

# 2. Installer et activer le service
sudo cp scripts/4isafecross.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable 4isafecross.service
sudo systemctl start 4isafecross.service

# 3. Vérifier le statut
sudo systemctl status 4isafecross.service
journalctl -u 4isafecross.service -f
```

---

### `set-poe-gpio.service`

Service oneshot qui exécute [`set_poe_gpio.sh`](../../scripts/set_poe_gpio.sh) au
boot pour activer l'alimentation PoE via GPIO.

Le script positionne le GPIO **`gpiochip2` / ligne `15`** à `1` — nécessaire sur
le reServer Industrial pour que les ports RJ45 PoE (eth1–eth4) fournissent du
courant aux caméras IP.

> ⚠️ Sans ce service, les caméras alimentées par PoE ne reçoivent pas de courant
> après un redémarrage du boîtier.

**Installation :**

```sh
# 1. Copier le script dans le répertoire système
sudo cp scripts/set_poe_gpio.sh /usr/local/bin/set_poe_gpio.sh
sudo chmod +x /usr/local/bin/set_poe_gpio.sh

# 2. Installer et activer le service
sudo cp scripts/set-poe-gpio.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable set-poe-gpio.service
sudo systemctl start set-poe-gpio.service
```

---

### `check-dummy-display.service`

Service qui exécute [`switch-display.sh`](../../scripts/switch-display.sh) au
démarrage pour détecter si un écran HDMI est branché et configurer Xorg en
conséquence.

| Situation | Comportement |
|---|---|
| **HDMI connecté** | `xorg.conf` renommé en `.bak` — l'écran physique prend la main |
| **Aucun HDMI** | `xorg.conf.bak` restauré en `xorg.conf` — driver dummy activé pour VNC |

> ℹ️ Ce service est indispensable pour que la session graphique XFCE reste
> accessible via VNC lorsque le boîtier fonctionne en headless (sans écran).

**Installation :**

```sh
# 1. Copier le script dans le répertoire système
sudo cp scripts/switch-display.sh /usr/local/bin/switch-display.sh
sudo chmod +x /usr/local/bin/switch-display.sh

# 2. Installer et activer le service
sudo cp scripts/check-dummy-display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable check-dummy-display.service
sudo systemctl start check-dummy-display.service
```

---

## Scripts Bash

### `4isafecross.sh`

Script principal de lancement de l'application en mode développement.
Lance l'application avec `uv run waitress-serve`.

```sh
bash scripts/4isafecross.sh
# ou directement depuis la racine du projet :
bash 4isafecross.sh
```

---

### `deploy-jetson.sh`

Déploiement automatisé de l'image Docker depuis le registry GitLab privé
`gitlab.4itec.ddns.net/frank-k/4isafecross`.

**Fonctionnement :**
1. Vérifie la présence de Docker et du runtime NVIDIA.
2. Arrête et supprime l'ancien conteneur `4isafecross` s'il existe.
3. Télécharge la nouvelle image (`docker pull`).
4. Lance le conteneur avec les options de production.

**Options de lancement du conteneur :**

| Option | Valeur |
|---|---|
| Runtime | `--runtime nvidia` |
| Redémarrage | `--restart unless-stopped` |
| Réseau | `--network host` |
| Volume données | `/data/4isafecross:/app/data` |
| Périphériques | `--privileged`, `-v /dev:/dev` |
| Timezone | `-e TZ=Europe/Paris` |
| Port | `5000` |

**Usage :**

```sh
# Déployer le tag latest
bash scripts/deploy-jetson.sh

# Déployer un tag spécifique
bash scripts/deploy-jetson.sh v1.2.0
```

---

### `disable-autosuspend.sh`

Désactive l'autosuspend USB du kernel Linux en ajoutant `usbcore.autosuspend=-1`
aux paramètres de boot dans `/boot/extlinux/extlinux.conf`.

> ⚠️ **À exécuter une seule fois après le flash**, avant tout branchement du
> module Yoctopuce. Sans ce réglage, le kernel suspend le module USB
> Yocto-MaxRelay après quelques minutes d'inactivité, rendant les relais
> inaccessibles sans redémarrage.

```sh
sudo bash scripts/disable-autosuspend.sh
sudo reboot
```

---

### `set_poe_gpio.sh`

Positionne le GPIO `gpiochip2 / ligne 15` à `1` via la commande `gpioset`.
Alimente les ports PoE (eth1–eth4) du reServer Industrial pour les caméras IP.

Géré automatiquement au boot via `set-poe-gpio.service`. Peut aussi être exécuté
manuellement :

```sh
sudo bash scripts/set_poe_gpio.sh
```

---

### `switch-display.sh`

Détecte la présence d'un écran HDMI via le nœud sysfs
`/sys/class/drm/card1-HDMI-A-1/status` et bascule la configuration Xorg :

- HDMI présent → `xorg.conf` → `.bak` (désactivation du dummy)
- HDMI absent → `.bak` → `xorg.conf` (activation du dummy)

Géré automatiquement au boot via `check-dummy-display.service`.

---

### `install_xrdp_jetson.sh`

Installe et configure **TigerVNC + XFCE** sur Jetson Orin NX pour l'accès
graphique distant (VNC sur port `5999`, display `:99`).

**Ce que fait le script :**

- Installe TigerVNC et XFCE4.
- Installe **UFW** et applique les politiques par défaut (`deny incoming`,
  `allow outgoing`).
- Installe et configure **Fail2ban** (jail `tigervnc-auth`, backend systemd,
  action UFW).
- Crée le service systemd `vncserver@99`.
- Configure le clavier AZERTY (`setxkbmap fr`).
- En exécution distante SSH : ajoute une règle anti-lockout pour le port `22`.
- Nettoie les anciennes règles UFW (`3389`, `5999` global) avant d'appliquer les
  nouvelles.

**Options :**

| Option | Description |
|---|---|
| `--subnet <CIDR>` | Sous-réseau autorisé pour VNC (défaut `192.168.3.0/24`) |
| `--tailscale` | Autorise aussi le port VNC via `tailscale0` |

**Usage :**

```sh
# Accès local RJ45 uniquement
sudo bash scripts/install_xrdp_jetson.sh --subnet 192.168.3.0/24

# Recommandé : XFCE + VNC + accès Tailscale distant
sudo bash scripts/install_xrdp_jetson.sh --tailscale
```

**Configuration réseau maintenance recommandée (NetworkManager) :**

- Interface : eth2 / enP1p1s0
- IPv4 : Manuel — `192.168.3.122/24`
- Passerelle : vide
- DNS : vide
- Route par défaut : désactivée (`never-default`)

**Après installation (obligatoire) :**

```sh
# 1. Définir le mot de passe VNC (utilisateur normal)
vncpasswd

# 2. Vérifier UFW et les règles 5999/22
sudo ufw status numbered

# 3. Vérifier Fail2ban
sudo fail2ban-client status tigervnc-auth

# 4. Démarrer le service VNC
sudo systemctl start vncserver@99.service

# 5. Connexion Remmina : VNC | hôte:5999
```

#### Installation rapide de Tailscale (Jetson)

```sh
# 1. Installer Tailscale
sudo curl -fsSL https://tailscale.com/install.sh | sh

# 2. Authentifier le Jetson dans votre tailnet
sudo tailscale up

# 3. Vérifier l'IP Tailscale
tailscale status
tailscale ip -4

# 4. Lancer le script avec l'option Tailscale
sudo bash scripts/install_xrdp_jetson.sh --tailscale

# 5. Définir le mot de passe VNC et démarrer
vncpasswd
sudo systemctl start vncserver@99.service
```

Connexion via Remmina : **VNC** sur `<IP_Tailscale>:5999`.

---

## Logrotate — `4isafecross.logrotate`

Évite la saturation du disque par les logs applicatifs. Conserve 5 archives
compressées de 10 Mo maximum chacune.

```logrotate
/home/user-4itec/4iSafeCross/logs/service_stdout.log
/home/user-4itec/4iSafeCross/logs/service_stderr.log {
    su root root
    size 10M
    rotate 5
    compress
    missingok
    notifempty
    copytruncate
}
```

**Installation :**

```sh
# 1. Copier dans /etc/logrotate.d/
sudo cp scripts/4isafecross.logrotate /etc/logrotate.d/4isafecross

# 2. Tester la rotation manuellement
sudo logrotate -f /etc/logrotate.d/4isafecross
```

---

## Ordre d'installation recommandé sur un Jetson neuf

Après le flash JetPack (voir
[flash-jetson-reserver-j4012-jetpack62.md](flash-jetson-reserver-j4012-jetpack62.md)) :

```
1. disable-autosuspend.sh   → désactiver USB autosuspend + reboot
2. set_poe_gpio.sh          → installer set-poe-gpio.service
3. switch-display.sh        → installer check-dummy-display.service
4. install_xrdp_jetson.sh   → VNC + UFW + Fail2ban
5. .env                     → créer et remplir depuis .env.example
6. 4isafecross.service      → installer et activer
7. 4isafecross.logrotate    → installer dans /etc/logrotate.d/
```
