#!/bin/bash
# ============================================================
# install_xrdp_jetson.sh
# Installation xrdp sur Jetson Orin NX (JetPack / Ubuntu)
# Remplace gnome-remote-desktop
# Usage : sudo bash install_xrdp_jetson.sh [--xfce] [--ip 192.168.3.X]
# Exemple : sudo bash install_xrdp_jetson.sh --ip 192.168.3.122
# ============================================================

set -e

USE_XFCE=false
RJ45_IP=""

# Parsing des arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --xfce) USE_XFCE=true; shift ;;
        --ip) RJ45_IP="$2"; shift 2 ;;
        *) echo "Argument inconnu : $1"; exit 1 ;;
    esac
done

CURRENT_USER=$(logname 2>/dev/null || echo "$SUDO_USER")
USER_HOME=$(eval echo "~$CURRENT_USER")

# Si aucune IP fournie, détecter automatiquement la première IP non-loopback non-WiFi
if [ -z "$RJ45_IP" ]; then
    RJ45_IP=$(ip -4 addr show | grep -v "127.0.0.1" | grep -v "docker" | grep -v "br-" | grep -v "wl" | grep "inet " | head -1 | awk '{print $2}' | cut -d/ -f1)
    echo "[INFO] Aucune IP spécifiée, détection automatique : $RJ45_IP"
    echo "[INFO] Pour forcer une IP : sudo bash $0 --ip 192.168.3.XX"
fi

# Extraire le sous-réseau depuis l'IP (ex: 192.168.3.122 → 192.168.3.0/24)
RJ45_SUBNET=$(echo "$RJ45_IP" | awk -F. '{print $1"."$2"."$3".0/24"}')

echo "============================================"
echo " Installation xrdp - Jetson Orin NX"
echo " Utilisateur : $CURRENT_USER"
echo " Home        : $USER_HOME"
echo " Mode        : $([ "$USE_XFCE" = true ] && echo XFCE || echo GNOME)"
echo " Ecoute xrdp : $RJ45_IP:3389 (RJ45 uniquement)"
echo " Sous-réseau : $RJ45_SUBNET"
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

# --- 6. Fix clavier AZERTY (session + Polkit/root) ---
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

# --- 7. Restreindre xrdp à l'interface RJ45 uniquement ---
echo "[7/9] Restriction xrdp sur RJ45 ($RJ45_IP) uniquement..."
cp /etc/xrdp/xrdp.ini /etc/xrdp/xrdp.ini.bak

# Remplacer le port par la syntaxe avec IP fixée
sed -i "s|^port=.*|port=tcp://${RJ45_IP}:3389|" /etc/xrdp/xrdp.ini

echo "    OK"

# --- 8. Optimisation xrdp.ini ---
echo "[8/9] Optimisation xrdp.ini..."
grep -q "^tcp_send_buffer_bytes" /etc/xrdp/xrdp.ini     && sed -i 's/^tcp_send_buffer_bytes.*/tcp_send_buffer_bytes=4194304/' /etc/xrdp/xrdp.ini     || sed -i '/^\[globals\]/a tcp_send_buffer_bytes=4194304' /etc/xrdp/xrdp.ini

if grep -q "^\[Xorg\]" /etc/xrdp/xrdp.ini; then
    sed -i '/^\[Xorg\]/a max_bpp=24
quality=0
codec_id=2' /etc/xrdp/xrdp.ini
fi
echo "    OK"

# --- 9. UFW + démarrage xrdp ---
echo "[9/9] Pare-feu et démarrage de xrdp..."
if ufw status 2>/dev/null | grep -q "Status: active"; then
    # Supprimer toute règle existante sur 3389
    ufw delete allow 3389/tcp 2>/dev/null || true
    # N'autoriser que le sous-réseau RJ45
    ufw allow from "$RJ45_SUBNET" to any port 3389 proto tcp
    echo "    UFW : 3389/tcp autorisé uniquement depuis $RJ45_SUBNET"
fi

systemctl enable xrdp
systemctl restart xrdp
echo "    OK"

# --- Vérification finale ---
echo ""
echo "============================================"
echo " Vérification"
echo "============================================"
systemctl is-active xrdp && echo " xrdp         : ACTIF" || echo " xrdp         : ERREUR"
ss -tlnp | grep -q 3389 && echo " Port 3389    : EN ECOUTE" || echo " Port 3389    : NON TROUVÉ"
ss -tlnp | grep 3389
ls /etc/xrdp/km-00000000.ini > /dev/null 2>&1 && echo " Clavier fr   : OK" || echo " Clavier fr   : NON CONFIGURÉ"
echo " Restriction  : $RJ45_IP:3389 (RJ45 uniquement)"

echo ""
echo "============================================"
echo " Installation terminée !"
echo "============================================"
echo " Connecte-toi depuis Remmina :"
echo "   Protocole   : RDP"
echo "   Serveur     : $RJ45_IP"
echo "   Port        : 3389"
echo "   Utilisateur : $CURRENT_USER"
if [ "$USE_XFCE" = true ]; then
    echo "   Session     : XFCE (léger, fluide)"
else
    echo "   Session     : GNOME X11"
fi
echo ""
echo " Connexion WiFi/4G : BLOQUÉE (RJ45 uniquement)"
echo ""
echo " Pour changer l IP RJ45 plus tard :"
echo "   sudo sed -i 's|^port=.*|port=tcp://NOUVELLE_IP:3389|' /etc/xrdp/xrdp.ini"
echo "   sudo systemctl restart xrdp"
echo "============================================"