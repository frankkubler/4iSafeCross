#!/bin/bash
# ============================================================
# setup-camera-net.sh — sous-réseau(x) caméras dédié(s) et ISOLÉ(s) (nmcli)
# ------------------------------------------------------------
# Mesure compensatoire CS-1143-01 (le transport RTSP des caméras TP-Link VIGI
# S485/S455 ne peut pas être chiffré pour un client tiers) : le segment vidéo
# est un réseau L2 dédié, sans passerelle, sans DNS, SANS route par défaut,
# IPv6 désactivé — les caméras n'ont aucun chemin sortant.
#
# Plan d'adressage standard (2026-09-10) : chaque caméra a son propre /24 —
#   caméra 1 (index 0, zones _cam0) : 172.16.10.169  →  Jetson 172.16.10.1/24
#   caméra 2 (index 1, zones _cam1) : 172.16.11.91   →  Jetson 172.16.11.1/24
# Le Jetson porte donc UNE adresse PAR sous-réseau. L'ordre des caméras dans
# config.ini [RTSP] HOST fixe leur index : ne pas l'intervertir.
#
# Deux topologies :
#   - une interface Jetson par caméra, chacune son sous-réseau, isolées entre elles :
#       sudo bash setup-camera-net.sh eth2=172.16.10.1/24 eth3=172.16.11.1/24
#   - un pont (ou un switch PoE externe derrière une seule interface) portant
#     toutes les adresses :
#       sudo bash setup-camera-net.sh --bridge 172.16.10.1/24,172.16.11.1/24 eth2 eth3 eth4
#       sudo bash setup-camera-net.sh --bridge 172.16.10.1/24,172.16.11.1/24 eth2
#
# Les noms d'interface Jetson (enPxpxsx / ethN) se lisent avec :  ip -br link
# Site HAM (plan précédent, eth1 / 192.168.2.x) : NE PAS exécuter ce script —
# sa config réseau est propre au site.
# ============================================================
set -euo pipefail

CON_NAME="cameras"
BR_NAME="br-cameras"

if [ "$(id -u)" -ne 0 ]; then echo "À lancer en root (sudo)." >&2; exit 1; fi
command -v nmcli >/dev/null || { echo "nmcli requis (NetworkManager)." >&2; exit 1; }

usage() {
    echo "Usage : sudo bash $0 <iface>=<ip/prefix> [<iface>=<ip/prefix> ...]        # une interface par caméra"
    echo "        sudo bash $0 --bridge <ip/prefix>[,<ip/prefix>...] <iface> [...]    # pont / switch, N adresses"
    echo "  ex.   sudo bash $0 eth2=172.16.10.1/24 eth3=172.16.11.1/24"
    echo "        sudo bash $0 --bridge 172.16.10.1/24,172.16.11.1/24 eth2 eth3 eth4"
    echo
    echo "Interfaces disponibles :"; ip -br link | sed 's/^/  /'
    exit 1
}
_check_addr() {
    # ip/prefix, prefixe 8..30
    [[ "$1" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/([89]|[12][0-9]|30)$ ]] \
        || { echo "Adresse invalide : « $1 » (attendu ip/prefixe, ex. 172.16.10.1/24)" >&2; exit 1; }
}

MODE="single"
BRIDGE_ADDRS=""
if [ "${1:-}" = "--bridge" ]; then
    MODE="bridge"; shift
    BRIDGE_ADDRS="${1:-}"; shift || true
    [ -n "$BRIDGE_ADDRS" ] || usage
    IFS=',' read -r -a _addrs <<< "$BRIDGE_ADDRS"
    for a in "${_addrs[@]}"; do _check_addr "$a"; done
fi
[ "$#" -eq 0 ] && usage

echo "== Nettoyage d'éventuelles connexions caméras existantes =="
nmcli -t -f NAME connection show | grep -E "^(${CON_NAME}|${BR_NAME})(-|$)" \
    | while read -r c; do nmcli connection delete "$c" || true; done

_ipv4_hardening() {
    # $1 connexion, $2 adresse(s) ip/prefix séparées par des virgules
    # aucune passerelle, aucun DNS, jamais de route par défaut, IPv6 off
    nmcli connection modify "$1" \
        ipv4.method manual ipv4.addresses "$2" \
        ipv4.gateway "" ipv4.dns "" ipv4.never-default yes \
        ipv4.ignore-auto-dns yes ipv4.ignore-auto-routes yes \
        ipv6.method disabled \
        connection.autoconnect yes
}

ALL_ADDRS=()
if [ "$MODE" = "single" ]; then
    for pair in "$@"; do
        [[ "$pair" == *=* ]] || { echo "Attendu <iface>=<ip/prefix>, reçu « $pair »" >&2; usage; }
        IF="${pair%%=*}"; ADDR="${pair#*=}"
        _check_addr "$ADDR"
        echo "== Interface $IF -> $ADDR (isolée) =="
        nmcli connection add type ethernet ifname "$IF" con-name "${CON_NAME}-${IF}"
        _ipv4_hardening "${CON_NAME}-${IF}" "$ADDR"
        nmcli connection up "${CON_NAME}-${IF}"
        ALL_ADDRS+=("$ADDR")
    done
else
    echo "== Pont $BR_NAME sur : $* -> $BRIDGE_ADDRS (isolé) =="
    nmcli connection add type bridge ifname "$BR_NAME" con-name "$BR_NAME" bridge.stp no
    _ipv4_hardening "$BR_NAME" "$BRIDGE_ADDRS"
    for IF in "$@"; do
        nmcli connection add type ethernet ifname "$IF" \
            con-name "${CON_NAME}-slave-${IF}" master "$BR_NAME"
    done
    nmcli connection up "$BR_NAME"
    ALL_ADDRS=("${_addrs[@]}")
fi

echo
echo "== Contrôles =="
for a in "${ALL_ADDRS[@]}"; do
    ip -br addr show | grep -q "${a%%/*}" && echo "  $a posée" || echo "  !! $a non posée"
done
if ip route show default | grep -q .; then
    echo "  !! Une route par défaut existe :"; ip route show default | sed 's/^/     /'
    echo "     (elle doit venir de eth1/maintenance ou être absente — PAS du segment caméras)"
else
    echo "  Aucune route par défaut — OK pour un boîtier autonome"
fi
echo
echo "Vérifier ensuite : scripts/harden-run.sh (section « Segment caméras »)."
