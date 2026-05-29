# Multi-stage build pour image Docker ARM64 avec Cython
# Base image NVIDIA JetPack pour compilation (registry NVIDIA officiel)
FROM nvcr.io/nvidia/l4t-jetpack:r36.4.0 AS builder

WORKDIR /app

# Installation des dependances systeme pour compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3-pip \
    build-essential \
    gcc \
    g++ \
    cmake \
    ninja-build \
    pkg-config \
    libglib2.0-0 \
    libglib2.0-dev \
    libgirepository1.0-dev \
    gobject-introspection \
    gir1.2-gstreamer-1.0 \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libcairo2-dev \
    python3-dev \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Installation de uv pour gestion des dependances (telechargement verifie par SHA256)
ARG UV_VERSION=0.11.16
RUN set -eux \
    && cd /tmp \
    && curl -LsSf \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz" \
        -o uv-aarch64-unknown-linux-gnu.tar.gz \
    && curl -LsSf \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz.sha256" \
        -o uv-aarch64-unknown-linux-gnu.tar.gz.sha256 \
    && sha256sum --check uv-aarch64-unknown-linux-gnu.tar.gz.sha256 \
    && mkdir -p /root/.local/bin \
    && tar -xzf uv-aarch64-unknown-linux-gnu.tar.gz -C /root/.local/bin --strip-components=1 \
    && rm uv-aarch64-unknown-linux-gnu.tar.gz uv-aarch64-unknown-linux-gnu.tar.gz.sha256
ENV PATH="/root/.local/bin:$PATH"

# Installation de Cython et outils de build dans Python systeme
RUN pip install --no-cache-dir cython setuptools wheel meson-python meson

# Copie des fichiers de dependances
COPY pyproject.toml uv.lock ./

# Creation du venv avec acces aux packages systeme
# (requis pour que --no-build-isolation-package trouve meson-python lors du build de pycairo)
RUN uv venv --system-site-packages --python python3.10

# Pre-installation sequentielle de pycairo avant pygobject
# uv sync construit pycairo et pygobject en parallele : pygobject demarre sa config meson
# avant que pycairo soit installe, donc py3cairo.h est introuvable -> ninja echoue.
# La pre-installation force pycairo a etre entierement compile et installe en premier.
# uv sync detecte ensuite pycairo==1.29.0 deja present et le saute.
RUN uv pip install --no-build-isolation pycairo==1.29.0

# Installation des dependances Python restantes
# pycairo est deja installe ; pygobject le trouve pour sa compilation Cairo
RUN uv sync --frozen --no-dev \
    --no-build-isolation-package pycairo \
    --no-build-isolation-package pygobject

# Copie du code source
COPY config/ ./config/
COPY templates/ ./templates/
COPY static/ ./static/
COPY db/ ./db/
COPY src/ ./src/
COPY utils/ ./utils/
COPY app.py .
COPY setup_cython.py .

# Compilation avec Cython
# Compile tous les fichiers .py en .so (binaires)
RUN python3 setup_cython.py build_ext --inplace && \
    # Nettoyer les fichiers .py originaux (garder uniquement les .so)
    find src/ -name "*.py" -type f -delete && \
    find utils/ -name "*.py" -type f -delete && \
    # Nettoyer les fichiers de build intermediaires (src/**/*.c ne fonctionne pas en sh)
    find src/ utils/ -name "*.c" -type f -delete && \
    rm -rf build/

# Stage final - Image NVIDIA JetPack minimale avec GStreamer
FROM nvcr.io/nvidia/l4t-jetpack:r36.4.0

WORKDIR /app

# Copie uniquement le necessaire depuis builder
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app/.venv /app/.venv

# Installation runtime minimal avec GStreamer + plugins NVIDIA
# Note: on ignore les erreurs pour nvidia-l4t-gstreamer car il est pre-installe dans l4t-jetpack
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    libglib2.0-0 \
    libgirepository-1.0-1 \
    libcairo2 \
    libcairo-gobject2 \
    gir1.2-gstreamer-1.0 \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-libav \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1 \
    libgomp1 \
    libgtk-3-0 \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libtbb-dev \
    libatlas-base-dev \
    libhdf5-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copie des fichiers compiles (.so) et configuration
COPY --from=builder /app/config/ ./config/
COPY --from=builder /app/templates/ ./templates/
COPY --from=builder /app/static/ ./static/
COPY --from=builder /app/db/ ./db/
COPY --from=builder /app/src/ ./src/
COPY --from=builder /app/utils/ ./utils/
COPY --from=builder /app/app.py .

# Creation des repertoires necessaires
RUN mkdir -p /app/logs /app/data

# Variables d'environnement
ENV PATH="/root/.local/bin:/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Port expose
EXPOSE 5000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import requests; requests.get('http://localhost:5000/health')" || exit 1

# Demarrage de l'application
CMD ["python3", "app.py"]
