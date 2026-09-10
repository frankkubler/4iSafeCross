#!/bin/bash
# Deploiement de 4iSafeCross sur la Jetson cible — PILOTE docker compose.
#
# La reference de production est docker-compose-arm64.yml : ce script ne lance
# plus de « docker run » avec ses propres options (qui divergeaient du compose :
# /dev entier, pas de ipc: host, pas d'argus/enctune, pas de rotation des logs).
# Il enchaine ce qu'un operateur ferait a la main, sans rien oublier :
#   login registry (jeton sur stdin) -> pull -> amorcage de /data -> controles
#   .env -> docker compose up -d -> attente du healthcheck -> logout.
#
# Usage :
#   ./scripts/deploy-jetson.sh v3.0.1-arm64     # version figee — mode nominal
#   TAG=v3.0.1-arm64 ./scripts/deploy-jetson.sh # equivalent
#   ./scripts/deploy-jetson.sh                  # latest-arm64 (mise au point)
# Le suffixe -arm64 est ajoute s'il manque (la CI publie <tag>-arm64).
#
# Mode hors ligne (boitier livre, sans acces Internet — cas nominal en RUN) :
#   OFFLINE=1 ./scripts/deploy-jetson.sh v3.0.1-arm64
# L'image doit avoir ete chargee depuis le support amovible :
#   sudo docker load -i <support>/4isafecross_v3.0.1-arm64.tar
# Aucun contact avec le registry n'est alors tente (install-prod § 3.3).
#
# Convention (install-prod-jetson-docker.md § 3.2) : le deploy token est lu sur
# stdin — jamais en argument ni en variable d'environnement (historique shell,
# /proc/<pid>/environ) — et la session registry est refermee en sortant, meme
# en cas d'erreur : ~/.docker/config.json stocke le jeton en base64, pas chiffre,
# et un boitier livre ne doit conserver aucun acces au registry (CS-127-01/02).
# Le digest de l'image deployee est releve : c'est lui qui identifie la version
# en production (CS-1141-01), pas le tag.

set -euo pipefail

REGISTRY="${PACKAGE_REGISTRY_HOST:-registry.gitlab.4itec.ddns.net}"
IMAGE_NAME="frank-k/4isafecross"
CONTAINER_NAME="4isafecross"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose-arm64.yml}"
DATA_DIR="/data/4isafecross"
TAG="${1:-${TAG:-latest-arm64}}"
OFFLINE="${OFFLINE:-0}"

# Le script fonctionne depuis scripts/ ou pose a cote du compose.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR=""
for d in "${SCRIPT_DIR}/.." "${SCRIPT_DIR}" "${PWD}"; do
    if [ -f "${d}/${COMPOSE_FILE}" ]; then PROJECT_DIR="$(cd "${d}" && pwd)"; break; fi
done
if [ -z "${PROJECT_DIR}" ]; then
    echo "[X] ${COMPOSE_FILE} introuvable (cherche dans ${SCRIPT_DIR}/.., ${SCRIPT_DIR}, ${PWD})."
    exit 1
fi
cd "${PROJECT_DIR}"

# La CI publie <tag>-arm64 / <tag>-amd64 : completer si l'operateur a tape « v3.0.1 ».
case "${TAG}" in
    *-arm64|*-amd64) ;;
    *) TAG="${TAG}-arm64"; echo "[i] Suffixe d'architecture ajoute : ${TAG}" ;;
esac

# Le compte joint-il le daemon ? Les identifiants du registry sont stockes par
# utilisateur (~/.docker vs /root/.docker) : melanger « sudo docker login » et
# « docker compose pull » ferait echouer le pull sur un refus d'authentification.
if docker info >/dev/null 2>&1; then DOCKER="docker"; else DOCKER="sudo docker"; echo "[i] Acces au daemon via sudo."; fi

FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "==========================================="
echo "Deploiement 4iSafeCross sur Jetson"
echo "==========================================="
echo "Image   : ${FULL_IMAGE}"
echo "Compose : ${PROJECT_DIR}/${COMPOSE_FILE}"
echo ""

case "${TAG}" in
    latest-*)
        echo "[!] « ${TAG} » est un tag mouvant : il ne dit pas quelle version tourne."
        echo "    En production, deployer un tag de version fige (v3.0.1-arm64) — CS-1141-01."
        echo "    Le digest releve en fin de script identifie ce qui tourne reellement."
        echo ""
        ;;
esac

if ! ${DOCKER} info 2>/dev/null | grep -q nvidia; then
    echo "[!] Runtime NVIDIA non detecte : le conteneur demarrera sans GPU."
    echo "    sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"
fi

# ─── .env : obligatoire (compose : env_file) et porteur de l'authentification IHM ───
if [ ! -f .env ]; then
    echo "[X] ${PROJECT_DIR}/.env introuvable."
    echo "    Le creer depuis .env.example et renseigner au minimum"
    echo "    SAFECROSS_AUTH_USER et SAFECROSS_AUTH_PASSWORD (CS-1144-01)."
    exit 1
fi
if ! grep -qE '^SAFECROSS_AUTH_USER=.+' .env || ! grep -qE '^SAFECROSS_AUTH_PASSWORD=.+' .env; then
    echo "[X] SAFECROSS_AUTH_USER / SAFECROSS_AUTH_PASSWORD non renseignes dans .env."
    echo "    L'application refuse de demarrer sans authentification (CS-1144-01)."
    exit 1
fi

# Le tag deploye est ecrit dans .env, que docker compose lit tout seul : toute
# commande compose ulterieure (run, logs, up) vise la meme image. Sans cela, un
# « docker compose run » lance a la main retomberait sur le defaut du fichier
# compose — une autre image, eventuellement perimee et jamais re-tiree.
write_env() { if [ -w .env ]; then sed -i "$1" .env; else sudo sed -i "$1" .env; fi; }
if grep -q '^SAFECROSS_TAG=' .env; then
    write_env "s|^SAFECROSS_TAG=.*|SAFECROSS_TAG=${TAG}|"
else
    if [ -w .env ]; then echo "SAFECROSS_TAG=${TAG}" >> .env; else echo "SAFECROSS_TAG=${TAG}" | sudo tee -a .env >/dev/null; fi
fi
export SAFECROSS_TAG="${TAG}"
echo "[i] .env : SAFECROSS_TAG=${TAG}"

# ─── Conteneur herite d'un ancien « docker run » ───────────────────────────
# Un conteneur du meme nom cree hors compose bloquerait « compose up » (nom
# deja pris) : on le retire, compose recree le sien avec les bonnes options.
if ${DOCKER} inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    if [ -z "$(${DOCKER} inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "${CONTAINER_NAME}")" ]; then
        echo "[i] Conteneur « ${CONTAINER_NAME} » cree par docker run (hors compose) : suppression."
        ${DOCKER} rm -f "${CONTAINER_NAME}" >/dev/null
    fi
fi

# ─── Image ─────────────────────────────────────────────────────────────────
LOGGED_IN=0
registry_logout() {
    if [ "${LOGGED_IN}" = "1" ]; then
        ${DOCKER} logout "${REGISTRY}" >/dev/null 2>&1 || true
        echo "[i] Deconnecte du registry (aucun jeton conserve sur la machine)."
    fi
}
trap registry_logout EXIT

if [ "${OFFLINE}" = "1" ]; then
    echo "[i] Mode hors ligne : aucune interaction avec le registry."
    if ! ${DOCKER} image inspect "${FULL_IMAGE}" >/dev/null 2>&1; then
        echo "[X] Image absente localement : ${FULL_IMAGE}"
        echo "    sha256sum -c <support>/4isafecross_${TAG}.tar.sha256"
        echo "    sudo docker load -i <support>/4isafecross_${TAG}.tar"
        exit 1
    fi
else
    if [ -z "${REGISTRY_USERNAME:-}" ]; then
        read -rp "Nom du deploy token (portee read_registry) : " REGISTRY_USERNAME
    fi
    read -rsp "Deploy token : " GL_TOKEN; echo
    printf '%s' "${GL_TOKEN}" | ${DOCKER} login "${REGISTRY}" -u "${REGISTRY_USERNAME}" --password-stdin
    unset GL_TOKEN
    LOGGED_IN=1
    echo "[i] Telechargement de l'image..."
    ${DOCKER} compose -f "${COMPOSE_FILE}" pull
fi

# ─── Etat persistant ──────────────────────────────────────────────────────
# config/ et db/ sont des bind-mounts : un repertoire hote vide masquerait le
# contenu de l'image et l'application ne demarrerait pas. Amorcage au premier
# deploiement seulement — JAMAIS de reecriture ensuite, ce serait effacer la
# geometrie des zones du site et l'historique des relais.
sudo mkdir -p "${DATA_DIR}/config" "${DATA_DIR}/db" "${DATA_DIR}/detections" "${DATA_DIR}/dataset" "${DATA_DIR}/logs"
if [ -z "$(ls -A "${DATA_DIR}/config" 2>/dev/null)" ]; then
    echo "[i] Premier deploiement : amorcage de config/ et db/ depuis l'image..."
    # --runtime runc : « tar » n'a pas besoin du GPU, et cela evite le hook cudacompat
    # sur une image ancienne qui contiendrait encore /usr/local/cuda/compat_orin.
    ${DOCKER} run --rm --runtime runc --entrypoint tar "${FULL_IMAGE}" -C /app -c config db \
        | sudo tar -C "${DATA_DIR}" -x
    echo "[!] Renseigner ${DATA_DIR}/config/config.ini (adresses RTSP, zones) avant exploitation."
else
    echo "[i] ${DATA_DIR}/config deja amorce — conserve tel quel."
fi
if [ -z "$(ls -A licenses 2>/dev/null)" ]; then
    echo "[!] ${PROJECT_DIR}/licenses est vide : sans fichier de licence, l'application ne demarrera pas."
fi

# ─── Deploiement ──────────────────────────────────────────────────────────
echo "[i] docker compose up -d..."
${DOCKER} compose -f "${COMPOSE_FILE}" up -d

# ─── Verification ─────────────────────────────────────────────────────────
echo "[i] Attente du healthcheck (jusqu'a 120 s)..."
status="absent"
for _ in $(seq 1 24); do
    status=$(${DOCKER} inspect -f '{{.State.Health.Status}}' "${CONTAINER_NAME}" 2>/dev/null || echo "absent")
    [ "${status}" = "healthy" ] && break
    [ "${status}" = "absent" ] && break
    sleep 5
done

echo ""
${DOCKER} compose -f "${COMPOSE_FILE}" ps
echo ""
echo "[i] Version deployee (a consigner) :"
${DOCKER} image inspect --format '{{index .RepoDigests 0}}' "${FULL_IMAGE}" 2>/dev/null \
    || echo "    digest indisponible (image chargee hors registry ?)"
echo ""
if [ "${status}" = "healthy" ]; then
    echo "[OK] Service sain — IHM : https://<hote> via Caddy ; API locale : curl http://localhost:5050/health"
    # Couches des anciennes images devenues orphelines apres le changement de tag.
    ${DOCKER} image prune -f >/dev/null || true
else
    echo "[X] Service non sain (etat : ${status}). Journaux :"
    ${DOCKER} compose -f "${COMPOSE_FILE}" logs --tail 60
    exit 1
fi
