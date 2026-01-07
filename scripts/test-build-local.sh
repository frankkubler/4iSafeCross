#!/bin/bash
# Script de test local pour simuler la compilation GitHub Actions
# Utilise Docker pour émuler l'environnement ARM64

set -e

echo "🚀 Test local de compilation Nuitka ARM64 pour Jetson Orin NX"
echo "============================================================"

# Vérifier que Docker est installé
if ! command -v docker &> /dev/null; then
    echo "❌ Docker n'est pas installé. Veuillez l'installer d'abord."
    exit 1
fi

# Vérifier que QEMU est disponible
if ! docker run --rm --privileged multiarch/qemu-user-static --reset -p yes &> /dev/null; then
    echo "⚠️  Installation de QEMU pour l'émulation ARM64..."
    docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
fi

echo "✅ QEMU configuré pour l'émulation ARM64"

# Nettoyer les anciens conteneurs
echo "🧹 Nettoyage des anciens builds..."
rm -rf dist/

# Créer les répertoires nécessaires
mkdir -p config templates static db logs

echo "🐳 Lancement du conteneur Docker ARM64..."

# Exécuter la compilation dans un conteneur ARM64
docker run --rm \
  --platform linux/arm64 \
  -v "$(pwd)":/workspace \
  -w /workspace \
  arm64v8/ubuntu:22.04 \
  bash -c '
    set -ex
    
    echo "📦 Installation des dépendances système..."
    apt-get update -qq
    apt-get install -y -qq \
      python3.10 \
      python3.10-dev \
      python3.10-venv \
      python3-pip \
      build-essential \
      gcc \
      g++ \
      ccache \
      patchelf \
      libglib2.0-0 \
      libsm6 \
      libxrender1 \
      libxext6 \
      libgl1-mesa-glx \
      curl \
      git \
      > /dev/null 2>&1
    
    echo "🔧 Installation de uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh > /dev/null 2>&1
    export PATH="/root/.local/bin:$PATH"
    
    echo "📚 Synchronisation des dépendances Python..."
    uv sync
    
    echo "⚙️  Compilation avec Nuitka..."
    uv run nuitka \
      --standalone \
      --onefile \
      --assume-yes-for-downloads \
      --include-data-dir=config=config \
      --include-data-dir=templates=templates \
      --include-data-dir=static=static \
      --include-data-dir=db=db \
      --include-data-dir=logs=logs \
      --include-data-file=.venv/lib/python3.10/site-packages/yoctopuce/cdll/libyapi-aarch64.so=yoctopuce/cdll/libyapi-aarch64.so \
      --output-dir=dist \
      --output-filename=4isafecross \
      app.py
    
    echo "✅ Compilation terminée avec succès !"
    
    # Vérification de l'\''exécutable
    echo "📋 Informations sur l'\''exécutable généré:"
    ls -lh dist/
    
    if [ -f "dist/4isafecross" ]; then
        file dist/4isafecross
        echo "✅ Exécutable unique créé : dist/4isafecross"
    elif [ -d "dist/app.dist" ]; then
        file dist/app.dist/app
        echo "✅ Dossier de distribution créé : dist/app.dist/"
    fi
    
    # Créer une archive
    echo "📦 Création de l'\''archive..."
    cd dist
    if [ -d "app.dist" ]; then
        tar -czf 4isafecross-arm64-jetson-local.tar.gz app.dist/
        echo "✅ Archive créée : dist/4isafecross-arm64-jetson-local.tar.gz"
    elif [ -f "4isafecross" ]; then
        tar -czf 4isafecross-arm64-jetson-local.tar.gz 4isafecross
        echo "✅ Archive créée : dist/4isafecross-arm64-jetson-local.tar.gz"
    fi
  '

echo ""
echo "============================================================"
echo "✅ BUILD TERMINÉ AVEC SUCCÈS !"
echo "============================================================"
echo ""
echo "📦 Fichiers générés dans le dossier dist/"
echo ""
echo "📤 Pour transférer sur le Jetson :"
echo "   scp dist/*.tar.gz user-4itec@<jetson-ip>:/home/user-4itec/"
echo ""
echo "🚀 Pour déployer sur le Jetson :"
echo "   ssh user-4itec@<jetson-ip>"
echo "   tar -xzf 4isafecross-arm64-jetson-local.tar.gz"
echo "   cd app.dist/  # ou utilisez directement 4isafecross si --onefile"
echo "   chmod +x app  # ou ./4isafecross"
echo "   ./app"
echo ""
