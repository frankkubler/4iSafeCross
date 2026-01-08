#!/bin/bash
# Script de deploiement automatique pour Jetson Orin NX
# Usage: ./deploy.sh [tag]
# Exemple: ./deploy.sh latest
#          ./deploy.sh v1.0.0

set -e

# Configuration
REGISTRY="gitlab.4itec.ddns.net"
IMAGE_NAME="frank-k/4isafecross"
CONTAINER_NAME="4isafecross"
TAG="${1:-latest}"
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
docker pull ${FULL_IMAGE}

# Lancer le nouveau conteneur
echo "🚀 Lancement du conteneur..."
docker run -d \
  --name ${CONTAINER_NAME} \
  --runtime nvidia \
  --restart unless-stopped \
  --privileged \
  -p 5000:5000 \
  -v /data/4isafecross:/app/data \
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
    echo "   curl http://localhost:5000/health"
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
