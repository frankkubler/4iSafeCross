#!/bin/bash
# Script de deploiement automatique pour Jetson Orin NX
# Usage: ./deploy.sh [tag]
# Exemple: ./deploy.sh latest
#          ./deploy.sh v1.0.0

set -e

# Configuration
REGISTRY="registry.gitlab.4itec.ddns.net"
IMAGE_NAME="frank-k/4isafecross"
CONTAINER_NAME="4isafecross"
TAG="${1:-latest}"

# Permet la surcharge depuis l'environnement (ex: .bashrc)
REGISTRY="${PACKAGE_REGISTRY_HOST:-${REGISTRY}}"
REGISTRY_USERNAME="${REGISTRY_USERNAME:-}"
REGISTRY_TOKEN="${REGISTRY_TOKEN:-}"

FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "==================================="
echo "Deploiement 4iSafeCross sur Jetson"
echo "==================================="
echo "Image: ${FULL_IMAGE}"
echo ""

# Verifier si Docker est installe
if ! command -v docker &> /dev/null; then
    echo "❌ Docker n'est pas installe"
    exit 1
fi

# Verifier le runtime NVIDIA
if ! docker info | grep -q "nvidia"; then
    echo "⚠️  Warning: NVIDIA runtime non detecte"
    echo "Installer avec: sudo apt install nvidia-docker2"
fi

# Arreter et supprimer l'ancien conteneur si existe
if docker ps -a | grep -q ${CONTAINER_NAME}; then
    echo "🛑 Arret de l'ancien conteneur..."
    docker stop ${CONTAINER_NAME} || true
    docker rm ${CONTAINER_NAME} || true
fi

# Telecharger la nouvelle image
echo "📥 Telechargement de l'image..."
if [ -n "${REGISTRY_USERNAME}" ] && [ -n "${REGISTRY_TOKEN}" ]; then
    echo "🔐 Connexion au registry avec les variables d'environnement..."
    echo "${REGISTRY_TOKEN}" | docker login ${REGISTRY} -u "${REGISTRY_USERNAME}" --password-stdin
else
    echo "🔐 Connexion interactive au registry (variables REGISTRY_USERNAME/REGISTRY_TOKEN non definies)..."
    docker login ${REGISTRY}
fi
docker pull ${FULL_IMAGE}

# Amorcage de l'etat persistant (premier deploiement uniquement).
# config/ et db/ sont montes depuis l'hote pour survivre aux mises a jour
# d'image. Un bind mount sur un repertoire hote vide masquerait le contenu de
# l'image : on copie donc la config par defaut avant le premier demarrage.
DATA_DIR="/data/4isafecross"
echo "📂 Verification de l'etat persistant dans ${DATA_DIR}..."
sudo mkdir -p "${DATA_DIR}/config" "${DATA_DIR}/db" \
              "${DATA_DIR}/detections" "${DATA_DIR}/dataset"

if [ -z "$(ls -A "${DATA_DIR}/config" 2>/dev/null)" ]; then
    echo "   Premier deploiement : copie de la configuration par defaut..."
    docker run --rm --entrypoint tar "${FULL_IMAGE}" -C /app -c config db \
        | sudo tar -C "${DATA_DIR}" -x
    echo "   ✅ Config amorcee dans ${DATA_DIR}/config"
    echo "   ⚠️  Renseigner ${DATA_DIR}/config/config.ini (adresses RTSP) avant exploitation"
else
    echo "   ✅ Configuration existante conservee (non ecrasee)"
fi

# Lancer le nouveau conteneur
echo "🚀 Lancement du conteneur..."
docker run -d \
  --name ${CONTAINER_NAME} \
  --runtime nvidia \
  --restart unless-stopped \
  --privileged \
  -v "${DATA_DIR}/config":/app/config \
  -v "${DATA_DIR}/db":/app/db \
  -v "${DATA_DIR}/detections":/app/detections \
  -v "${DATA_DIR}/dataset":/app/dataset \
  -v "$(pwd)/licenses":/app/licenses \
  -v /etc/machine-id:/etc/machine-id:ro \
  -v /dev:/dev \
  --network host \
  -e TZ=Europe/Paris \
  ${FULL_IMAGE}

# Attendre que le conteneur demarre
echo "⏳ Demarrage..."
sleep 5

# Verifier le status
if docker ps | grep -q ${CONTAINER_NAME}; then
    echo "✅ Conteneur demarre avec succes!"
    echo ""
    echo "📊 Status:"
    docker ps | grep ${CONTAINER_NAME}
    echo ""
    echo "📝 Voir les logs:"
    echo "   docker logs -f ${CONTAINER_NAME}"
    echo ""
    echo "🔍 Tester l'API:"
    echo "   curl http://localhost:5050/failsafe_status"
else
    echo "❌ Erreur: Le conteneur n'a pas demarre"
    echo "Logs:"
    docker logs ${CONTAINER_NAME}
    exit 1
fi

# Nettoyer les anciennes images
echo ""
echo "🧹 Nettoyage des anciennes images..."
docker image prune -f

echo ""
echo "✅ Deploiement termine!"
