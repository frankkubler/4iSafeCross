#!/bin/bash
# ============================================================
# install_xrdp_jetson.sh
# Installation xrdp sur Jetson Orin NX (JetPack / Ubuntu)
# Remplace gnome-remote-desktop
# xrdp écoute sur toutes les interfaces, UFW filtre le sous-réseau maintenance
# Usage : sudo bash install_xrdp_jetson.sh [--gnome|--xfce|--fluxbox] [--vnc] [--subnet 192.168.3.0/24] [--tailscale]
# ============================================================

set -e

USE_GNOME=false
USE_XFCE=false
USE_FLUXBOX=false
USE_VNC=false
USE_TAILSCALE=false
MAINTENANCE_SUBNET="192.168.3.0/24"   # Sous-réseau du port de maintenance

while [[ $# -gt 0 ]]; do
    case "$1" in
        --gnome) USE_GNOME=true; shift ;;
        --xfce)   USE_XFCE=true; shift ;;
        --fluxbox) USE_FLUXBOX=true; shift ;;
        --vnc) USE_VNC=true; shift ;;
        --tailscale) USE_TAILSCALE=true; shift ;;
        --subnet) MAINTENANCE_SUBNET="$2"; shift 2 ;;
        *) echo "Argument inconnu : $1"; exit 1 ;;
    esac
done

# Mode par defaut: GNOME si aucun WM explicite n'est demande
if [ "$USE_GNOME" = false ] && [ "$USE_XFCE" = false ] && [ "$USE_FLUXBOX" = false ]; then
    USE_GNOME=true
fi

if ([ "$USE_XFCE" = true ] || [ "$USE_FLUXBOX" = true ] || [ "$USE_GNOME" = true ]); then
    count=0
    [ "$USE_XFCE" = true ] && count=$((count + 1))
    [ "$USE_FLUXBOX" = true ] && count=$((count + 1))
    [ "$USE_GNOME" = true ] && count=$((count + 1))
    if [ $count -gt 1 ]; then
        echo "Options incompatibles : --gnome, --xfce et --fluxbox s'excluent mutuellement"
        exit 1
    fi
fi

CURRENT_USER=$(logname 2>/dev/null || echo "$SUDO_USER")
USER_HOME=$(eval echo "~$CURRENT_USER")

echo "============================================"
echo " Installation xrdp - Jetson Orin NX"
echo " Utilisateur  : $CURRENT_USER"
echo " Mode         : $([ "$USE_XFCE" = true ] && echo XFCE || ([ "$USE_FLUXBOX" = true ] && echo Fluxbox || ([ "$USE_GNOME" = true ] && echo GNOME || echo 'GNOME (défaut)')))$([ "$USE_VNC" = true ] && echo ' + VNC (port 5999)')"
echo " Sous-réseau  : $MAINTENANCE_SUBNET (port maintenance RJ45)"
echo " Tailscale    : $([ "$USE_TAILSCALE" = true ] && echo 'ACTIVÉ (autorisation RDP via tailscale0)' || echo 'DÉSACTIVÉ')"
echo "============================================"
echo ""

# --- 1. Désactiver gnome-remote-desktop ---
echo "[1/9] Désactivation de gnome-remote-desktop..."
sudo -u "$CURRENT_USER" systemctl --user stop gnome-remote-desktop 2>/dev/null || true
sudo -u "$CURRENT_USER" systemctl --user disable gnome-remote-desktop 2>/dev/null || true
sudo -u "$CURRENT_USER" systemctl --user mask gnome-remote-desktop 2>/dev/null || true
fuser -k 3389/tcp 2>/dev/null || true
echo "    OK"

# --- 2. Installation des paquets ---
echo "[2/9] Installation des paquets..."
apt update -q
apt install -y xrdp xorgxrdp dbus-x11 fluxbox xterm
if [ "$USE_XFCE" = true ]; then
    apt install -y xfce4 xfce4-goodies xfce4-terminal
fi
if [ "$USE_VNC" = true ]; then
    apt install -y tigervnc-standalone-server
fi
echo "    OK"

# --- 3. Permissions SSL ---
echo "[3/9] Permissions SSL pour xrdp..."
adduser xrdp ssl-cert
echo "    OK"

# --- 4. Configuration startwm.sh ---
echo "[4/9] Configuration /etc/xrdp/startwm.sh..."
if [ "$USE_XFCE" = true ]; then
cat > /etc/xrdp/startwm.sh << 'STARTWM'
#!/bin/sh
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR

if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    eval $(dbus-launch --sh-syntax --exit-with-session)
fi

export DESKTOP_SESSION=xfce
export XDG_CURRENT_DESKTOP=XFCE
export XDG_SESSION_TYPE=x11
exec startxfce4
STARTWM
elif [ "$USE_FLUXBOX" = true ]; then
cat > /etc/xrdp/startwm.sh << 'STARTWM'
#!/bin/sh
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR

if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    eval $(dbus-launch --sh-syntax --exit-with-session)
fi

export DESKTOP_SESSION=fluxbox
export XDG_CURRENT_DESKTOP=fluxbox
export XDG_SESSION_TYPE=x11
export XDG_SESSION_DESKTOP=fluxbox
exec fluxbox
STARTWM
elif [ "$USE_GNOME" = true ]; then
cat > /etc/xrdp/startwm.sh << 'STARTWM'
#!/bin/sh
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR

if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    eval $(dbus-launch --sh-syntax --exit-with-session)
fi

export DESKTOP_SESSION=ubuntu
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
export XDG_SESSION_TYPE=x11
export XDG_SESSION_DESKTOP=ubuntu
exec gnome-session --session=ubuntu
STARTWM
fi
chmod +x /etc/xrdp/startwm.sh
echo "    OK"

# --- 5. Configuration session utilisateur ---
echo "[5/9] Configuration session pour $CURRENT_USER..."
if [ "$USE_XFCE" = true ]; then
    cat > "$USER_HOME/.xsession" << 'XSESSION'
#!/bin/sh
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR
setxkbmap fr
startxfce4
XSESSION
    chmod +x "$USER_HOME/.xsession"
    chown "$CURRENT_USER:$CURRENT_USER" "$USER_HOME/.xsession"
    rm -f "$USER_HOME/.xsessionrc"
elif [ "$USE_FLUXBOX" = true ]; then
    cat > "$USER_HOME/.xsession" << 'XSESSION'
#!/bin/sh
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR
setxkbmap fr
exec fluxbox
XSESSION
    chmod +x "$USER_HOME/.xsession"
    chown "$CURRENT_USER:$CURRENT_USER" "$USER_HOME/.xsession"
    rm -f "$USER_HOME/.xsessionrc"
else
    rm -f "$USER_HOME/.xsession"
    cat > "$USER_HOME/.xsessionrc" << 'XSESSIONRC'
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
export XDG_SESSION_TYPE=x11
export XDG_SESSION_DESKTOP=ubuntu
setxkbmap fr
gsettings set org.gnome.desktop.interface enable-animations false 2>/dev/null || true
XSESSIONRC
    chown "$CURRENT_USER:$CURRENT_USER" "$USER_HOME/.xsessionrc"
fi
echo "    OK"

# --- 6. Fix clavier AZERTY ---
echo "[6/9] Configuration clavier AZERTY..."
xrdp-genkeymap /etc/xrdp/km-0000040c.ini 2>/dev/null || true
ln -sf /etc/xrdp/km-0000040c.ini /etc/xrdp/km-00000000.ini
mkdir -p /etc/X11/xorg.conf.d
cat > /etc/X11/xorg.conf.d/00-keyboard.conf << 'XKEYBOARD'
Section "InputClass"
    Identifier "system-keyboard"
    MatchIsKeyboard "on"
    Option "XkbLayout" "fr"
    Option "XkbVariant" ""
EndSection
XKEYBOARD
localectl set-keymap fr 2>/dev/null || true
localectl set-x11-keymap fr 2>/dev/null || true
echo "    OK"

# --- 7. xrdp écoute sur toutes les interfaces (0.0.0.0) ---
echo "[7/9] Configuration xrdp.ini (écoute 0.0.0.0 + optimisation)..."
cp /etc/xrdp/xrdp.ini /etc/xrdp/xrdp.ini.bak

python3 << 'PYEOF'
import re

with open('/etc/xrdp/xrdp.ini', 'r') as f:
    content = f.read()

# Ecoute sur toutes les interfaces - le filtrage est géré par UFW
content = re.sub(r'^port=.*', 'port=3389', content, flags=re.MULTILINE)

# Buffer TCP
if 'tcp_send_buffer_bytes' not in content:
    content = content.replace('[globals]', '[globals]\ntcp_send_buffer_bytes=4194304', 1)
else:
    content = re.sub(r'^tcp_send_buffer_bytes=.*', 'tcp_send_buffer_bytes=4194304', content, flags=re.MULTILINE)

# Codec RemoteFX
if '[Xorg]' in content and 'codec_id' not in content:
    content = content.replace('[Xorg]', '[Xorg]\ncodec_id=2\nquality=0\nmax_bpp=24', 1)

with open('/etc/xrdp/xrdp.ini', 'w') as f:
    f.write(content)

print("    xrdp.ini modifié avec succès")
PYEOF
echo "    OK"

# --- 8. UFW : autoriser maintenance + option Tailscale ---
echo "[8/9] Configuration pare-feu (maintenance locale + option Tailscale)..."
if ufw status 2>/dev/null | grep -q "Status: active"; then
    # Supprimer toute règle existante sur 3389
    ufw delete allow 3389/tcp 2>/dev/null || true
    # N autoriser que le sous-réseau du port de maintenance
    ufw allow from "$MAINTENANCE_SUBNET" to any port 3389 proto tcp
    echo "    UFW : 3389/tcp autorisé depuis $MAINTENANCE_SUBNET"
    if [ "$USE_TAILSCALE" = true ]; then
        ufw allow in on tailscale0 to any port 3389 proto tcp
        echo "    UFW : 3389/tcp autorisé aussi via tailscale0"
    fi
else
    echo "    UFW inactif - activation recommandée :"
    echo "    sudo ufw enable"
    echo "    sudo ufw allow from $MAINTENANCE_SUBNET to any port 3389 proto tcp"
    if [ "$USE_TAILSCALE" = true ]; then
        echo "    sudo ufw allow in on tailscale0 to any port 3389 proto tcp"
    fi
fi
echo "    OK"

# --- 9. Activer et démarrer xrdp ---
echo "[9/9] Démarrage de xrdp..."
systemctl enable xrdp
systemctl restart xrdp
echo "    OK"

# --- 10. Configuration VNC (si --vnc) ---
if [ "$USE_VNC" = true ]; then
    echo "[10] Configuration TigerVNC..."
    VNC_DISPLAY=99
    VNC_PORT=5999

    # Répertoire .vnc
    mkdir -p "$USER_HOME/.vnc"
    chown "$CURRENT_USER:$CURRENT_USER" "$USER_HOME/.vnc"

    # xstartup VNC (utilise le même WM que xrdp)
    if [ "$USE_XFCE" = true ]; then
cat > "$USER_HOME/.vnc/xstartup" << 'VNCSTART'
#!/bin/sh
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    eval $(dbus-launch --sh-syntax --exit-with-session)
fi
export DESKTOP_SESSION=xfce
export XDG_CURRENT_DESKTOP=XFCE
export XDG_SESSION_TYPE=x11
setxkbmap fr
exec startxfce4
VNCSTART
    elif [ "$USE_GNOME" = true ]; then
cat > "$USER_HOME/.vnc/xstartup" << 'VNCSTART'
#!/bin/sh
unset DBUS_SESSION_BUS_ADDRESS

# GNOME attend un runtime utilisateur valide. Sans session PAM/systemd,
# on peut ne pas avoir /run/user/<uid> dans le contexte VNC.
USER_ID=$(id -u)
if [ -z "$XDG_RUNTIME_DIR" ] || [ ! -d "$XDG_RUNTIME_DIR" ]; then
    if [ -d "/run/user/$USER_ID" ]; then
        export XDG_RUNTIME_DIR="/run/user/$USER_ID"
    else
        export XDG_RUNTIME_DIR="/tmp/runtime-$USER"
        mkdir -p "$XDG_RUNTIME_DIR"
        chmod 700 "$XDG_RUNTIME_DIR"
    fi
fi

# Crée une vraie session bus DBus pour GNOME.
if command -v dbus-run-session >/dev/null 2>&1; then
    DBUS_PREFIX="dbus-run-session --"
else
    if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
        eval $(dbus-launch --sh-syntax --exit-with-session)
    fi
    DBUS_PREFIX=""
fi

export DESKTOP_SESSION=ubuntu
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
export XDG_SESSION_TYPE=x11
export XDG_SESSION_DESKTOP=ubuntu
setxkbmap fr
exec sh -lc "$DBUS_PREFIX gnome-session --session=ubuntu"
VNCSTART
    else
cat > "$USER_HOME/.vnc/xstartup" << 'VNCSTART'
#!/bin/sh
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    eval $(dbus-launch --sh-syntax --exit-with-session)
fi
export DESKTOP_SESSION=fluxbox
export XDG_CURRENT_DESKTOP=fluxbox
export XDG_SESSION_TYPE=x11
setxkbmap fr
exec fluxbox
VNCSTART
    fi
    chmod +x "$USER_HOME/.vnc/xstartup"
    chown "$CURRENT_USER:$CURRENT_USER" "$USER_HOME/.vnc/xstartup"

    # Neutraliser les anciennes configurations TigerVNC qui peuvent forcer un autre WM
    if [ -f "$USER_HOME/.vnc/config" ]; then
        cp "$USER_HOME/.vnc/config" "$USER_HOME/.vnc/config.bak.$(date +%Y%m%d-%H%M%S)"
        rm -f "$USER_HOME/.vnc/config"
    fi
    if [ -d "$USER_HOME/.vnc/config.d" ]; then
        mv "$USER_HOME/.vnc/config.d" "$USER_HOME/.vnc/config.d.bak.$(date +%Y%m%d-%H%M%S)"
    fi

    # Service systemd TigerVNC
    cat > /etc/systemd/system/vncserver@.service << VNCSVC
[Unit]
Description=TigerVNC server display :%i
After=network.target

[Service]
Type=forking
User=$CURRENT_USER
PIDFile=/tmp/.X%i-lock
ExecStartPre=-/usr/bin/vncserver -kill :%i > /dev/null 2>&1
ExecStart=/usr/bin/vncserver :%i -geometry 1920x1080 -depth 24 -localhost no -xstartup $USER_HOME/.vnc/xstartup
ExecStop=/usr/bin/vncserver -kill :%i
Restart=on-failure

[Install]
WantedBy=multi-user.target
VNCSVC

    systemctl daemon-reload
    systemctl enable vncserver@${VNC_DISPLAY}.service

    # UFW : autoriser le port VNC
    if ufw status 2>/dev/null | grep -q "Status: active"; then
        ufw delete allow ${VNC_PORT}/tcp 2>/dev/null || true
        ufw allow from "$MAINTENANCE_SUBNET" to any port $VNC_PORT proto tcp
        echo "    UFW : ${VNC_PORT}/tcp autorisé depuis $MAINTENANCE_SUBNET"
        if [ "$USE_TAILSCALE" = true ]; then
            ufw allow in on tailscale0 to any port $VNC_PORT proto tcp
            echo "    UFW : ${VNC_PORT}/tcp autorisé aussi via tailscale0"
        fi
    fi

    echo "    OK"
    echo ""
    echo " !! IMPORTANT : définir le mot de passe VNC AVANT de démarrer le service :"
    echo "    sudo -u $CURRENT_USER vncpasswd"
    echo "    sudo systemctl start vncserver@${VNC_DISPLAY}.service"
fi

# --- Vérification finale ---
echo ""
echo "============================================"
echo " Vérification"
echo "============================================"
systemctl is-active xrdp && echo " xrdp         : ACTIF" || echo " xrdp         : ERREUR"
ss -tlnp | grep "3389" && echo " Port 3389    : EN ECOUTE" || echo " Port 3389    : NON TROUVÉ"
ls /etc/xrdp/km-00000000.ini > /dev/null 2>&1 && echo " Clavier fr   : OK" || echo " Clavier fr   : NON CONFIGURÉ"
if [ "$USE_VNC" = true ]; then
    which vncserver > /dev/null 2>&1 && echo " TigerVNC     : INSTALLÉ" || echo " TigerVNC     : ERREUR"
    systemctl is-enabled vncserver@99.service 2>/dev/null && echo " vncserver@99 : SERVICE ACTIVÉ (port 5999)" || true
fi
if [ "$USE_TAILSCALE" = true ]; then
    echo " Accès RDP    : $MAINTENANCE_SUBNET + interface tailscale0 (via UFW)"
else
    echo " Accès RDP    : $MAINTENANCE_SUBNET uniquement (via UFW)"
fi

echo ""
echo "============================================"
echo " Installation terminée !"
echo "============================================"
echo "   Protocole   : RDP"
echo "   Port        : 3389"
echo "   Utilisateur : $CURRENT_USER"
echo "   Session     : $([ "$USE_XFCE" = true ] && echo 'XFCE (léger)' || ([ "$USE_FLUXBOX" = true ] && echo 'Fluxbox (stable)' || ([ "$USE_GNOME" = true ] && echo 'GNOME' || echo 'GNOME (défaut)')))"
if [ "$USE_VNC" = true ]; then
echo ""
echo " Accès VNC (TigerVNC - display :99, port 5999) :"
echo "   1. Définir le mot de passe  : sudo -u $CURRENT_USER vncpasswd"
echo "   2. Démarrer le service      : sudo systemctl start vncserver@99.service"
echo "   3. Vérifier le statut       : sudo systemctl status vncserver@99.service"
echo "   4. Connexion Remmina        : VNC | hôte:5999 (ou IP Tailscale:5999)"
echo "   (Le service redémarre automatiquement à chaque boot après vncpasswd)"
fi
echo ""
echo " Workflow port maintenance :"
echo "   1. Brancher le câble RJ45"
echo "   2. Ouvrir NetworkManager (GUI) et forcer l IP manuellement sur le port maintenance"
echo "      IPv4: Manuel | Adresse: 192.168.3.122/24 | Passerelle: vide"
echo "      DNS: vide | Route par défaut: désactivée (never-default)"
echo "   3. Se connecter depuis Remmina sur 192.168.3.122:3389"
if [ "$USE_TAILSCALE" = true ]; then
echo ""
echo " Accès distant sécurisé (option Tailscale) :"
echo "   1. Installer Tailscale : curl -fsSL https://tailscale.com/install.sh | sh"
echo "   2. Joindre le tailnet : sudo tailscale up"
echo "   3. Utiliser l IP Tailscale du Jetson dans votre client RDP"
if command -v tailscale >/dev/null 2>&1; then
    TS_IP4=$(tailscale ip -4 2>/dev/null | head -n 1 || true)
    TS_STATUS_JSON=$(tailscale status --json 2>/dev/null || true)
    TS_DNS=""

    if [ -n "$TS_STATUS_JSON" ]; then
        TS_DNS=$(printf '%s' "$TS_STATUS_JSON" | python3 -c 'import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
print(data.get("Self", {}).get("DNSName", "").rstrip("."))' 2>/dev/null || true)
    fi

    if [ -n "$TS_IP4" ]; then
        echo "   IP Tailscale détectée : $TS_IP4"
        echo "   RDP via Tailscale IP : ${TS_IP4}:3389"
    else
        echo "   IP Tailscale : non détectée (vérifier: sudo tailscale up)"
    fi

    if [ -n "$TS_DNS" ]; then
        echo "   MagicDNS détecté     : $TS_DNS"
        echo "   RDP via MagicDNS     : ${TS_DNS}:3389"
    fi
else
    echo "   tailscale introuvable (installation requise pour afficher l IP)"
fi
fi
echo ""
echo " Pour créer le profil maintenance NetworkManager :"
cat << 'NMCLI_EXAMPLE'
     sudo nmcli connection add type ethernet ifname enP1p1s0 \
         con-name maintenance \
         ipv4.method manual \
         ipv4.addresses 192.168.3.122/24 \
         ipv4.never-default yes \
         connection.autoconnect no
NMCLI_EXAMPLE
echo "============================================"
