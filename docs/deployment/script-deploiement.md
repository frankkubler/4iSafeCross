# Déploiement Jetson — Accès distant RustDesk

## Contexte

Jetson Orin NX headless avec accès distant via RustDesk self-hosted.
Problème résolu : RustDesk retournait `connection refused` / `cannot open display` après installation de xrdp + XFCE.

---

## Architecture des displays

| Composant | Display | Port | Démarrage |
|---|---|---|---|
| TigerVNC (permanent) | `:1` | 5901 | Au boot via systemd |
| xrdp | `:99` | 3389 | À la connexion RDP |
| RustDesk | capture `:1` | — | Service systemd |

> **Note** : Le display `:99` créé par xrdp n'existe que pendant une session RDP active. RustDesk doit utiliser `:1` (TigerVNC), permanent au boot.

---

## Prérequis

- Jetson Orin NX avec L4T Ubuntu
- GDM3 avec autologin configuré
- TigerVNC installé (`tigervnc-standalone-server`)
- xrdp installé (optionnel, pour accès RDP)
- RustDesk installé et configuré (self-hosted)
- `xserver-xorg-video-dummy` installé

---

## Configuration GDM3 (autologin + X11)

Fichier `/etc/gdm3/custom.conf` :

```ini
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=user-4itec

# Forcer X11 (Wayland non supporté par RustDesk)
WaylandEnable=false
```

---

## Script de détection display dummy

Fichier `/usr/local/bin/switch-display.sh` :

```bash
#!/bin/bash
# Bascule entre le driver nvidia (HDMI connecté) et le driver dummy (headless)
# Déployé via systemd : check-dummy-display.service

sleep 10

HDMI_STATUS=$(cat /sys/class/drm/card1-HDMI-A-1/status)

if [ "$HDMI_STATUS" = "connected" ]; then
  if [ -f /usr/share/X11/xorg.conf.d/xorg.conf ]; then
    sudo mv /usr/share/X11/xorg.conf.d/xorg.conf /usr/share/X11/xorg.conf.d/xorg.conf.bak
    echo "HDMI connected. Dummy driver configuration disabled."
  else
    echo "HDMI connected, but xorg.conf does not exist."
  fi
else
  if [ -f /usr/share/X11/xorg.conf.d/xorg.conf.bak ]; then
    sudo mv /usr/share/X11/xorg.conf.d/xorg.conf.bak /usr/share/X11/xorg.conf.d/xorg.conf
    sudo X :0 -config /usr/share/X11/xorg.conf.d/xorg.conf &
    echo "HDMI not connected. Dummy driver configuration enabled."
  else
    echo "HDMI not connected, but xorg.conf.bak does not exist."
  fi
fi
```

### Fichier dummy requis : `/usr/share/X11/xorg.conf.d/xorg.conf.bak`

Ce fichier **doit exister** pour que le script fonctionne en mode headless.
Si absent (par ex. après installation xrdp/XFCE), le recréer :

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

### Service systemd associé : `check-dummy-display.service`

```ini
[Unit]
Description=Check and configure dummy display if HDMI not connected
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/switch-display.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Activation :
```bash
sudo systemctl enable check-dummy-display.service
```

---

## Configuration RustDesk — override systemd

RustDesk tourne en tant que root mais doit accéder au display TigerVNC (`:1`) de l'utilisateur.

Fichier `/etc/systemd/system/rustdesk.service.d/override.conf` :

```ini
[Service]
Environment=DISPLAY=:1
Environment=XAUTHORITY=/home/user-4itec/.Xauthority
```

Application :
```bash
sudo systemctl daemon-reload
sudo systemctl restart rustdesk
```

---

## Autostart XFCE — xhost permanent

Le cookie MIT-MAGIC-COOKIE-1 change à chaque session. L'autostart renouvelle l'autorisation root à chaque connexion.

Fichier `~/.config/autostart/rustdesk-xhost.desktop` à copier depuis `autostart/rustdesk-xhost.desktop` du dépôt.

Création rapide :
```bash
mkdir -p ~/.config/autostart
tee ~/.config/autostart/rustdesk-xhost.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=RustDesk xhost fix
Exec=bash -c "DISPLAY=:1 xhost +local:root"
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF
```

---

## Diagnostic

```bash
# Vérifier les displays actifs
ls /tmp/.X*-lock
xrandr --listmonitors

# Vérifier le cookie XAUTHORITY
xauth -f ~/.Xauthority list | grep ":1"

# Logs RustDesk
sudo journalctl -u rustdesk -n 50 --no-pager | grep -iE "display|xauth|error|refused"

# Status du service dummy
sudo systemctl status check-dummy-display.service

# Tester l'accès au display :1
DISPLAY=:1 XAUTHORITY=/home/user-4itec/.Xauthority xdpyinfo | grep "name of display"
```

---

## Checklist de déploiement

- [ ] `/etc/gdm3/custom.conf` : autologin + WaylandEnable=false
- [ ] `/usr/share/X11/xorg.conf.d/xorg.conf.bak` : config dummy créée
- [ ] `check-dummy-display.service` : enabled + status OK
- [ ] `/etc/systemd/system/rustdesk.service.d/override.conf` : DISPLAY=:1 + XAUTHORITY
- [ ] `~/.config/autostart/rustdesk-xhost.desktop` : xhost +local:root au démarrage
- [ ] Connexion RustDesk testée depuis client
