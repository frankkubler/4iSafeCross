#!/bin/bash
# ============================================================
# setup-camera-net.sh — sous-réseau caméras dédié et ISOLÉ (nmcli)
# ------------------------------------------------------------
# Mesure compensatoire CS-1143-01 (le transport RTSP des caméras TP-Link VIGI
# S485/S455 ne peut pas être chiffré pour un client tiers) : le segment vidéo
# est un réseau L2 dédié, sans passerelle, sans DNS, SANS route par défaut,
# IPv6 désactivé — les caméras n'ont aucun chemin sortant.
#
# Deux topologies :
#   - switch PoE externe : une seule interface Jetson vers le switch
#       sudo bash setup-camera-net.sh <iface>
#   - 3 ports Jetson pontés :
#       sudo bash setup-camera-net.sh --bridge <iface2> <iface3> <iface4>
#
# Les noms d'interface Jetson (enPxpxsx / ethN) se lisent avec :  ip -br link
#
# Plan d'adressage (nouvelles installations) : Jetson 192.168.0.100/24,
# caméras 192.168.0.60/.61/.62. Site HAM (plan précédent, eth1 / 192.168.2.x) :
# NE PAS exécuter ce script — sa config réseau est propre au site.
# ============================================================
set -euo pipefail

CAM_SUBNET_IP="192.168.0.100/24"
CON_NAME="cameras"
BR_NAME="br-cameras"

if [ "$(id -u)" -ne 0 ]; then echo "À lancer en root (sudo)." >&2; exit 1; fi
command -v nmcli >/dev/null || { echo "nmcli requis (NetworkManager)." >&2; exit 1; }

MODE="single"
if [ "${1:-}" = "--bridge" ]; then MODE="bridge"; shift; fi
if [ "$#" -eq 0 ]; then
    echo "Usage : sudo bash $0 <iface>                       # switch PoE externe"
    echo "        sudo bash $0 --bridge <iface2> <iface3> <iface4>   # 3 ports pontés"
    echo
    echo "Interfaces disponibles :"; ip -br link | sed 's/^/  /'
    exit 1
fi
IFACES=("$@")

echo "== Nettoyage d'éventuelles connexions caméras existantes =="
nmcli -t -f NAME connection show | grep -E "^(${CON_NAME}|${BR_NAME}|${CON_NAME}-slave-)" \
    | while read -r c; do nmcli connection delete "$c" || true; done

_ipv4_hardening() {
    # aucune passerelle, aucun DNS, jamais de route par défaut, IPv6 off
    nmcli connection modify "$1" \
        ipv4.method manual ipv4.addresses "$CAM_SUBNET_IP" \
        ipv4.gateway "" ipv4.dns "" ipv4.never-default yes \
        ipv4.ignore-auto-dns yes ipv4.ignore-auto-routes yes \
        ipv6.method disabled \
        connection.autoconnect yes
}

if [ "$MODE" = "single" ]; then
    IF="${IFACES[0]}"
    echo "== Interface unique : $IF -> $CAM_SUBNET_IP (isolée) =="
    nmcli connection add type ethernet ifname "$IF" con-name "$CON_NAME"
    _ipv4_hardening "$CON_NAME"
    nmcli connection up "$CON_NAME"
else
    echo "== Pont $BR_NAME sur : ${IFACES[*]} -> $CAM_SUBNET_IP (isolé) =="
    nmcli connection add type bridge ifname "$BR_NAME" con-name "$BR_NAME" \
        bridge.stp no
    _ipv4_hardening "$BR_NAME"
    for IF in "${IFACES[@]}"; do
        nmcli connection add type ethernet ifname "$IF" \
            con-name "${CON_NAME}-slave-${IF}" master "$BR_NAME"
    done
    nmcli connection up "$BR_NAME"
fi

echo
echo "== Contrôles =="
ip -br addr show | grep -E "192\.168\.0\.100" && echo "  IP caméras OK" || echo "  !! IP non posée"
if ip route show default | grep -q .; then
    echo "  !! Une route par défaut existe :"; ip route show default | sed 's/^/     /'
    echo "     (elle doit venir de eth1/maintenance ou être absente — PAS du segment caméras)"
else
    echo "  Aucune route par défaut — OK pour un boîtier autonome"
fi
echo
echo "Vérifier ensuite : scripts/harden-run.sh (section « Segment caméras »)."
