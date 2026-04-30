#!/bin/bash
# ============================================================
# security_audit.sh — Audit de sécurité Linux / Jetson / Ubuntu
# Usage : sudo bash security_audit.sh [--json] [--fix]
# --json  : sortie JSON pour intégration CI/CD
# --fix   : appliquer automatiquement les correctifs sans risque
# ============================================================

set -euo pipefail

# ── Couleurs ────────────────────────────────────────────────
RED='\033[0;31m'; ORANGE='\033[0;33m'; GREEN='\033[0;32m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

# ── Options ─────────────────────────────────────────────────
JSON_MODE=false
AUTO_FIX=false
for arg in "$@"; do
    case "$arg" in
        --json) JSON_MODE=true ;;
        --fix)  AUTO_FIX=true ;;
    esac
done

# ── Variables de score ───────────────────────────────────────
SCORE=0
MAX_SCORE=0
ISSUES=()
WARNINGS=()
PASSED=()

# ── Fonctions utilitaires ────────────────────────────────────
check_pass()    { PASSED+=("$1"); ((SCORE++)) || true; ((MAX_SCORE++)) || true; }
check_warn()    { WARNINGS+=("$1"); ((MAX_SCORE++)) || true; }
check_fail()    { ISSUES+=("$1"); ((MAX_SCORE++)) || true; }
check_info()    { ((MAX_SCORE++)) || true; }

banner() {
    echo ""
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${BLUE}  $1${NC}"
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════${NC}"
}

ok()   { [ "$JSON_MODE" = false ] && echo -e "  ${GREEN}✅  $1${NC}"; }
warn() { [ "$JSON_MODE" = false ] && echo -e "  ${ORANGE}⚠️   $1${NC}"; }
fail() { [ "$JSON_MODE" = false ] && echo -e "  ${RED}🔴  $1${NC}"; }
info() { [ "$JSON_MODE" = false ] && echo -e "  ${BLUE}ℹ️   $1${NC}"; }
fix()  { [ "$JSON_MODE" = false ] && echo -e "  ${ORANGE}🔧  Fix : $1${NC}"; }

# ═══════════════════════════════════════════════════════════
#  1. SYSTÈME DE BASE
# ═══════════════════════════════════════════════════════════
banner "1. Système de base"

# Kernel
KERNEL=$(uname -r)
info "Kernel : $KERNEL"

# Uptime
UPTIME=$(uptime -p 2>/dev/null || echo "inconnu")
info "Uptime : $UPTIME"

# OS
OS=$(lsb_release -d 2>/dev/null | cut -f2 || cat /etc/os-release | grep PRETTY | cut -d= -f2 | tr -d '"')
info "OS : $OS"

# Arch
ARCH=$(uname -m)
info "Architecture : $ARCH"

# Mises à jour disponibles
UPGRADABLE=$(apt list --upgradable 2>/dev/null | tail -n +2 | wc -l)
if [ "$UPGRADABLE" -eq 0 ]; then
    ok "Système à jour"
    check_pass "Système à jour"
elif [ "$UPGRADABLE" -lt 10 ]; then
    warn "$UPGRADABLE paquets à mettre à jour"
    check_warn "$UPGRADABLE paquets à mettre à jour"
    fix "sudo apt upgrade -y"
else
    fail "$UPGRADABLE paquets à mettre à jour (dont probablement des correctifs de sécurité)"
    check_fail "$UPGRADABLE paquets en attente"
    fix "sudo apt upgrade -y && sudo apt autoremove -y"
fi

# Mises à jour automatiques
if systemctl is-active --quiet unattended-upgrades 2>/dev/null || \
   [ -f /etc/apt/apt.conf.d/20auto-upgrades ]; then
    ok "Mises à jour automatiques actives"
    check_pass "Mises à jour auto"
else
    warn "Mises à jour de sécurité automatiques non configurées"
    check_warn "Mises à jour auto absentes"
    fix "sudo apt install unattended-upgrades -y && sudo dpkg-reconfigure --priority=low unattended-upgrades"
fi

# ═══════════════════════════════════════════════════════════
#  2. PARE-FEU (UFW)
# ═══════════════════════════════════════════════════════════
banner "2. Pare-feu UFW"

UFW_STATUS=$(sudo ufw status 2>/dev/null | head -1)
if echo "$UFW_STATUS" | grep -q "actif\|active"; then
    ok "UFW actif"
    check_pass "UFW actif"

    # Default deny incoming
    if sudo ufw status verbose 2>/dev/null | grep -q "deny (incoming)"; then
        ok "Default : deny incoming"
        check_pass "Default deny incoming"
    else
        fail "Default incoming n'est pas 'deny' — tout est ouvert par défaut"
        check_fail "UFW default non sécurisé"
        fix "sudo ufw default deny incoming && sudo ufw default allow outgoing"
        if [ "$AUTO_FIX" = true ]; then
            sudo ufw default deny incoming
            sudo ufw default allow outgoing
            ok "FIX appliqué : default deny incoming"
        fi
    fi
else
    fail "UFW désactivé ou absent"
    check_fail "UFW inactif"
    fix "sudo ufw enable && sudo ufw default deny incoming && sudo ufw default allow outgoing"
    if [ "$AUTO_FIX" = true ]; then
        sudo ufw enable
        sudo ufw default deny incoming
        ok "FIX appliqué : UFW activé"
    fi
fi

# ═══════════════════════════════════════════════════════════
#  3. PORTS RÉSEAU EXPOSÉS
# ═══════════════════════════════════════════════════════════
banner "3. Ports réseau exposés"

# Ports écoutant sur 0.0.0.0 (excluant localhost)
EXPOSED=$(sudo ss -tlnp 2>/dev/null | grep "0\.0\.0\.0:" | grep -v "127\.0\.0\." || true)

if [ -z "$EXPOSED" ]; then
    ok "Aucun port exposé sur 0.0.0.0"
    check_pass "Pas de port exposé"
else
    while IFS= read -r line; do
        PORT=$(echo "$line" | awk '{print $4}' | cut -d: -f2)
        PROCESS=$(echo "$line" | grep -oP 'users:\(\("\K[^"]+' || echo "inconnu")

        case "$PORT" in
            22)   warn "SSH (22) exposé sur toutes interfaces — restreindre à VPN/LAN"
                  check_warn "SSH sur 0.0.0.0"
                  fix "sudo ufw allow from <IP_AUTORISEE> to any port 22 proto tcp" ;;
            23)   fail "Telnet (23) exposé — protocole non chiffré, DÉSACTIVER"
                  check_fail "Telnet exposé"
                  fix "sudo systemctl stop telnet && sudo ufw deny 23" ;;
            80|443) warn "HTTP/HTTPS ($PORT) exposé — normal si serveur web intentionnel"
                  check_warn "Port web $PORT";;
            111)  warn "rpcbind (111) exposé — désactiver si pas de NFS"
                  check_warn "rpcbind exposé"
                  fix "sudo systemctl mask rpcbind rpcbind.socket" ;;
            3389) fail "RDP (3389) exposé sur 0.0.0.0 — risque critique sur internet"
                  check_fail "RDP exposé internet"
                  fix "sudo ufw deny 3389 && restreindre à VPN/LAN uniquement" ;;
            5900|5901|5902|5999)
                  warn "VNC ($PORT) exposé — restreindre à réseau local uniquement"
                  check_warn "VNC exposé"
                  fix "sudo ufw allow from 192.168.x.0/24 to any port $PORT" ;;
            6443) warn "Kubernetes API (6443) exposé — sécuriser avec certificats"
                  check_warn "K8s API exposé" ;;
            8080|8000|8001|8002|8003|8004|8005)
                  warn "Port API ($PORT/$PROCESS) exposé — vérifier si intentionnel"
                  check_warn "API $PORT exposée"
                  fix "Si non nécessaire : sudo ufw deny $PORT ou binder sur 127.0.0.1" ;;
            *)    warn "Port $PORT ($PROCESS) exposé sur 0.0.0.0 — vérifier si nécessaire"
                  check_warn "Port inconnu $PORT exposé" ;;
        esac
    done <<< "$EXPOSED"
fi

# Vérifier si un port est accessible depuis internet via 4G/WAN
WAN_IFACE=$(ip route | grep default | awk '{print $5}' | head -1)
if [ -n "$WAN_IFACE" ]; then
    WAN_IP=$(ip addr show "$WAN_IFACE" | grep "inet " | awk '{print $2}' | cut -d/ -f1)
    info "Interface WAN détectée : $WAN_IFACE ($WAN_IP)"
fi

# ═══════════════════════════════════════════════════════════
#  4. DOCKER
# ═══════════════════════════════════════════════════════════
banner "4. Docker"

if command -v docker &>/dev/null; then
    ok "Docker installé : $(docker --version | cut -d' ' -f3 | tr -d ',')"

    # Ports exposés sur 0.0.0.0
    DOCKER_EXPOSED=$(docker ps --format "{{.Names}}: {{.Ports}}" 2>/dev/null | grep "0\.0\.0\.0" || true)
    if [ -z "$DOCKER_EXPOSED" ]; then
        ok "Aucun conteneur Docker exposé sur 0.0.0.0"
        check_pass "Docker ports sécurisés"
    else
        fail "Conteneurs exposés sur 0.0.0.0 (contourne UFW) :"
        check_fail "Docker bypass UFW"
        while IFS= read -r c; do
            fail "  → $c"
            fix "Dans docker-compose.yml : changer \"PORT:PORT\" en \"127.0.0.1:PORT:PORT\""
        done <<< "$DOCKER_EXPOSED"
    fi

    # Conteneurs en root
    PRIV=$(docker ps -q 2>/dev/null | xargs -I{} docker inspect {} --format '{{.Name}}: Privileged={{.HostConfig.Privileged}}' 2>/dev/null | grep "true" || true)
    if [ -z "$PRIV" ]; then
        ok "Aucun conteneur en mode privilégié"
        check_pass "Docker non privilégié"
    else
        fail "Conteneurs en mode privilégié (risque d'escalade) :"
        check_fail "Docker privileged"
        echo "$PRIV" | while read -r p; do fail "  → $p"; done
    fi
else
    info "Docker non installé"
fi

# ═══════════════════════════════════════════════════════════
#  5. SSH
# ═══════════════════════════════════════════════════════════
banner "5. SSH"

if systemctl is-active --quiet ssh 2>/dev/null || systemctl is-active --quiet sshd 2>/dev/null; then
    ok "SSH actif"

    SSHD_CONFIG="/etc/ssh/sshd_config"

    # Root login
    ROOT_LOGIN=$(grep -i "^PermitRootLogin" "$SSHD_CONFIG" 2>/dev/null | awk '{print $2}' || echo "yes")
    if echo "$ROOT_LOGIN" | grep -qi "no"; then
        ok "PermitRootLogin : no"
        check_pass "SSH no root login"
    else
        fail "PermitRootLogin : $ROOT_LOGIN — désactiver l'accès root SSH"
        check_fail "SSH root login activé"
        fix "Ajouter 'PermitRootLogin no' dans /etc/ssh/sshd_config"
    fi

    # Authentification par mot de passe
    PASS_AUTH=$(grep -i "^PasswordAuthentication" "$SSHD_CONFIG" 2>/dev/null | awk '{print $2}' || echo "yes")
    if echo "$PASS_AUTH" | grep -qi "no"; then
        ok "PasswordAuthentication : no (clé uniquement)"
        check_pass "SSH clé uniquement"
    else
        warn "PasswordAuthentication : yes — préférer l'auth par clé"
        check_warn "SSH password auth"
        fix "PasswordAuthentication no dans /etc/ssh/sshd_config (après avoir déployé une clé)"
    fi

    # Port SSH
    SSH_PORT=$(grep -i "^Port " "$SSHD_CONFIG" 2>/dev/null | awk '{print $2}' || echo "22")
    if [ "$SSH_PORT" != "22" ]; then
        ok "SSH sur port non standard : $SSH_PORT"
        check_pass "SSH port non standard"
    else
        warn "SSH sur port 22 (standard) — envisager un port alternatif"
        check_warn "SSH port 22"
    fi

    # MaxAuthTries
    MAX_TRIES=$(grep -i "^MaxAuthTries" "$SSHD_CONFIG" 2>/dev/null | awk '{print $2}' || echo "6")
    if [ "$MAX_TRIES" -le 3 ] 2>/dev/null; then
        ok "MaxAuthTries : $MAX_TRIES"
        check_pass "SSH MaxAuthTries"
    else
        warn "MaxAuthTries : $MAX_TRIES — recommandé ≤ 3"
        check_warn "MaxAuthTries trop élevé"
        fix "MaxAuthTries 3 dans /etc/ssh/sshd_config"
    fi
else
    info "SSH non actif"
fi

# ═══════════════════════════════════════════════════════════
#  6. FAIL2BAN
# ═══════════════════════════════════════════════════════════
banner "6. Fail2ban"

if command -v fail2ban-client &>/dev/null && systemctl is-active --quiet fail2ban 2>/dev/null; then
    ok "Fail2ban actif"
    check_pass "Fail2ban actif"
    JAILS=$(fail2ban-client status 2>/dev/null | grep "Jail list" | cut -d: -f2 | tr -d ' ')
    ok "Jails actifs : $JAILS"

    if ! echo "$JAILS" | grep -q "sshd"; then
        warn "Jail SSH non configuré"
        check_warn "Fail2ban SSH absent"
        fix "Ajouter [sshd] dans /etc/fail2ban/jail.local"
    fi
else
    fail "Fail2ban absent ou inactif"
    check_fail "Fail2ban absent"
    fix "sudo apt install fail2ban -y && sudo systemctl enable --now fail2ban"
    if [ "$AUTO_FIX" = true ]; then
        apt install -y fail2ban &>/dev/null
        systemctl enable --now fail2ban
        ok "FIX appliqué : fail2ban installé"
    fi
fi

# ═══════════════════════════════════════════════════════════
#  7. UTILISATEURS ET PERMISSIONS
# ═══════════════════════════════════════════════════════════
banner "7. Utilisateurs et permissions"

# Utilisateurs avec UID 0 (root)
ROOT_USERS=$(awk -F: '$3==0 {print $1}' /etc/passwd | grep -v "^root$" || true)
if [ -z "$ROOT_USERS" ]; then
    ok "Aucun utilisateur UID 0 parasite (hors root)"
    check_pass "UID 0 propre"
else
    fail "Utilisateurs avec UID 0 détectés : $ROOT_USERS"
    check_fail "UID 0 parasite"
fi

# Comptes sans mot de passe
NO_PASS=$(sudo awk -F: '($2 == "" || $2 == "!") && $1 != "nobody" {print $1}' /etc/shadow 2>/dev/null | head -5 || true)
if [ -z "$NO_PASS" ]; then
    ok "Tous les comptes ont un mot de passe"
    check_pass "Mots de passe présents"
else
    fail "Comptes sans mot de passe : $NO_PASS"
    check_fail "Comptes sans mot de passe"
fi

# Membres du groupe sudo
SUDO_MEMBERS=$(grep -E '^sudo' /etc/group | cut -d: -f4)
info "Membres sudo : $SUDO_MEMBERS"

# Connexions récentes suspectes
LAST_FAIL=$(sudo lastb 2>/dev/null | head -5 || true)
if [ -n "$LAST_FAIL" ]; then
    warn "Tentatives de connexion échouées détectées :"
    echo "$LAST_FAIL" | head -5 | while read -r l; do warn "  $l"; done
    check_warn "Tentatives de connexion échouées"
else
    ok "Aucune tentative de connexion échouée récente"
    check_pass "Pas de tentatives échouées"
fi

# ═══════════════════════════════════════════════════════════
#  8. SERVICES INUTILES
# ═══════════════════════════════════════════════════════════
banner "8. Services inutiles"

for svc in rpcbind avahi-daemon cups bluetooth telnet; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        case "$svc" in
            rpcbind)  warn "rpcbind actif — utile uniquement pour NFS"
                      check_warn "rpcbind inutile"
                      fix "sudo systemctl mask rpcbind rpcbind.socket" ;;
            avahi-daemon) warn "Avahi (mDNS) actif — exposition sur réseau local"
                      check_warn "Avahi actif"
                      fix "sudo systemctl disable --now avahi-daemon" ;;
            cups)     warn "CUPS (impression) actif — inutile sur serveur headless"
                      check_warn "CUPS inutile"
                      fix "sudo systemctl disable --now cups cups-browsed" ;;
            bluetooth) warn "Bluetooth actif — désactiver si inutilisé"
                      check_warn "Bluetooth actif"
                      fix "sudo systemctl disable --now bluetooth" ;;
            telnet)   fail "Telnet actif — protocole non chiffré, CRITIQUE"
                      check_fail "Telnet actif"
                      fix "sudo systemctl disable --now telnet && sudo apt purge telnetd" ;;
        esac
    else
        ok "$svc : désactivé"
        check_pass "$svc désactivé"
    fi
done

# ═══════════════════════════════════════════════════════════
#  9. KERNEL HARDENING (sysctl)
# ═══════════════════════════════════════════════════════════
banner "9. Kernel hardening"

declare -A SYSCTL_CHECKS=(
    ["net.ipv4.tcp_syncookies"]="1"
    ["net.ipv4.conf.all.accept_redirects"]="0"
    ["net.ipv4.conf.all.accept_source_route"]="0"
    ["net.ipv4.icmp_echo_ignore_broadcasts"]="1"
)

SYSCTL_FIX_NEEDED=false
for param in "${!SYSCTL_CHECKS[@]}"; do
    EXPECTED="${SYSCTL_CHECKS[$param]}"
    ACTUAL=$(sysctl -n "$param" 2>/dev/null || echo "N/A")
    if [ "$ACTUAL" = "$EXPECTED" ]; then
        ok "$param = $ACTUAL"
        check_pass "sysctl $param"
    else
        warn "$param = $ACTUAL (recommandé : $EXPECTED)"
        check_warn "sysctl $param non optimal"
        SYSCTL_FIX_NEEDED=true
    fi
done

if [ "$SYSCTL_FIX_NEEDED" = true ]; then
    fix "Ajouter dans /etc/sysctl.d/99-hardening.conf et relancer : sudo sysctl -p /etc/sysctl.d/99-hardening.conf"
    if [ "$AUTO_FIX" = true ]; then
        cat > /etc/sysctl.d/99-hardening.conf << 'SYSCTL'
net.ipv4.tcp_syncookies=1
net.ipv4.conf.all.accept_redirects=0
net.ipv6.conf.all.accept_redirects=0
net.ipv4.conf.all.accept_source_route=0
net.ipv4.icmp_echo_ignore_broadcasts=1
SYSCTL
        sysctl -p /etc/sysctl.d/99-hardening.conf &>/dev/null
        ok "FIX appliqué : sysctl hardening"
    fi
fi

# ═══════════════════════════════════════════════════════════
#  10. VPN / TUNNEL
# ═══════════════════════════════════════════════════════════
banner "10. VPN / Accès distant sécurisé"

VPN_FOUND=false

if ip link show tailscale0 &>/dev/null 2>&1; then
    TAILSCALE_IP=$(ip addr show tailscale0 | grep "inet " | awk '{print $2}' | cut -d/ -f1 || echo "?")
    ok "Tailscale actif — IP : $TAILSCALE_IP"
    check_pass "Tailscale VPN"
    VPN_FOUND=true
fi

if ip link show wt0 &>/dev/null 2>&1; then
    NETBIRD_IP=$(ip addr show wt0 | grep "inet " | awk '{print $2}' | cut -d/ -f1 || echo "?")
    ok "NetBird actif — IP : $NETBIRD_IP"
    check_pass "NetBird VPN"
    VPN_FOUND=true
fi

if ip link show wg0 &>/dev/null 2>&1; then
    ok "WireGuard actif (wg0)"
    check_pass "WireGuard VPN"
    VPN_FOUND=true
fi

if [ "$VPN_FOUND" = false ]; then
    warn "Aucun VPN détecté — recommandé si accès distant via internet"
    check_warn "Pas de VPN"
    fix "Installer Tailscale : curl -fsSL https://tailscale.com/install.sh | sh"
fi

# ═══════════════════════════════════════════════════════════
#  SCORE FINAL
# ═══════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  RÉSULTAT DE L'AUDIT${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════${NC}"

PERCENT=0
if [ "$MAX_SCORE" -gt 0 ]; then
    PERCENT=$(( SCORE * 100 / MAX_SCORE ))
fi

if [ "$PERCENT" -ge 85 ]; then
    COLOR=$GREEN; NIVEAU="EXCELLENT"
elif [ "$PERCENT" -ge 65 ]; then
    COLOR=$ORANGE; NIVEAU="MOYEN — améliorations recommandées"
else
    COLOR=$RED; NIVEAU="FAIBLE — actions urgentes requises"
fi

echo -e "  Score : ${COLOR}${BOLD}${SCORE}/${MAX_SCORE} (${PERCENT}%) — ${NIVEAU}${NC}"
echo ""

if [ ${#ISSUES[@]} -gt 0 ]; then
    echo -e "  ${RED}${BOLD}Problèmes critiques (${#ISSUES[@]}) :${NC}"
    for i in "${ISSUES[@]}"; do echo -e "  ${RED}  • $i${NC}"; done
    echo ""
fi

if [ ${#WARNINGS[@]} -gt 0 ]; then
    echo -e "  ${ORANGE}${BOLD}Avertissements (${#WARNINGS[@]}) :${NC}"
    for w in "${WARNINGS[@]}"; do echo -e "  ${ORANGE}  • $w${NC}"; done
    echo ""
fi

if [ ${#PASSED[@]} -gt 0 ]; then
    echo -e "  ${GREEN}${BOLD}Points validés (${#PASSED[@]}) :${NC}"
    for p in "${PASSED[@]}"; do echo -e "  ${GREEN}  • $p${NC}"; done
fi

echo ""
if [ "$AUTO_FIX" = false ] && [ ${#ISSUES[@]} -gt 0 ]; then
    echo -e "  ${ORANGE}💡 Lance avec --fix pour appliquer les correctifs sans risque automatiquement${NC}"
fi

echo -e "${BOLD}══════════════════════════════════════════════════${NC}"
echo ""

# Sortie JSON si demandé
if [ "$JSON_MODE" = true ]; then
    python3 - <<PYEOF
import json, sys
data = {
    "score": $SCORE,
    "max_score": $MAX_SCORE,
    "percent": $PERCENT,
    "issues": $(printf '%s\n' "${ISSUES[@]+"${ISSUES[@]}"}" | python3 -c "import sys,json; print(json.dumps([l.rstrip() for l in sys.stdin]))"),
    "warnings": $(printf '%s\n' "${WARNINGS[@]+"${WARNINGS[@]}"}" | python3 -c "import sys,json; print(json.dumps([l.rstrip() for l in sys.stdin]))"),
    "passed": $(printf '%s\n' "${PASSED[@]+"${PASSED[@]}"}" | python3 -c "import sys,json; print(json.dumps([l.rstrip() for l in sys.stdin]))")
}
print(json.dumps(data, indent=2, ensure_ascii=False))
PYEOF
fi
