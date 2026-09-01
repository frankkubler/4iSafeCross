#!/bin/bash
# ============================================================
# harden-run.sh — passage du boîtier en état RUN (livraison)
# ------------------------------------------------------------
# Retire les commodités de MISE AU POINT qui n'ont pas leur place sur un
# boîtier autonome en exploitation, et vérifie qu'il ne reste que le VNC
# local sur le port de maintenance.
#
# Couvre : CS-127-01 / CS-127-02 (Internet/messagerie proscrits),
#          CS-1143-04 (protocoles de connexion à distance désactivés),
#          CS-1143-05 (besoin de communication externe).
#
# À exécuter sur le Jetson, en root, AVANT la recette. Idempotent.
# Consigner la sortie au dossier de recette (attestation de retrait).
# ============================================================
set -uo pipefail

RC=0
note()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn()  { printf '  \033[33m!\033[0m %s\n' "$*"; RC=1; }
step()  { printf '\n\033[1m[%s]\033[0m %s\n' "$1" "$2"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "À lancer en root (sudo)." >&2
    exit 1
fi

CURRENT_USER="$(logname 2>/dev/null || echo "${SUDO_USER:-user-4itec}")"
USER_HOME="$(eval echo "~${CURRENT_USER}")"

# ── 1. RustDesk ────────────────────────────────────────────
step 1 "RustDesk — désinstallation"
systemctl disable --now rustdesk 2>/dev/null || true
apt-get purge -y rustdesk 2>/dev/null || true
rm -f "${USER_HOME}/.config/autostart/rustdesk-xhost.desktop"
rm -f /etc/systemd/system/rustdesk.service.d/override.conf
rmdir /etc/systemd/system/rustdesk.service.d 2>/dev/null || true
if command -v rustdesk >/dev/null 2>&1 || systemctl list-unit-files 2>/dev/null | grep -q '^rustdesk'; then
    warn "RustDesk encore présent — vérifier manuellement"
else
    note "RustDesk absent"
fi

# ── 2. Tailscale ──────────────────────────────────────────
step 2 "Tailscale — désinstallation"
if command -v tailscale >/dev/null 2>&1; then
    tailscale down 2>/dev/null || true
    tailscale logout 2>/dev/null || true
fi
systemctl disable --now tailscaled 2>/dev/null || true
apt-get purge -y tailscale 2>/dev/null || true
if command -v tailscale >/dev/null 2>&1; then
    warn "Tailscale encore présent — vérifier manuellement"
else
    note "Tailscale absent"
    # Rétablir le blocage UFW de tailscale0 (le script VNC le fait sans --tailscale)
    if command -v bash >/dev/null 2>&1 && [ -f "$(dirname "$0")/install_vnc_jetson.sh" ]; then
        note "Relancer si besoin : sudo bash $(dirname "$0")/install_vnc_jetson.sh --subnet 192.168.3.0/24"
    fi
fi

# ── 3. Bot Telegram ───────────────────────────────────────
step 3 "Bot Telegram — désactivation"
ENV_FILE=""
for f in "${USER_HOME}/4iSafeCross/.env" "${USER_HOME}/github/4iSafeCross/.env" /data/4isafecross/.env; do
    [ -f "$f" ] && ENV_FILE="$f" && break
done
CFG=""
for f in /data/4isafecross/config/config.ini "${USER_HOME}/4iSafeCross/config/config.ini"; do
    [ -f "$f" ] && CFG="$f" && break
done
if [ -n "$CFG" ] && grep -qiE '^\s*TELEGRAM_ENABLED\s*=\s*(true|1|yes)' "$CFG"; then
    warn "TELEGRAM_ENABLED est activé dans $CFG — le passer à false"
else
    note "Bot Telegram désactivé (TELEGRAM_ENABLED != true)"
fi
if [ -n "$ENV_FILE" ] && grep -qE '^\s*TELEGRAM_TOKEN\s*=\s*\S' "$ENV_FILE"; then
    warn "TELEGRAM_TOKEN encore renseigné dans $ENV_FILE — le vider si Telegram n'est plus utilisé"
fi

# ── 4. Clé 4G / connectivité sortante ─────────────────────
step 4 "Connectivité sortante"
if ip route show default 2>/dev/null | grep -q .; then
    warn "Une route par défaut existe encore : $(ip route show default | head -1)"
    warn "→ retirer la clé 4G et toute route par défaut avant la recette"
else
    note "Aucune route par défaut (boîtier autonome)"
fi
for IF in $(ls /sys/class/net 2>/dev/null); do
    case "$IF" in
        wwan*|ppp*|usb0|lte*|"cdc-wdm"*)
            warn "Interface cellulaire détectée : $IF (clé 4G ?) — à retirer"
            ;;
    esac
done

# ── 5. Segment caméras (mesure compensatoire CS-1143-01) ──
step 5 "Segment caméras — isolation"
# Sous-réseau caméras : dérivé de config.ini [RTSP] HOST (1re IP → /24), sinon défaut.
CAM_NET="192.168.0.0/24"
if [ -n "$CFG" ]; then
    CAM_IP1="$(grep -E '^\s*HOST\s*=' "$CFG" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
    [ -n "$CAM_IP1" ] && CAM_NET="$(echo "$CAM_IP1" | cut -d. -f1-3).0/24"
fi
CAM_PREFIX="$(echo "$CAM_NET" | cut -d/ -f1 | cut -d. -f1-3)"
echo "  Sous-réseau caméras : $CAM_NET"

# a) pas de route par défaut via une interface du segment caméras
CAM_DEFROUTE="$(ip route show default 2>/dev/null | grep -E "src ${CAM_PREFIX}\.|dev (br-cameras|cameras)" || true)"
if [ -n "$CAM_DEFROUTE" ]; then
    warn "Route par défaut liée au segment caméras : $CAM_DEFROUTE — le segment doit être SANS passerelle"
else
    note "Aucune route par défaut via le segment caméras"
fi

# b) qui répond sur le /24 ? (doit être uniquement des caméras TP-Link)
for i in $(seq 1 254); do ping -c1 -W1 "${CAM_PREFIX}.${i}" >/dev/null 2>&1 & done
wait
FOUND=0; NONCAM=0
NEIGH="$(ip neigh show 2>/dev/null | grep -E "^${CAM_PREFIX//./\\.}\.[0-9]+ .* lladdr " || true)"
while read -r line; do
    [ -z "$line" ] && continue
    ip="${line%% *}"
    mac="$(echo "$line" | grep -oE '([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}' | head -1)"
    [ -z "$mac" ] && continue
    FOUND=$((FOUND+1))
    OUI="$(echo "$mac" | tr 'a-f' 'A-F' | cut -d: -f1-3)"
    case "$OUI" in
        EC:75:0C|E4:C3:2A|00:31:92|A4:2B:B0|30:DE:4B|B0:4E:26|D8:07:B6|1C:61:B4|50:C7:BF|CC:68:B6)
            note "  $ip  $mac  (TP-Link)" ;;
        *)
            warn "  $ip  $mac  — OUI $OUI NON TP-Link : équipement étranger sur le segment caméras ?"
            NONCAM=$((NONCAM+1)) ;;
    esac
done <<< "$NEIGH"
[ "$FOUND" -eq 0 ] && warn "Aucune caméra détectée sur $CAM_NET (câblage / alimentation ?)"
[ "$NONCAM" -eq 0 ] && [ "$FOUND" -gt 0 ] && note "Segment caméras : $FOUND caméra(s), uniquement TP-Link"

# c) attestation : une caméra ne doit PAS joindre Internet (contrôle manuel possible
#    depuis la caméra ou via un mirror de port). Rappel :
note "À attester à la recette : une caméra ne peut joindre aucune IP publique (segment sans route)"

# ── 6. UFW / fail2ban ─────────────────────────────────────
step 6 "Pare-feu"
if ufw status 2>/dev/null | grep -q "Status: active"; then
    note "UFW actif"
    ufw status | sed 's/^/    /'
else
    warn "UFW inactif — relancer scripts/install_vnc_jetson.sh"
fi
systemctl is-active --quiet fail2ban && note "fail2ban actif" || warn "fail2ban inactif"

# ── 7. Récapitulatif ──────────────────────────────────────
step 7 "Récapitulatif"
if [ "$RC" -eq 0 ]; then
    printf '\n  \033[32mÉtat RUN : OK.\033[0m Seul accès résiduel attendu : VNC chiffré local sur le port de maintenance.\n'
else
    printf '\n  \033[33mÉtat RUN : points à traiter ci-dessus avant la recette.\033[0m\n'
fi
exit "$RC"
