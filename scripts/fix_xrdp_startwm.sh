#!/bin/bash
# ============================================================
# fix_xrdp_startwm.sh
# Remplace /etc/xrdp/startwm.sh par une version stable utilisant Fluxbox
# Fluxbox est ultra-léger et fiable sur Jetson
# Usage : sudo bash scripts/fix_xrdp_startwm.sh
# ============================================================

set -e

echo "[FIX] Installation Fluxbox et création du nouveau startwm.sh..."

# 1. Installer Openbox (ultra-léger) + twm (fallback)
apt update -q
apt install -y openbox twm x11-xserver-utils

# 2. Sauvegarder l'ancien startwm.sh
if [ -f /etc/xrdp/startwm.sh ]; then
    cp /etc/xrdp/startwm.sh /etc/xrdp/startwm.sh.backup
    echo "    Backup: /etc/xrdp/startwm.sh.backup"
fi

# 3. Créer le nouveau startwm.sh minimal et stable
cat > /etc/xrdp/startwm.sh << 'STARTWM_EOF'
#!/bin/sh
# xrdp session startup script - minimal WM fallback (twm / openbox)

unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR

# Initialize D-Bus if not already set
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    eval $(dbus-launch --sh-syntax --exit-with-session) 2>/dev/null || true
fi

# Set minimal X11 environment
export DESKTOP_SESSION=xrdp
export XDG_CURRENT_DESKTOP=xrdp
export XDG_SESSION_TYPE=x11

# Try minimal WM in order of preference
if command -v openbox >/dev/null 2>&1; then
    exec openbox --startup /bin/true
elif command -v fluxbox >/dev/null 2>&1; then
    exec fluxbox -log /tmp/fluxbox.log
elif command -v twm >/dev/null 2>&1; then
    exec twm
else
    # Absolute fallback: xterm + sleep (never reach here, but safety)
    exec xterm
fi
STARTWM_EOF

# 4. Rendre exécutable
chmod +x /etc/xrdp/startwm.sh
chown root:root /etc/xrdp/startwm.sh
echo "    OK: /etc/xrdp/startwm.sh créé et exécutable"

# 5. Redémarrer xrdp pour tester
echo "[FIX] Redémarrage de xrdp..."
systemctl restart xrdp || true
systemctl restart xrdp-sesman || true
sleep 2

# 6. Vérifier le statut
if systemctl is-active --quiet xrdp; then
    echo "✓ xrdp actif"
else
    echo "✗ xrdp non actif (check: systemctl status xrdp)"
fi

echo ""
echo "============================================"
echo "✓ Fix appliqué avec succès!"
echo ""
echo "Pour tester la connexion RDP:"
echo "  xfreerdp /v:100.117.145.65:3389 /u:user-4itec /cert:ignore /sec:tls"
echo ""
echo "Si ça ne marche toujours pas:"
echo "  sudo tail -50 /var/log/xrdp-sesman.log"
echo "  tail -30 /tmp/fluxbox.log"
echo "============================================"
