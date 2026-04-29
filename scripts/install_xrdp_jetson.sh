#!/bin/bash
# ============================================================
# install_xrdp_jetson.sh
# Installation VNC sur Jetson Orin NX (JetPack / Ubuntu)
# Configuration unique : XFCE + TigerVNC
# Usage : sudo bash install_xrdp_jetson.sh [--subnet 192.168.3.0/24] [--tailscale]
# ============================================================

set -euo pipefail

USE_TAILSCALE=false
MAINTENANCE_SUBNET="192.168.3.0/24"
VNC_DISPLAY=99
VNC_PORT=5999

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tailscale)
            USE_TAILSCALE=true
            shift
            ;;
        --subnet)
            if [[ $# -lt 2 ]]; then
                echo "Argument manquant pour --subnet"
                exit 1
            fi
            MAINTENANCE_SUBNET="$2"
            shift 2
            ;;
        *)
            echo "Argument inconnu : $1"
            echo "Usage : sudo bash install_xrdp_jetson.sh [--subnet 192.168.3.0/24] [--tailscale]"
            exit 1
            ;;
    esac
done

CURRENT_USER=$(logname 2>/dev/null || echo "${SUDO_USER:-}")
if [[ -z "$CURRENT_USER" ]]; then
    echo "Impossible de déterminer l'utilisateur courant"
    exit 1
fi
USER_HOME=$(eval echo "~$CURRENT_USER")

echo "============================================"
echo " Installation VNC - Jetson Orin NX"
echo " Utilisateur  : $CURRENT_USER"
echo " Session      : XFCE + TigerVNC"
echo " Port VNC     : $VNC_PORT (display :$VNC_DISPLAY)"
echo " Sous-réseau  : $MAINTENANCE_SUBNET (port maintenance RJ45)"
echo " Tailscale    : $([ "$USE_TAILSCALE" = true ] && echo 'ACTIVÉ (autorisation VNC via tailscale0)' || echo 'DÉSACTIVÉ')"
echo "============================================"
echo ""

echo "[1/5] Installation des paquets..."
apt update -q
apt install -y dbus-x11 tigervnc-standalone-server xfce4 xfce4-goodies xfce4-terminal xterm ufw
echo "    OK"

echo "[2/5] Configuration de la session XFCE pour VNC..."
mkdir -p "$USER_HOME/.vnc"
chown "$CURRENT_USER:$CURRENT_USER" "$USER_HOME/.vnc"

cat > "$USER_HOME/.vnc/xstartup" << 'VNCSTART'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS

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

if command -v dbus-run-session >/dev/null 2>&1; then
    exec dbus-run-session -- sh -lc 'setxkbmap fr; export DESKTOP_SESSION=xfce; export XDG_CURRENT_DESKTOP=XFCE; export XDG_SESSION_TYPE=x11; exec startxfce4'
else
    exec sh -lc 'eval $(dbus-launch --sh-syntax --exit-with-session); setxkbmap fr; export DESKTOP_SESSION=xfce; export XDG_CURRENT_DESKTOP=XFCE; export XDG_SESSION_TYPE=x11; exec startxfce4'
fi
VNCSTART
chmod +x "$USER_HOME/.vnc/xstartup"
chown "$CURRENT_USER:$CURRENT_USER" "$USER_HOME/.vnc/xstartup"

if [ -f "$USER_HOME/.vnc/config" ]; then
    cp "$USER_HOME/.vnc/config" "$USER_HOME/.vnc/config.bak.$(date +%Y%m%d-%H%M%S)"
    rm -f "$USER_HOME/.vnc/config"
fi
if [ -d "$USER_HOME/.vnc/config.d" ]; then
    mv "$USER_HOME/.vnc/config.d" "$USER_HOME/.vnc/config.d.bak.$(date +%Y%m%d-%H%M%S)"
fi
echo "    OK"

echo "[3/5] Création du service systemd TigerVNC..."
cat > /etc/systemd/system/vncserver@.service << VNCSVC
[Unit]
Description=TigerVNC server display :%i
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$USER_HOME
KillMode=mixed
TimeoutStopSec=10
ExecStartPre=-/usr/bin/vncserver -kill :%i > /dev/null 2>&1
ExecStart=/usr/bin/vncserver -fg :%i -geometry 1920x1080 -depth 24 -localhost no -xstartup $USER_HOME/.vnc/xstartup
ExecStop=-/usr/bin/timeout 8 /usr/bin/vncserver -kill :%i
ExecStopPost=-/usr/bin/pkill -KILL -f "Xtigervnc.*:%i|Xvnc.*:%i|vncserver.*:%i"
ExecStopPost=-/usr/bin/rm -f /tmp/.X%i-lock /tmp/.X11-unix/X%i
Restart=on-failure

[Install]
WantedBy=multi-user.target
VNCSVC
systemctl daemon-reload
systemctl enable "vncserver@${VNC_DISPLAY}.service"
echo "    OK"

echo "[4/5] Configuration du pare-feu..."
ufw --force delete allow 3389/tcp 2>/dev/null || true
ufw --force delete allow ${VNC_PORT}/tcp 2>/dev/null || true
ufw --force delete allow in on tailscale0 to any port $VNC_PORT proto tcp 2>/dev/null || true

SSH_CLIENT_IP=""
if [ -n "${SSH_CLIENT:-}" ]; then
    SSH_CLIENT_IP=$(echo "$SSH_CLIENT" | awk '{print $1}')
elif [ -n "${SSH_CONNECTION:-}" ]; then
    SSH_CLIENT_IP=$(echo "$SSH_CONNECTION" | awk '{print $1}')
fi

if [ -n "$SSH_CLIENT_IP" ]; then
    ufw --force delete allow from "$SSH_CLIENT_IP" to any port 22 proto tcp 2>/dev/null || true
    ufw allow from "$SSH_CLIENT_IP" to any port 22 proto tcp
    echo "    UFW : SSH autorisé depuis $SSH_CLIENT_IP (anti lockout)"
fi

ufw default deny incoming
ufw default allow outgoing
echo "    UFW : politiques par défaut appliquées (deny incoming / allow outgoing)"

ufw allow from "$MAINTENANCE_SUBNET" to any port $VNC_PORT proto tcp
echo "    UFW : ${VNC_PORT}/tcp autorisé depuis $MAINTENANCE_SUBNET"

if [ "$USE_TAILSCALE" = true ]; then
    ufw allow in on tailscale0 to any port $VNC_PORT proto tcp
    echo "    UFW : ${VNC_PORT}/tcp autorisé aussi via tailscale0"
else
    echo "    UFW : accès tailscale0 non autorisé"
fi

if ! ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw --force enable
    echo "    UFW : activé automatiquement"
fi
ufw reload
echo "    UFW : configuration rechargée"
echo "    OK"

echo "[5/5] Vérification finale..."
which vncserver > /dev/null 2>&1 && echo " TigerVNC     : INSTALLÉ" || echo " TigerVNC     : ERREUR"
systemctl is-enabled "vncserver@${VNC_DISPLAY}.service" 2>/dev/null && echo " vncserver@${VNC_DISPLAY} : SERVICE ACTIVÉ" || true

echo ""
echo "============================================"
echo " Installation terminée !"
echo "============================================"
echo "   Session     : XFCE"
echo "   Protocole   : VNC"
echo "   Port        : ${VNC_PORT}"
echo "   Display     : :${VNC_DISPLAY}"
echo "   Utilisateur : $CURRENT_USER"
echo ""
echo " Étapes suivantes :"
echo "   1. Définir le mot de passe  : sudo -u $CURRENT_USER vncpasswd"
echo "   2. Démarrer le service      : sudo systemctl start vncserver@${VNC_DISPLAY}.service"
echo "   3. Vérifier le statut       : sudo systemctl status vncserver@${VNC_DISPLAY}.service"
echo "   4. Connexion Remmina        : VNC | hôte:${VNC_PORT}"
echo ""
echo " Workflow port maintenance :"
echo "   1. Brancher le câble RJ45"
echo "   2. Ouvrir NetworkManager (GUI) et forcer l'IP manuellement sur le port maintenance"
echo "      IPv4: Manuel | Adresse: 192.168.3.122/24 | Passerelle: vide"
echo "      DNS: vide | Route par défaut: désactivée (never-default)"
echo "   3. Se connecter depuis Remmina sur 192.168.3.122:${VNC_PORT}"
if [ "$USE_TAILSCALE" = true ]; then
    echo ""
    echo " Accès distant sécurisé (option Tailscale) :"
    echo "   1. Installer Tailscale : curl -fsSL https://tailscale.com/install.sh | sh"
    echo "   2. Joindre le tailnet : sudo tailscale up"
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
            echo "   VNC via Tailscale IP : ${TS_IP4}:${VNC_PORT}"
        else
            echo "   IP Tailscale : non détectée (vérifier: sudo tailscale up)"
        fi

        if [ -n "$TS_DNS" ]; then
            echo "   MagicDNS détecté     : $TS_DNS"
            echo "   VNC via MagicDNS     : ${TS_DNS}:${VNC_PORT}"
        fi
    else
        echo "   tailscale introuvable (installation requise pour afficher l'IP)"
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
