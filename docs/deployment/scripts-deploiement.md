# Scripts et services de déploiement — 4iSafeCross

Ce document décrit l'ensemble des scripts Bash et fichiers systemd fournis dans le
dossier [`scripts/`](../../scripts/) pour automatiser le déploiement, la
configuration matérielle et la maintenance du boîtier Jetson.

> Ce document fusionne l'ancien `script-deploiement.md` (supprimé). **xrdp/RDP
> est abandonné** ; **RustDesk est conservé comme accès distant provisoire de
> mise au point** (voir la section dédiée). L'affichage headless et GDM3 sont
> repris ci-dessous.

---

## Contexte de déploiement

Le boîtier fonctionne **autonome, sans connexion Internet** en exploitation.

| Élément | En mise au point (sur site) | En exploitation (RUN) |
|---|---|---|
| Connectivité | Clé **4G** provisoire (téléchargement d'image, réglages) — retirée à la livraison | Aucune |
| Accès distant | SSH + VNC local ; **RustDesk** et/ou **Tailscale** provisoires | **VNC local uniquement** (câble RJ45 point-à-point sur `eth2`) |
| Caméras | `eth1`, sous-réseau dédié `192.168.2.x` (PoE) | Idem |

**Accès de maintenance en RUN : TigerVNC chiffré** (port `5999`, `SecurityTypes X509Vnc,RA2ne`).
RDP/xrdp est proscrit (§1.1.4.3 du référentiel Stellantis STLA-CS_STD_004) et
n'est **pas** installé. **Clé 4G, RustDesk, Tailscale et bot Telegram sont des
commodités de mise au point** : connectivité à déclarer au Plant IT Leader, et à
désinstaller/retirer + attester à la recette (voir `CYBER_AUDIT.md`).

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
| [`install_vnc_jetson.sh`](../../scripts/install_vnc_jetson.sh) | Bash | TigerVNC + XFCE + UFW + Fail2ban sur Jetson |
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

**Fichier dummy requis : `/usr/share/X11/xorg.conf.d/xorg.conf.bak`**

`switch-display.sh` bascule ce fichier entre `xorg.conf` (dummy actif, headless)
et `xorg.conf.bak` (HDMI présent). Il **doit exister**. Le recréer si absent
(par ex. après réinstallation du stack graphique) :

```bash
sudo tee /usr/share/X11/xorg.conf.d/xorg.conf.bak << 'EOF'
Section "Device"
    Identifier  "Tegra0"
    Driver      "dummy"
    VideoRam    256000
EndSection

Section "Monitor"
    Identifier  "DummyMonitor"
    HorizSync   28.0-80.0
    VertRefresh 48.0-75.0
    Modeline "1920x1080" 148.50 1920 2008 2052 2200 1080 1084 1089 1125 +hsync +vsync
EndSection

Section "Screen"
    Identifier  "DummyScreen"
    Device      "Tegra0"
    Monitor     "DummyMonitor"
    DefaultDepth 24
    SubSection "Display"
        Depth   24
        Modes   "1920x1080"
    EndSubSection
EndSection
EOF
```

Prérequis paquet : `xserver-xorg-video-dummy`.

---

## Session graphique headless (GDM3)

Pour qu'une session XFCE soit disponible via VNC sur un boîtier sans écran, GDM3
ouvre une session au boot. `/etc/gdm3/custom.conf` :

```ini
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=user-4itec
WaylandEnable=false
```

> **Point de conformité (`CYBER_AUDIT.md`, `CS-113-05`)** : cet autologon n'est
> admis par la norme que sur un **compte Opérateur** sans accès à l'OS depuis le
> runtime. À restreindre (compte dédié sans shell, ou session verrouillée) ou à
> supprimer si l'accès graphique n'est pas indispensable en RUN.

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
`registry.gitlab.4itec.ddns.net/frank-k/4isafecross`.

**Fonctionnement :**
1. Vérifie la présence de Docker et du runtime NVIDIA.
2. Arrête et supprime l'ancien conteneur `4isafecross` s'il existe.
3. Se connecte au registry GitLab (`docker login`).
4. Télécharge la nouvelle image (`docker pull`).
5. Lance le conteneur avec les options de production.

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
bash scripts/deploy-jetson.sh latest

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

### `install_vnc_jetson.sh`

Installe et configure **TigerVNC + XFCE** sur Jetson Orin NX pour l'accès
graphique distant (VNC sur port `5999`, display `:99`).

**Ce que fait le script :**

- Installe TigerVNC et XFCE4.
- Crée le service systemd `vncserver@99` avec **`-SecurityTypes X509Vnc,RA2ne`** :
  la session est **chiffrée** (TLS/X509 — certificat auto-généré dans `~/.vnc/`,
  empreinte à vérifier au 1er accès ; ou RSA-AES). `VncAuth` et `None` (session
  en clair) sont **refusés**.
- Installe **UFW** (`deny incoming` / `allow outgoing`) et n'ouvre `5999/tcp` que
  depuis le sous-réseau de maintenance.
- Installe et configure **Fail2ban** (jail `tigervnc-auth`, backend systemd,
  action UFW).
- Configure le clavier AZERTY (`setxkbmap fr`).
- En exécution distante SSH : ajoute une règle anti-lockout pour le port `22`.
- Nettoie les anciennes règles UFW (`3389`, `5999` global) avant d'appliquer les
  nouvelles.

**Options :**

| Option | Description |
|---|---|
| `--subnet <CIDR>` | Sous-réseau autorisé pour VNC (défaut `192.168.3.0/24`) |
| `--tailscale` | Autorise aussi le port VNC via `tailscale0` — **mise au point uniquement**, à retirer pour l'état RUN (boîtier autonome) |

**Usage — état RUN (recommandé) :**

```sh
sudo bash scripts/install_vnc_jetson.sh --subnet 192.168.3.0/24
```

**Configuration réseau maintenance (NetworkManager, port `eth2`) :**

- Interface : eth2 / enP1p1s0
- IPv4 : Manuel — `192.168.3.122/24`
- Passerelle : vide · DNS : vide · Route par défaut : désactivée (`never-default`)

**Après installation (obligatoire) :**

```sh
# 1. Mot de passe VNC — UNIQUE PAR BOÎTIER, à stocker dans le coffre-fort 4itec
vncpasswd

# 2. Démarrer le service
sudo systemctl start vncserver@99.service

# 3. Contrôle du chiffrement : une connexion NON chiffrée doit être REFUSÉE
vncviewer -SecurityTypes VncAuth 127.0.0.1:5999    # → doit échouer
vncviewer -SecurityTypes X509Vnc,RA2ne 127.0.0.1:5999   # → doit aboutir

# 4. Vérifier UFW et Fail2ban
sudo ufw status numbered
sudo fail2ban-client status tigervnc-auth
```

Côté client (Remmina / TigerVNC viewer) : **activer le chiffrement**
(TLS/X509 ou RSA-AES) ; refuser toute connexion « VNC » non chiffrée.

**Option Tailscale — mise au point uniquement**

```sh
sudo curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo bash scripts/install_vnc_jetson.sh --tailscale
```

À la livraison : `sudo tailscale down && sudo apt purge tailscale`, puis
re-lancer le script sans `--tailscale` pour rétablir le blocage UFW de `tailscale0`.

---

## Accès distant provisoire de mise au point — RustDesk

> **Provisoire, comme la clé 4G et Tailscale.** RustDesk (self-hosted) sert
> uniquement au réglage à distance pendant la mise au point sur site. Il **doit
> être désinstallé et son autostart retiré à la livraison** ; le boîtier en
> exploitation n'a aucun accès distant hors du VNC local sur `eth2`.
> Cette connectivité de mise au point est à déclarer au Plant IT Leader
> (voir `CYBER_AUDIT.md`, §1.2.7 / §1.4.5) et son retrait à attester à la recette.

RustDesk capture le display de la session VNC (`:99`). Deux réglages sont
nécessaires :

**1. Accès au display X pour le service RustDesk** (tourne en root) —
`/etc/systemd/system/rustdesk.service.d/override.conf` :

```ini
[Service]
Environment=DISPLAY=:99
Environment=XAUTHORITY=/home/user-4itec/.Xauthority
```

**2. Autorisation `xhost` renouvelée à chaque session** (le cookie
MIT-MAGIC-COOKIE-1 change) — [`autostart/rustdesk-xhost.desktop`](../../autostart/rustdesk-xhost.desktop),
à copier dans `~/.config/autostart/` :

```ini
[Desktop Entry]
Type=Application
Name=RustDesk xhost fix
Exec=bash -c "DISPLAY=:99 xhost +local:root"
X-GNOME-Autostart-enabled=true
```

> `xhost +local:root` abaisse le contrôle d'accès du serveur X pour root local
> — acceptable le temps de la mise au point, à retirer avec RustDesk.

**Retrait à la livraison :**

```sh
sudo systemctl disable --now rustdesk
sudo apt purge rustdesk
rm -f ~/.config/autostart/rustdesk-xhost.desktop
sudo rm -f /etc/systemd/system/rustdesk.service.d/override.conf
```

**Diagnostic (pendant la mise au point) :**

```sh
sudo journalctl -u rustdesk -n 50 --no-pager | grep -iE "display|xauth|error|refused"
DISPLAY=:99 XAUTHORITY=/home/user-4itec/.Xauthority xdpyinfo | grep "name of display"
```

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
4. install_vnc_jetson.sh   → VNC + UFW + Fail2ban
5. .env                     → créer et remplir depuis .env.example
6. 4isafecross.service      → installer et activer
7. 4isafecross.logrotate    → installer dans /etc/logrotate.d/
```
