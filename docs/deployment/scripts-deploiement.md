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
| Accès distant | SSH + VNC local ; **RustDesk** et/ou **Tailscale** provisoires | **VNC local uniquement** (câble RJ45 point-à-point sur le port maintenance) |
| IHM de supervision | HTTPS via Caddy sur le port maintenance (`https://192.168.3.122`) ; ou tunnel SSH sur la 4G | HTTPS via Caddy sur le port maintenance uniquement |
| Caméras | sous-réseau partagé `192.168.0.0/24` sur `eth2`/`eth3`/`eth4` (bridge `br0` ou switch PoE) | Idem |

> **Plan d'adressage (nouvelles installations)** : maintenance sur **`eth1`**
> (`192.168.3.122/24`), caméras sur **`eth2`/`eth3`/`eth4`** (sous-réseau partagé
> `192.168.0.0/24`, Jetson en `192.168.0.100`). Le **site HAM** est **en service à
> ce jour sur le plan précédent** (caméras `eth1` / `192.168.2.x`, maintenance
> `eth2`) et **sera migré ultérieurement** — détail dans le `README.md`. Voir aussi
> `docs/compliance/cartographie-flux-stellantis.md`.

**IHM en HTTPS** : `waitress` sert l'IHM Flask **en clair sur `127.0.0.1:5050` uniquement**
(`run.py`) ; le reverse-proxy **Caddy** (`config/Caddyfile`, `scripts/caddy-4isafecross.service`)
termine le TLS et l'expose sur le port maintenance. Le port `5050` n'est jamais ouvert sur le réseau.
Voir la section **« IHM en HTTPS (Caddy) »** ci-dessous. Conformité : `CYBER_AUDIT.md`
(`CS-1143-01`, `CS-143-02`).

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
| [`4isafecross.sh`](../../scripts/4isafecross.sh) | Bash | Lance l'app manuellement (`uv run python run.py`) |
| [`caddy-4isafecross.service`](../../scripts/caddy-4isafecross.service) | systemd | Reverse-proxy TLS de l'IHM (Caddy, sur l'hôte) |
| [`../../config/Caddyfile`](../../config/Caddyfile) | config | Vhosts + `tls internal` + en-têtes de sécurité de l'IHM |
| [`deploy-jetson.sh`](../../scripts/deploy-jetson.sh) | Bash | Déploie l'image Docker depuis le registry GitLab |
| [`disable-autosuspend.sh`](../../scripts/disable-autosuspend.sh) | Bash | Désactive l'USB autosuspend (Yoctopuce) |
| [`set_poe_gpio.sh`](../../scripts/set_poe_gpio.sh) | Bash | Positionne le GPIO PoE (utilisé par le service) |
| [`switch-display.sh`](../../scripts/switch-display.sh) | Bash | Logique de détection HDMI / activation dummy Xorg |
| [`install_vnc_jetson.sh`](../../scripts/install_vnc_jetson.sh) | Bash | TigerVNC + XFCE + UFW (VNC 5999 + IHM 443) + Fail2ban |
| [`setup-camera-net.sh`](../../scripts/setup-camera-net.sh) | Bash | Sous-réseau caméras **dédié et isolé** (`nmcli` : IP statique, sans passerelle/DNS/route par défaut) — mesure compensatoire `CS-1143-01` |
| [`harden-run.sh`](../../scripts/harden-run.sh) | Bash | **Passage en état RUN** : retire RustDesk / Tailscale / bot Telegram / clé 4G, contrôle l'isolation du segment caméras, vérifie UFW — attestation à la recette (`CS-127-01/02`, `CS-1143-04/05`, `CS-1143-01`) |
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

Service **persistant** qui maintient à `1` le GPIO **`gpiochip2` / ligne `15`**
(`PSE_PWR_EN`) — nécessaire sur le reServer Industrial pour que les quatre ports
RJ45 PoE fournissent du courant aux caméras IP. Le cinquième port (`LAN0`) n'est
pas PoE.

> ⚠️ **`--mode=signal` rend l'état déterministe.** Sans lui, `gpioset` positionne la
> valeur puis rend la main et le kernel relâche la ligne — état que libgpiod qualifie
> de **non défini** (`gpioset --help` : « the state of a GPIO line reverts to default
> when the last process referencing the file descriptor exits »). En pratique, le
> pilote `pca953x` laisse la sortie haute après libération, et c'est ainsi que
> l'ancien service `oneshot` (`gpioset gpiochip2 15=1` sans mode) fonctionne encore
> sur les boîtiers en JetPack 6.2. Mais rien ne garantit cet effet de bord d'un kernel
> à l'autre : le process reste donc vivant et tient la ligne, d'où l'absence de
> `Type=oneshot` et la présence de `Restart=always`. Ce n'est pas un correctif de
> panne — un boîtier qui n'alimente pas avec la ligne tenue a un autre problème
> (voir le diagnostic ci-dessous).

**Installation :**

```sh
sudo cp scripts/set-poe-gpio.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now set-poe-gpio.service
```

**Vérification** (les trois doivent concorder) :

```sh
systemctl status set-poe-gpio.service          # active (running), PID gpioset vivant
gpioinfo gpiochip2 | grep PSE_PWR_EN           # "gpioset" comme consumer, [used]
sudo grep -i PSE_PWR_EN /sys/kernel/debug/gpio # out hi
```

Si `gpioinfo` affiche `unused`, la ligne n'est tenue par personne : son niveau
dépend alors d'un effet de bord du pilote, pas d'une commande — vérifier
`/sys/kernel/debug/gpio` ou `i2cget -y -f 1 0x21 0x03` (bit 7).

**Diagnostic** (constats relevés sur JetPack 7.2, `4isafecross-2`) :

| Point | Commande | Attendu |
|---|---|---|
| Version des outils | `gpioset --version` | libgpiod **1.6.3** sous JP 7.2 (Ubuntu 24.04) — la syntaxe positionnelle reste valide, contrairement à libgpiod 2.x |
| Ligne PoE | `gpiofind PSE_PWR_EN` | `gpiochip2 15` |
| Contrôleur PSE | `gpioget gpiochip2 0` (`PSE_PG`) | `1` — lecture non intrusive, c'est une entrée |
| Registres de l'expander | `sudo i2cget -y -f 1 0x21 0x03` (PCA9535 à `0x21` sur `i2c-1`) | bit 7 = 1 (sortie haute) |
| Ports PoE | — | les quatre `lan743x` (`enP7p3s0`, `enP7p4s0`, `enP7p5s0`, `enP1p1s0`) ; `ethtool -p` n'est pas supporté par ce pilote, mapper les connecteurs via `journalctl -k -f \| grep -i link` |

Les erreurs `pcieport … AER: Uncorrectable (Non-Fatal)` visibles au branchement
d'un câble sont un bruit de fond de plateforme sans incidence sur le PoE.

**Test de la chaîne d'alimentation** : `PSE_PG` (ligne 0) doit suivre l'enable —
`0` quand `PSE_PWR_EN` est tenu bas, `1` quand il est haut :

```sh
sudo systemctl stop set-poe-gpio.service
sudo gpioset --mode=time --sec=8 gpiochip2 15=0 & sleep 4; gpioget gpiochip2 0; wait   # → 0
sudo systemctl start set-poe-gpio.service; sleep 4; gpioget gpiochip2 0                  # → 1
```

Le contrôleur des ports PoE **n'est pas sur I²C** (aucune adresse au-delà de
l'expander `0x21` et de l'INA3221 `0x40` sur `i2c-1`) : il fonctionne en mode
autonome, sans pilote, sous JetPack 6.2 comme 7.2. Si tous les points ci-dessus sont
conformes et qu'aucun PD ne s'allume (caméra validée sur injecteur), **le défaut est
matériel**, en aval du convertisseur 48 V — cas rencontré sur `4isafecross-2` en
septembre 2026, avec un état logiciel strictement identique à un boîtier JP 6.2
fonctionnel. Preuve définitive : échanger les modules Orin NX entre deux boîtiers, le
défaut suit la carte porteuse. Contournement : injecteurs ou switch PoE externe.

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

TigerVNC (`vncserver@99`) démarre sa **propre** session XFCE indépendamment de
GDM3 (`install_vnc_jetson.sh`). **L'autologon GDM3 n'est donc pas nécessaire** au
fonctionnement du VNC de maintenance.

### Pourquoi une session VNC dédiée, et pas la recopie de l'écran `:0` ?

Question récurrente à chaque nouveau boîtier : « GDM3 est déjà installé, pourquoi
ajouter XFCE ? »

`tigervnc-standalone-server` lance un **second serveur X complet** (`Xvnc`, display
`:99`), sans aucun rapport avec l'affichage physique `:0` que gère GDM3. Ce display
démarre **vide** : son contenu est uniquement ce que lance `~/.vnc/xstartup`. GDM3 est un
*display manager* — il ouvre une session sur `:0`, il ne fournit rien à `:99`. Il faut
donc un environnement de bureau ou un gestionnaire de fenêtres **dans la session VNC**,
et XFCE n'est qu'un choix parmi d'autres :

| Option | Ce que ça donne | Verdict |
|---|---|---|
| **XFCE resserré** (retenu) | Bureau complet dans `:99`, rendu logiciel, aucun besoin de GPU | ✅ |
| **GNOME** (`exec gnome-session` dans `xstartup`) | Rien à installer en plus, GNOME étant déjà là avec GDM3 | ⚠️ GNOME Shell sous `Xvnc` = rendu logiciel `llvmpipe` sans accélération, lourd sur Orin et session Wayland-first sur 24.04 → fragile |
| **WM minimal** (`openbox`, `fluxbox`) + terminal | Le strict nécessaire pour la maintenance | ✅ encore plus léger si la session n'a besoin ni de navigateur ni de bureau |
| **Recopie de `:0`** (`x0vncserver`, `x11vnc`) | Aucun bureau supplémentaire : on voit la vraie session GNOME | ❌ voir ci-dessous |

La recopie de `:0` est la seule option qui réutiliserait réellement GDM3. Elle est
**incompatible avec l'interdiction d'autologon** (`CS-113-05`, ci-dessous) : sans
autologon, après un redémarrage il n'existe aucune session utilisateur sur `:0` — il n'y a
que le greeter GDM. Un `x0vncserver` lancé sous l'utilisateur d'exploitation n'a alors rien
à recopier, et **l'accès de maintenance à distance est perdu après chaque reboot**. Le mode
standalone démarre au contraire avec `multi-user.target`, indépendamment de toute session
ouverte.

**Paquets installés** — `install_vnc_jetson.sh` installe les composants nécessaires à
`startxfce4` et rien de plus (`xfce4-session`, `xfwm4`, `xfce4-panel`, `xfdesktop4`,
`xfce4-settings`, `xfce4-terminal`, plus `xterm` comme terminal de secours). Les
métapaquets `xfce4` et `xfce4-goodies` sont **volontairement écartés** : ils tirent des
dizaines d'applications annexes inutiles à une session de maintenance, donc à suivre et à
corriger pour rien (`CS-123-03`).

Contrôle après installation — certains métapaquets de bureau tirent leur propre display
manager et peuvent supplanter GDM3 :

```sh
cat /etc/X11/default-display-manager      # doit rester /usr/sbin/gdm3
systemctl is-enabled gdm3 lightdm 2>/dev/null
```

**Par défaut : ne pas activer l'autologon** (`CS-113-05`, `CS-113-01`).
`/etc/gdm3/custom.conf` :

```ini
[daemon]
WaylandEnable=false
# AutomaticLoginEnable / AutomaticLogin : NON activés.
```

Vérifier après flash :

```sh
grep -E 'AutomaticLogin' /etc/gdm3/custom.conf || echo "OK : pas d'autologon"
```

> **Si** un autologon est indispensable sur un site donné, le référentiel
> Stellantis (`CS-113-05`) ne l'admet qu'aux **trois** conditions cumulatives,
> à documenter dans le dossier de recette du boîtier :
> 1. compte **dédié** à la seule session graphique, **sans shell** (`usermod -s /usr/sbin/nologin`) et sans `sudo` ;
> 2. session **verrouillée** au démarrage (écran de verrouillage XFCE), déverrouillée seulement par l'intervenant de maintenance ;
> 3. aucun accès à l'OS ni aux fichiers applicatifs depuis cette session (pas de terminal, gestionnaire de fichiers restreint).
>
> À défaut de pouvoir garantir les trois, **supprimer l'autologon**.

---

## Scripts Bash

### `4isafecross.sh`

Lancement manuel de l'application en développement. Exécute `uv run python run.py`
(même point d'entrée que le conteneur Docker et le service systemd) : la séquence
de boot — licence, relais fail-safe, caméras, threads — est obligatoire et n'est
pas reproductible par `waitress-serve --call`.

`run.py` lie `waitress` à **`127.0.0.1:5050` uniquement**. Pour l'accès depuis un
navigateur distant, passer par Caddy (`https://…`, voir ci-dessous) ou par un
tunnel SSH.

```sh
bash scripts/4isafecross.sh
# ou directement depuis la racine du projet :
bash 4isafecross.sh
```

---

### `caddy-4isafecross.service` + `config/Caddyfile` — IHM en HTTPS (Caddy)

`waitress` sert l'IHM Flask **en clair sur `127.0.0.1:5050`**. Le reverse-proxy
**Caddy** termine le TLS et expose l'IHM en `https://192.168.3.122` sur le port
de maintenance (`eth1` sur les nouvelles installations, `eth2` sur HAM). Il tourne **sur l'hôte** (le conteneur applicatif est en
`network_mode: host`, Caddy joint donc `127.0.0.1:5050` directement).

- Certificat : **CA interne Caddy** (`tls internal`) — boîtier hors ligne, aucune
  émission ACME. Empreinte à vérifier au 1er accès, comme le certificat TigerVNC.
  Pour retirer l'avertissement navigateur sur le PC de maintenance, importer la
  racine interne (voir « Certificat interne » plus bas).
- Pare-feu : `install_vnc_jetson.sh` ouvre `443/tcp` au seul sous-réseau
  `192.168.3.0/24` et referme `5050/tcp`.

Deux méthodes d'installation, au choix. **En ligne (apt)** pendant la fenêtre de
mise au point (clé 4G branchée) : plus simple, mises à jour de sécurité par apt.
**Hors ligne (binaire statique)** : aucune dépendance réseau, à privilégier pour
l'image RUN. Les deux aboutissent au même résultat : un service `caddy` qui sert
`/etc/caddy/Caddyfile`.

#### Méthode A — en ligne (dépôt apt officiel)

À exécuter avec la clé 4G branchée. Cette connectivité est à déclarer au Plant IT
Leader au même titre que les autres flux de mise au point.

```sh
# 1. Ajouter le dépôt Caddy (Cloudsmith) et installer
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy

# 2. Le paquet fournit DÉJÀ : le binaire /usr/bin/caddy, l'utilisateur `caddy`,
#    et une unité /lib/systemd/system/caddy.service fonctionnelle.
#    -> NE PAS copier scripts/caddy-4isafecross.service : on garde l'unité du paquet
#       (mises à jour apt) et on ne remplace QUE le Caddyfile.
sudo install -d -o caddy -g caddy /var/log/caddy
sudo cp config/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy && sudo systemctl enable caddy
```

> Pour figer la version (recette) : `sudo apt-mark hold caddy`.
> Bascule ultérieure vers l'état RUN hors ligne : `sudo apt-mark unhold caddy`,
> `sudo apt purge caddy`, puis méthode B.

#### Méthode B — hors ligne (binaire statique)

Binaire transféré par support local (aucun module supplémentaire requis) :

```sh
# 1. Binaire « linux / arm64 » depuis https://caddyserver.com/download
sudo install -m 0755 caddy /usr/local/bin/caddy
sudo useradd --system --home /var/lib/caddy --create-home --shell /usr/sbin/nologin caddy
sudo mkdir -p /etc/caddy /var/log/caddy && sudo chown caddy:caddy /var/log/caddy

# 2. Configuration + service (notre unité pointe sur /usr/local/bin/caddy)
sudo cp config/Caddyfile /etc/caddy/Caddyfile
/usr/local/bin/caddy validate --config /etc/caddy/Caddyfile
sudo cp scripts/caddy-4isafecross.service /etc/systemd/system/caddy.service
sudo systemctl daemon-reload && sudo systemctl enable --now caddy
```

> Si la méthode A a déjà été utilisée : d'abord `sudo apt purge caddy` (sinon
> deux unités `caddy.service` entrent en conflit).

#### Contrôles (communs aux deux méthodes)

```sh
curl -k https://127.0.0.1/health                        # -> 200 (Caddy -> waitress)
curl    http://127.0.0.1:5050/health                    # -> 200 en local uniquement
curl -k https://192.168.3.122/health                    # -> 200 depuis le PC maintenance
curl    http://192.168.3.122:5050/health                # -> doit ÉCHOUER (refusé)
systemctl status caddy --no-pager
```

#### Certificat interne (retirer l'avertissement navigateur)

```sh
# Sur le Jetson : installer la racine interne dans le magasin système local
sudo caddy trust                     # -> curl https://... sans -k fonctionne en local

# Racine à exporter vers le PC de maintenance (chemin selon la méthode) :
#   Méthode A (apt)      : /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
#   Méthode B (statique) : idem, $HOME de l'utilisateur `caddy` = /var/lib/caddy
sudo cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
# -> importer ce fichier dans les « Autorités de certification racines de confiance »
#    du PC de maintenance.
```

**Accès pendant la mise au point (clé 4G)** : Caddy sur `eth2` n'est pas joignable
par la 4G. Utiliser soit le bureau distant **RustDesk** (puis `https://localhost`
en local sur le boîtier), soit un **tunnel SSH** :
`ssh -L 8443:127.0.0.1:5050 user-4itec@<jetson>` → `https://localhost:8443`.

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
| Volumes état | `/data/4isafecross/{config,db,detections,dataset,logs}` → `/app/…` |
| Volumes licence | `./licenses:/app/licenses`, `/etc/machine-id:/etc/machine-id:ro` |
| Périphériques | `--privileged`, `-v /dev:/dev` |
| Timezone | `-e TZ=Europe/Paris` |
| Port IHM | `5050` en clair sur `127.0.0.1` (exposé en HTTPS par Caddy) — non publié, réseau `host` |

**Usage :**

```sh
# Déployer le tag latest
bash scripts/deploy-jetson.sh latest-arm64

# Déployer un tag spécifique
bash scripts/deploy-jetson.sh v3.0.0-arm64
```

> ⚠️ **La référence de production est `docker-compose-arm64.yml`**, pas ce script : son
> `docker run` diverge du fichier compose (montage de `/dev` en entier, pas de `ipc: host`
> ni de montages `enctune`/`argus_socket`). `deploy-jetson.sh` sert au déploiement rapide
> en mise au point. Ne pas mélanger les deux méthodes sur un même boîtier — un conteneur
> créé par `docker run` n'est pas géré par `docker compose`.
> Voir [install-prod-jetson-docker.md](install-prod-jetson-docker.md).

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

Maintient à `1` le GPIO `gpiochip2 / ligne 15` (`PSE_PWR_EN`) et alimente les
quatre ports PoE du reServer Industrial pour les caméras IP.

En exploitation, cette fonction est assurée par `set-poe-gpio.service`, qui
appelle `gpioset` directement. Ce script sert au **test manuel** :

```sh
sudo bash scripts/set_poe_gpio.sh    # ne rend pas la main
```

> ⚠️ Il reste au premier plan tant que le PoE doit être alimenté, et **`Ctrl+C`
> coupe l'alimentation des caméras**. Arrêter d'abord `set-poe-gpio.service`
> avant de l'utiliser : deux processus ne peuvent pas détenir la même ligne, le
> second échouerait avec « Device or resource busy ».

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
  action UFW), avec `python3-systemd` — requis par le backend `systemd`, sans lui la
  jail ne démarre pas. Le script **vérifie que la jail est réellement active** après
  démarrage et prévient sinon ; un échec de Fail2ban n'interrompt pas l'installation,
  UFW restant la protection prioritaire.
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

**Configuration réseau maintenance (NetworkManager) :**

- Port : **`eth1`** sur les nouvelles installations (**`eth2`** sur le site HAM).
  Nom d'interface Jetson (`enPxpxsx`) : `ip -br link`.
- IPv4 : Manuel — `192.168.3.122/24`
- Passerelle : vide · DNS : vide · Route par défaut : désactivée (`never-default`)

**Configuration réseau caméras (nouvelles installations) :**

- `eth2` + `eth3` + `eth4` réunis en un pont `br0` (ou via un switch PoE externe).
- IPv4 de `br0` (ou de l'interface caméra) : Manuel — `192.168.0.100/24`, sans passerelle ni route par défaut.
- Caméras (1 à 3) : `192.168.0.60` (obligatoire), `192.168.0.61`, `192.168.0.62` (optionnelles) — cf. `config/config.ini` `[RTSP] HOST`.

**Transport des flux caméras (`CS-1143-01`) — testé sur cible :**

Caméras **TP-Link VIGI S485 / S455**. Constats vérifiés sur `192.168.0.62` :

| Test | Résultat |
|---|---|
| **554** | RTSP standard. `SRTP=Off` : SDP `m=video 0 **RTP/AVP** 96` (H.264 High 1080p), `SETUP` → `200 OK`, GStreamer/ffmpeg lisent en TCP **et** UDP. **Transport RTP en clair.** |
| **322 / 8554** | Fermés — aucun port RTSPS. |
| **8443** (*HTTP(S) → Local Stream Port*) | TLS 1.2 mais service **propriétaire `Server: Streamd`** : une requête RTSP → `HTTP/1.0 400` ; un tunnel RTSP-over-HTTP → `302` vers l'IHM web `443`. **Inexploitable** par GStreamer/ffmpeg (« Parse error »). |
| **8800** (*Video Service Port*) | Binaire propriétaire, pas même du TLS. |
| **`SRTP = On`** (*Advance Settings → SRTP Settings*) | La caméra **rejette tout `SETUP` non-SRTP** → `400`. Aucun client tiers ne lit le flux. Le SRTP TP-Link est réservé aux **NVR VIGI**. **→ SRTP doit rester `Off`.** |
| **Authentification** | Réglée sur **`Digest MD5/SHA-256`** (onglet *RTSP → Digest Authentication Algorithm*). Le `401` propose les deux Digest **+ `Basic`**. **`rtspsrc` (= 4iSafeCross) s'authentifie en Digest — vérifié.** ⚠️ ffmpeg/`ffplay`/VLC **échouent** (bug de gestion des défis Digest multi-algorithmes) — sans impact sur l'app ; pour un test manuel, utiliser `gst-launch-1.0` / `gst-play-1.0` ou l'app VIGI. ⚠️ `Basic` reste accepté par la caméra, sans option pour le désactiver. |

```ini
[RTSP]
SCHEME = rtsp          ; aucun mode RTSP chiffré exploitable sur les VIGI S485/S455
PORT   = 554
```

**Mesures compensatoires (dérogation `CS-1143-01` — impossibilité matérielle) :**

| Mesure | État |
|---|---|
| **Digest MD5/SHA-256** | `rtspsrc` négocie et utilise le Digest (vérifié). ⚠️ Basic reste accepté par la caméra. |
| **Segment caméras dédié et isolé** | Appliqué par **`scripts/setup-camera-net.sh`** : `192.168.0.0/24` sur bridge `br-cameras` (ou une interface unique vers un switch PoE), **IP statique, sans passerelle, sans DNS, `never-default`, IPv6 off**. Contrôlé par `harden-run.sh` (étape « Segment caméras »). |
| **Durcissement caméra** | **SNMP** (SNMPv1/2 = protocole interdit §1.1.4.3), **RTMP**, **DDNS**, **ONVIF** (+ WS-Discovery) → **désactivés**. Mot de passe **unique par caméra** (coffre 4itec). **802.1x** (EAP-TLS) si le switch PoE est managé + RADIUS, sinon non applicable (compensé par l'isolation physique). |
| **Équipements dédiés** | Caméras = appliances à fonction unique. `harden-run.sh` liste les hôtes du `/24` et signale tout OUI non-TP-Link. **À attester à la recette** : une caméra ne joint aucune IP publique. |
| **Bascule prête** | Le code gère `SCHEME = rtsps` (+ `TLS_CA`) si des caméras à RTSP/TLS sont installées un jour (Axis, Bosch, Hanwha, Mobotix…) — seul `config.ini` change. |

**Checklist de durcissement caméra (à cocher par unité, à joindre à la recette) :**

- [ ] `SRTP = Off` (*Advance Settings*)
- [ ] *Digest Authentication Algorithm* = `MD5/SHA256` — onglet **RTSP** *et* onglet **HTTP(S)**
- [ ] **SNMP désactivé** (ou SNMPv3 uniquement)
- [ ] **RTMP désactivé**
- [ ] **DDNS désactivé**
- [ ] **ONVIF désactivé** (« Open Network Video Interface » = Off)
- [ ] `802.1x` (`Automatically switch to static IP` = On) — configuré si switch managé
- [ ] IP **statique**, **sans passerelle**, sans DNS (segment isolé)
- [ ] Mot de passe **unique**, compte admin renommé si le firmware le permet
- [ ] Firmware caméra à jour ; heure synchronisée (traçabilité RGPD des captures)

Étapes de déploiement :

1. Appliquer la checklist ci-dessus sur **chaque caméra**.
2. `scripts/setup-camera-net.sh` sur le Jetson (voir en-tête du script pour la topologie).
3. Renseigner `RTSP_LOGIN` / `RTSP_PASSWORD` dans `.env`.
4. **Formaliser la dérogation `CS-1143-01`** (flux caméras) avec le référent : impossibilité matérielle + tableau + checklist ci-dessus.

> Contrôle à la recette : `tcpdump -i <if-cam> -A port 554` — l'URL/SDP en clair,
> **pas** d'identifiants (Digest actif), et aucun autre hôte que les caméras sur le `/24`.

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
sudo fail2ban-client status tigervnc-auth      # doit lister la jail, pas « Sorry but... »

# 5. Contrôler que le filtre reconnaît bien les échecs d'authentification réels
#    (après quelques tentatives ratées volontaires)
sudo fail2ban-regex "systemd-journal[_SYSTEMD_UNIT=vncserver@99.service]" \
     /etc/fail2ban/filter.d/tigervnc-auth.conf
```

> Le `failregex` du filtre **doit contenir le tag `<HOST>`** : c'est lui qui désigne
> l'adresse à bannir. Sans ce tag, Fail2ban rejette le filtre (« No 'host' group ») et la
> jail ne démarre pas — le service tourne, mais **aucune tentative n'est bloquée**. D'où
> le contrôle n° 4 : ne jamais supposer la protection active sans l'avoir vérifiée.

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
> exploitation n'a aucun accès distant hors du VNC local sur le port de maintenance.
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

> `logs/audit.log` (journal d'audit, ci-dessous) **n'est pas** géré par logrotate :
> il a sa propre rotation applicative (`RotatingFileHandler`, 5 Mo × 10). Ne pas
> l'ajouter ici (double rotation).

---

## Journal d'audit — `logs/audit.log` (`CS-144-01` / `CS-R2-03`)

L'IHM écrit une **ligne JSON par événement** dans `logs/audit.log` :

- toute **écriture** (`POST` / `PUT` / `PATCH` / `DELETE` — zones, masques, seuils, toggle détection, relais) ;
- tout **rejet** : `401` (non authentifié) et `403` (contrôle anti-CSRF d'`Origin`).

Champs : `ts` (ISO 8601 avec fuseau), `ip` (source réelle via `X-Forwarded-For` posé par Caddy), `user` (identité présentée), `method`, `path`, `status`, `event` (`write` / `auth_reject` / `forbidden`), `origin` si présent.

```json
{"ts":"2026-09-01T14:32:07.412+02:00","ip":"192.168.3.50","user":"maintenance","method":"POST","path":"/api/zones/0","status":200,"event":"write"}
{"ts":"2026-09-01T14:33:11.088+02:00","ip":"192.168.3.50","user":"-","method":"POST","path":"/toggle_detection/0","status":401,"event":"auth_reject"}
```

- **Rotation** : applicative, 5 Mo × 10 fichiers (`audit.log`, `audit.log.1`, …).
- **Persistance** : `logs/` est monté en volume (`/data/4isafecross/logs`, `docker-compose-*.yml` et `scripts/deploy-jetson.sh`) — le journal survit aux mises à jour d'image.
- **Revue / export** (`CS-R2-04`) : consulter avec `tail -f logs/audit.log | jq .` ; exporter sur support amovible lors des interventions, ou rediriger vers syslog si un collecteur est disponible.
- **Recette FOR_509** : vérifier qu'un `curl` sans identifiants (`→ 401`) **et** une écriture authentifiée produisent chacun une ligne.

---

## Ordre d'installation recommandé sur un Jetson neuf

Après le flash **JetPack 7.2** (voir
[flash-jetson-reserver-j4012-jetpack72.md](flash-jetson-reserver-j4012-jetpack72.md)) :

```
--- sur site, écran HDMI + clavier branchés -------------------------------------
1. Gel des paquets firmware → apt-mark hold + pin (carte Seeed) — AVANT tout apt
2. install_vnc_jetson.sh    → VNC chiffré 5999 + UFW (5999 + 443) + Fail2ban

--- à partir d'ici, tout se pilote depuis le PC de maintenance -------------------
3. disable-autosuspend.sh   → désactiver USB autosuspend + reboot
4. set_poe_gpio.sh          → installer set-poe-gpio.service (alimentation des caméras)
5. switch-display.sh        → installer check-dummy-display.service (headless)
6. setup-camera-net.sh      → sous-réseau caméras dédié isolé (192.168.0.0/24)
7. Docker + runtime NVIDIA  → plugin Compose v2, contrôle `docker info | grep -i runtimes`
8. .env                     → créer et remplir depuis .env.example (dont RTSP_LOGIN/PASSWORD)
9. Image applicative        → pull (registry GitLab) ou docker load, amorçage de
                              /data/4isafecross, licence, `docker compose up -d`
   (alternative « sources / binaire » : 4isafecross.service — EXCLUSIF du conteneur,
    les deux servent l'IHM sur 127.0.0.1:5050)
10. caddy-4isafecross.service + config/Caddyfile → reverse-proxy TLS de l'IHM
11. 4isafecross.logrotate   → installer dans /etc/logrotate.d/
12. harden-run.sh           → à la LIVRAISON : retrait des outils de mise au point
                              + contrôle isolation caméras ; sortie au dossier de recette
```

**Pourquoi l'accès distant en n° 2** : seules les deux premières étapes exigent d'être
physiquement devant le boîtier. Une fois TigerVNC en place, le reste du déploiement
(scripts matériels, Docker, image applicative, Caddy) se fait depuis le PC de maintenance,
écran et clavier débranchés — y compris les redémarrages, `vncserver@99` étant lancé par
`multi-user.target` sans session ouverte.

Prérequis pour que le n° 2 suffise :

- **IP de maintenance posée** sur `eth1` (`192.168.3.122/24`) — à faire dans l'assistant
  Ubuntu juste après le flash, ou en `nmcli` avant de lancer le script ;
- **source de paquets accessible** (clé 4G de mise au point ou dépôt local) : le script
  fait `apt update && apt install`.

> ⚠️ **Le gel firmware (n° 1) doit précéder le n° 2.** `install_vnc_jetson.sh` déclenche un
> `apt update && apt install` qui reconfigurerait `nvidia-l4t-bootloader` sur la carte
> Seeed et casserait l'état dpkg dès la première commande apt du boîtier — voir
> [install-system-deps.md](install-system-deps.md) § « Carte porteuse Seeed ».

> ⚠️ **Anti-lockout SSH.** Le script applique `ufw default deny incoming` et n'ouvre le
> port 22 que depuis l'IP du client **s'il est lancé par SSH** (variable `SSH_CLIENT`).
> Lancé depuis la console locale (clavier + HDMI), SSH sera **bloqué** après l'activation
> d'UFW : n'ouvrir alors que le VNC, ou ajouter la règle avant de débrancher l'écran :
> ```sh
> sudo ufw allow from 192.168.3.0/24 to any port 22 proto tcp
> ```

> Étapes 7 à 9 en détail (dépendances, registry GitLab, docker-compose, licence,
> checklist de recette) : [install-prod-jetson-docker.md](install-prod-jetson-docker.md).

> Mises à jour de sécurité L4T/OS en exploitation (hors ligne) + rollback :
> [maj-l4t-hors-ligne.md](maj-l4t-hors-ligne.md).

---

## Matrice de compatibilité OS / runtime (`CS-R7-01`)

| Composant | Version cible | Plancher de version dans le code | Plan de montée |
|---|---|---|---|
| JetPack / L4T | **7.2 / r39.2** (homologuée) | Base image `nvcr.io/nvidia/cuda:13.2.1-runtime-ubuntu24.04` ; dépôts apt `jetson … r39.2` | Toute montée réhomologuée par le référent + appliquée à tout le parc (`CS-1141-01`) |
| Rootfs | Ubuntu 24.04 LTS | `python3.12` (Dockerfile) | 26.04 LTS : à évaluer avec JetPack ultérieur |
| Python | 3.12 | `requires-python = ">=3.10,<3.13"` (`pyproject.toml`) | Lever le plafond `<3.13` dès que `pygobject` / `opencv-python` publient des roues 3.13 stables |
| PyGObject | < 3.51.0 | `pygobject<3.51.0` (`pyproject.toml`) | Plafond posé pour compat GLib de L4T r39.2 ; réévaluer à chaque montée L4T |
| GStreamer | 1.24 (Ubuntu 24.04) | Backend `jetson` (`nvv4l2decoder` + `nvvidconv`, dépôt L4T) | Suivre la version fournie par le BSP ; le backend `software` reste le repli universel |
| CUDA / TensorRT | 13.2 / BSP r39.2 | image runtime + `nvidia-l4t-*` | Fournis par le BSP — pas de montée indépendante |

Les plafonds (`<3.13`, `pygobject<3.51.0`) sont **volontaires** : ils garantissent
la compatibilité avec les bibliothèques système de JetPack 7.2. Ils sont à revoir
à chaque réhomologation de version de firmware.

---

## Effacement sécurisé des supports (fin de vie / retour SAV) (`CS-R1-03`)

Le boîtier stocke des **images de personnes** (captures d'alerte, dataset) et des
identifiants (`.env`, mots de passe VNC). Avant retour SAV, revente ou mise au
rebut :

1. **Arrêter** l'application et Docker : `sudo systemctl stop 4isafecross docker`.
2. **Effacer les données applicatives** (`/data/4isafecross` = bind-mounts
   `config`, `db`, `detections`, `dataset`, `logs`) :
   ```sh
   sudo find /data/4isafecross -type f -exec shred -u -n 3 {} +
   sudo rm -rf /data/4isafecross
   ```
3. **Effacer les secrets hôte** : `.env`, `~/.vnc/passwd`, historique shell,
   `journalctl --rotate && journalctl --vacuum-time=1s`.
4. **Support de stockage** :
   - NVMe : `sudo nvme format /dev/nvme0n1 --ses=1` (secure erase) si supporté,
     sinon `blkdiscard` puis `shred` de la partition.
   - eMMC (module Orin) : reflasher une image **vierge** (sans config ni licence)
     via `l4t_initrd_flash.sh` — c'est la garantie la plus fiable.
5. **Attester** l'effacement (date, méthode, n° de série) au dossier de fin de vie.

> Pour un **retour SAV** où le disque doit rester lisible par le SAV : n'effacer
> que l'étape 2 et 3, et retirer la licence (`licenses/`).
