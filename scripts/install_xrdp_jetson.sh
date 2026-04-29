#!/bin/bash
# ============================================================
# install_xrdp_jetson.sh
# Installation xrdp sur Jetson Orin NX (JetPack / Ubuntu)
# Remplace gnome-remote-desktop
# xrdp écoute sur toutes les interfaces, UFW filtre le sous-réseau maintenance
# Usage : sudo bash install_xrdp_jetson.sh [--xfce] [--subnet 192.168.3.0/24]
# ============================================================

set -e

USE_XFCE=false
MAINTENANCE_SUBNET="192.168.3.0/24"   # Sous-réseau du port de maintenance

while [[ $# -gt 0 ]]; do
    case "$1" in
        --xfce)   USE_XFCE=true; shift ;;
        --subnet) MAINTENANCE_SUBNET="$2"; shift 2 ;;
        *) echo "Argument inconnu : $1"; exit 1 ;;
    esac
done

CURRENT_USER=$(logname 2>/dev/null || echo "$SUDO_USER")
USER_HOME=$(eval echo "~$CURRENT_USER")

echo "============================================"
echo " Installation xrdp - Jetson Orin NX"
echo " Utilisateur  : $CURRENT_USER"
echo " Mode         : $([ "$USE_XFCE" = true ] && echo XFCE || echo GNOME)"
echo " Sous-réseau  : $MAINTENANCE_SUBNET (port maintenance RJ45)"
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
apt install -y xrdp xorgxrdp dbus-x11
if [ "$USE_XFCE" = true ]; then
    apt install -y xfce4 xfce4-goodies xfce4-terminal
fi
echo "    OK"

# --- 3. Permissions SSL ---
echo "[3/9] Permissions SSL pour xrdp..."
adduser xrdp ssl-cert
echo "    OK"

# --- 4. Configuration startwm.sh ---
echo "[4/9] Configuration /etc/xrdp/startwm.sh..."
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

test -x /etc/X11/Xsession && exec /etc/X11/Xsession
exec /bin/sh /etc/X11/Xsession
STARTWM
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
else
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

# --- 8. UFW : autoriser uniquement le sous-réseau maintenance ---
echo "[8/9] Configuration pare-feu (sous-réseau maintenance uniquement)..."
if ufw status 2>/dev/null | grep -q "Status: active"; then
    # Supprimer toute règle existante sur 3389
    ufw delete allow 3389/tcp 2>/dev/null || true
    # N autoriser que le sous-réseau du port de maintenance
    ufw allow from "$MAINTENANCE_SUBNET" to any port 3389 proto tcp
    echo "    UFW : 3389/tcp autorisé uniquement depuis $MAINTENANCE_SUBNET"
else
    echo "    UFW inactif - activation recommandée :"
    echo "    sudo ufw enable"
    echo "    sudo ufw allow from $MAINTENANCE_SUBNET to any port 3389 proto tcp"
fi
echo "    OK"

# --- 9. Activer et démarrer xrdp ---
echo "[9/9] Démarrage de xrdp..."
systemctl enable xrdp
systemctl restart xrdp
echo "    OK"

# --- Vérification finale ---
echo ""
echo "============================================"
echo " Vérification"
echo "============================================"
systemctl is-active xrdp && echo " xrdp         : ACTIF" || echo " xrdp         : ERREUR"
ss -tlnp | grep "3389" && echo " Port 3389    : EN ECOUTE" || echo " Port 3389    : NON TROUVÉ"
ls /etc/xrdp/km-00000000.ini > /dev/null 2>&1 && echo " Clavier fr   : OK" || echo " Clavier fr   : NON CONFIGURÉ"
echo " Accès RDP    : $MAINTENANCE_SUBNET uniquement (via UFW)"

echo ""
echo "============================================"
echo " Installation terminée !"
echo "============================================"
echo "   Protocole   : RDP"
echo "   Port        : 3389"
echo "   Utilisateur : $CURRENT_USER"
echo "   Session     : $([ "$USE_XFCE" = true ] && echo 'XFCE (léger)' || echo 'GNOME X11')"
echo ""
echo " Workflow port maintenance :"
echo "   1. Brancher le câble RJ45"
echo "   2. Ouvrir NetworkManager (GUI) et forcer l IP manuellement sur le port maintenance"
echo "      IPv4: Manuel | Adresse: 192.168.3.122/24 | Passerelle: vide"
echo "      DNS: vide | Route par défaut: désactivée (never-default)"
echo "   3. Se connecter depuis Remmina sur 192.168.3.122:3389"
