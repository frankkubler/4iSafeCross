#!/bin/bash
# ============================================================
# install_xrdp_jetson.sh
# Installation xrdp sur Jetson Orin NX (JetPack / Ubuntu)
# Remplace gnome-remote-desktop
# Usage : sudo bash install_xrdp_jetson.sh [--xfce]
# ============================================================

set -e

USE_XFCE=false
if [[ "$1" == "--xfce" ]]; then
    USE_XFCE=true
fi

CURRENT_USER=$(logname 2>/dev/null || echo "$SUDO_USER")
USER_HOME=$(eval echo "~$CURRENT_USER")

echo "============================================"
echo " Installation xrdp - Jetson Orin NX"
echo " Utilisateur : $CURRENT_USER"
echo " Home        : $USER_HOME"
echo " Mode        : $([ "$USE_XFCE" = true ] && echo XFCE || echo GNOME)"
echo "============================================"
echo ""

# --- 1. Désactiver gnome-remote-desktop ---
echo "[1/8] Désactivation de gnome-remote-desktop..."
sudo -u "$CURRENT_USER" systemctl --user stop gnome-remote-desktop 2>/dev/null || true
sudo -u "$CURRENT_USER" systemctl --user disable gnome-remote-desktop 2>/dev/null || true
sudo -u "$CURRENT_USER" systemctl --user mask gnome-remote-desktop 2>/dev/null || true
fuser -k 3389/tcp 2>/dev/null || true
echo "    OK"

# --- 2. Installation des paquets ---
echo "[2/8] Installation des paquets..."
apt update -q
apt install -y xrdp xorgxrdp dbus-x11

if [ "$USE_XFCE" = true ]; then
    apt install -y xfce4 xfce4-goodies xfce4-terminal
fi
echo "    OK"

# --- 3. Permissions SSL ---
echo "[3/8] Permissions SSL pour xrdp..."
adduser xrdp ssl-cert
echo "    OK"

# --- 4. Configuration startwm.sh ---
echo "[4/8] Configuration /etc/xrdp/startwm.sh..."
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

# --- 5. Configuration .xsessionrc utilisateur ---
echo "[5/8] Configuration session pour $CURRENT_USER..."
if [ "$USE_XFCE" = true ]; then
    cat > "$USER_HOME/.xsession" << 'XSESSION'
#!/bin/sh
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR
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
gsettings set org.gnome.desktop.interface enable-animations false 2>/dev/null || true
XSESSIONRC
    chown "$CURRENT_USER:$CURRENT_USER" "$USER_HOME/.xsessionrc"
fi
echo "    OK"

# --- 6. Fix clavier AZERTY (session + Polkit/root) ---
echo "[6/8] Configuration clavier AZERTY..."

# Keymap xrdp niveau système (couvre les dialogues Polkit/root)
xrdp-genkeymap /etc/xrdp/km-0000040c.ini 2>/dev/null || true
ln -sf /etc/xrdp/km-0000040c.ini /etc/xrdp/km-00000000.ini

# Forcer AZERTY via xorg.conf.d pour toute session X11 (Polkit inclus)
mkdir -p /etc/X11/xorg.conf.d
cat > /etc/X11/xorg.conf.d/00-keyboard.conf << 'XKEYBOARD'
Section "InputClass"
    Identifier "system-keyboard"
    MatchIsKeyboard "on"
    Option "XkbLayout" "fr"
    Option "XkbVariant" ""
EndSection
XKEYBOARD

# Appliquer aussi au niveau système
localectl set-keymap fr 2>/dev/null || true
localectl set-x11-keymap fr 2>/dev/null || true

# Ajouter setxkbmap dans la session utilisateur
if [ "$USE_XFCE" = true ]; then
    echo "setxkbmap fr" >> "$USER_HOME/.xsession"
else
    echo "setxkbmap fr" >> "$USER_HOME/.xsessionrc"
fi
echo "    OK"

# --- 7. Optimisation xrdp.ini ---
echo "[7/8] Optimisation xrdp.ini..."
cp /etc/xrdp/xrdp.ini /etc/xrdp/xrdp.ini.bak

# Buffer TCP
grep -q "^tcp_send_buffer_bytes" /etc/xrdp/xrdp.ini \
    && sed -i 's/^tcp_send_buffer_bytes.*/tcp_send_buffer_bytes=4194304/' /etc/xrdp/xrdp.ini \
    || sed -i '/^\[globals\]/a tcp_send_buffer_bytes=4194304' /etc/xrdp/xrdp.ini

# Codec RemoteFX
if grep -q "^\[Xorg\]" /etc/xrdp/xrdp.ini; then
    sed -i '/^\[Xorg\]/a max_bpp=24\nquality=0\ncodec_id=2' /etc/xrdp/xrdp.ini
fi
echo "    OK"

# --- 8. Activer et démarrer xrdp ---
echo "[8/8] Activation et démarrage de xrdp..."
systemctl enable xrdp
systemctl restart xrdp

if ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow 3389/tcp
    echo "    UFW : port 3389 ouvert"
fi
echo "    OK"

# --- Vérification finale ---
echo ""
echo "============================================"
echo " Vérification"
echo "============================================"
systemctl is-active xrdp && echo " xrdp       : ACTIF" || echo " xrdp       : ERREUR"
ss -tlnp | grep -q 3389 && echo " Port 3389  : EN ECOUTE" || echo " Port 3389  : NON TROUVÉ"
ls /etc/xrdp/km-00000000.ini > /dev/null 2>&1 && echo " Clavier fr : OK" || echo " Clavier fr : NON CONFIGURÉ"

echo ""
echo "============================================"
echo " Installation terminée !"
echo "============================================"
echo " Connecte-toi depuis Remmina :"
echo "   Protocole   : RDP"
echo "   Port        : 3389"
echo "   Utilisateur : $CURRENT_USER"
if [ "$USE_XFCE" = true ]; then
    echo "   Session     : XFCE (léger, fluide)"
else
    echo "   Session     : GNOME X11"
fi
echo ""
echo " En cas d écran noir, relance avec --xfce :"
echo "   sudo bash install_xrdp_jetson.sh --xfce"
echo "============================================"
