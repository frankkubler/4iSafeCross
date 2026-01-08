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
    libgirepository1.0-dev \
    python3-dev \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1-mesa-glx \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Installation de uv pour gestion des dependances
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Installation de Cython
RUN pip install --no-cache-dir cython setuptools wheel

# Copie des fichiers de dependances
COPY pyproject.toml uv.lock ./

# Installation des dependances Python
RUN uv sync --frozen --no-dev

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
    # Nettoyer les fichiers de build intermediaires
    rm -rf build/ *.c src/**/*.c utils/**/*.c

# Stage final - Image NVIDIA JetPack minimale avec GStreamer
FROM nvcr.io/nvidia/l4t-jetpack:r36.4.0

WORKDIR /app

# Copie uniquement le necessaire depuis builder
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app/.venv /app/.venv

# Installation runtime minimal avec GStreamer + plugins NVIDIA
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    libglib2.0-0 \
    libgirepository-1.0-1 \
    libcairo2 \
    gir1.2-gstreamer-1.0 \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-libav \
    nvidia-l4t-gstreamer \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1-mesa-glx \
    libgomp1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libavcodec58 \
    libavformat58 \
    libswscale5 \
    libtbb2 \
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
