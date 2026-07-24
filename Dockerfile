# Multi-stage build - ARM64 (Jetson Orin NX) + AMD64 (Intel/x86_64)


# ═══════════════════════════════════════════════════════════════════
# BUILDER AMD64
# ═══════════════════════════════════════════════════════════════════
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:0.11.16 AS uv-binary-amd64


FROM --platform=linux/amd64 ubuntu:24.04 AS builder-amd64


WORKDIR /app


ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-dev \
    python3-pip \
    build-essential \
    gcc \
    g++ \
    cmake \
    ninja-build \
    pkg-config \
    libglib2.0-0 \
    libglib2.0-dev \
    libgirepository-1.0-dev \
    gobject-introspection \
    gir1.2-gstreamer-1.0 \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libcairo2-dev \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*


COPY --from=uv-binary-amd64 /uv /root/.local/bin/uv
ENV PATH="/root/.local/bin:$PATH"

ARG UV_INDEX_USERNAME
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=uv_index_token \
    TOKEN="$(cat /run/secrets/uv_index_token)" && \
    printf '[[index]]\nname = "gitlab-license-validator"\nurl = "https://%s:%s@gitlab.4itec.ddns.net/api/v4/projects/38/packages/pypi/simple"\nexplicit = true\n' "${UV_INDEX_USERNAME}" "$TOKEN" > uv.toml && \
    uv sync --frozen --no-dev --python 3.12 && \
    uv pip install --python /app/.venv/bin/python "cython==3.2.8" setuptools wheel && \
    rm -f uv.toml

COPY config/ ./config/
COPY templates/ ./templates/
COPY static/ ./static/
COPY db/ ./db/
COPY src/ ./src/
COPY utils/ ./utils/
COPY run.py .
COPY setup_cython.py .


ENV TARGET_ARCH=amd64


RUN /app/.venv/bin/python setup_cython.py build_ext --inplace && \
    find src/ -name "*.py" ! -name "constants.py" -type f -delete && \
    find utils/ -name "*.py" ! -name "constants.py" -type f -delete && \
    rm -rf build/ *.c src/**/*.c utils/**/*.c


# ═══════════════════════════════════════════════════════════════════
# BUILDER ARM64 (Jetson Orin NX - JetPack 7.2 / L4T r39.2.0)
# Pas d'image l4t-jetpack pour JetPack 7 : NVIDIA unifie sur les
# images CUDA SBSA multi-arch (Ubuntu 24.04, CUDA 13.2)
# ═══════════════════════════════════════════════════════════════════
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:0.11.16 AS uv-binary-arm64


FROM --platform=linux/arm64 nvcr.io/nvidia/cuda:13.2.1-devel-ubuntu24.04 AS builder-arm64


WORKDIR /app


ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-dev \
    python3-pip \
    build-essential \
    gcc \
    g++ \
    cmake \
    ninja-build \
    pkg-config \
    libglib2.0-0 \
    libglib2.0-dev \
    libgirepository-1.0-dev \
    gobject-introspection \
    gir1.2-gstreamer-1.0 \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libcairo2-dev \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*


COPY --from=uv-binary-arm64 /uv /root/.local/bin/uv
ENV PATH="/root/.local/bin:$PATH"

ARG UV_INDEX_USERNAME
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=uv_index_token \
    TOKEN="$(cat /run/secrets/uv_index_token)" && \
    printf '[[index]]\nname = "gitlab-license-validator"\nurl = "https://%s:%s@gitlab.4itec.ddns.net/api/v4/projects/38/packages/pypi/simple"\nexplicit = true\n' "${UV_INDEX_USERNAME}" "$TOKEN" > uv.toml && \
    uv sync --frozen --no-dev --python 3.12 && \
    uv pip install --python /app/.venv/bin/python "cython==3.2.8" setuptools wheel && \
    rm -f uv.toml

COPY config/ ./config/
COPY templates/ ./templates/
COPY static/ ./static/
COPY db/ ./db/
COPY src/ ./src/
COPY utils/ ./utils/
COPY run.py .
COPY setup_cython.py .


ENV TARGET_ARCH=arm64


# Le build ARM64 tourne sous QEMU (binfmt) en CI : gcc et son linker y
# segfaultent aleatoirement, sur un module au hasard et sans rapport avec le
# code compile ("command '/usr/bin/aarch64-linux-gnu-gcc' failed with exit
# code -11"). build_ext saute les extensions dont le .so est deja a jour :
# relancer l'etape reprend donc la ou elle s'est arretee, au lieu de perdre
# les ~20 min de compilation deja faites. Avant chaque reprise, les .so ecrits
# au moment du crash sont supprimes : tronques, ils paraitraient a jour.
RUN attempt=1; max=5; \
    until /app/.venv/bin/python setup_cython.py build_ext --inplace; do \
        attempt=$((attempt + 1)); \
        if [ "$attempt" -gt "$max" ]; then \
            echo ">>> Compilation Cython en echec apres $max tentatives" >&2; \
            exit 1; \
        fi; \
        find src/ utils/ -name "*.so" -newermt '-120 seconds' -delete; \
        echo ">>> Crash gcc sous QEMU - reprise, tentative $attempt/$max"; \
        sleep 5; \
    done && \
    find src/ -name "*.py" ! -name "constants.py" -type f -delete && \
    find utils/ -name "*.py" ! -name "constants.py" -type f -delete && \
    rm -rf build/ *.c src/**/*.c utils/**/*.c


# ═══════════════════════════════════════════════════════════════════
# STAGE FINAL AMD64 (Intel iGPU - VA-API)
# ═══════════════════════════════════════════════════════════════════
FROM ubuntu:24.04 AS final-amd64


WORKDIR /app


ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    libglib2.0-0t64 \
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
    libgtk-3-0t64 \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libtbb-dev \
    libatlas-base-dev \
    libhdf5-dev \
    libva2 \
    libva-drm2 \
    libva-x11-2 \
    intel-media-va-driver-non-free \
    i965-va-driver \
    vainfo \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean


COPY --from=builder-amd64 /root/.local /root/.local
COPY --from=builder-amd64 /app/.venv /app/.venv
COPY --from=builder-amd64 /app/config/ ./config/
COPY --from=builder-amd64 /app/templates/ ./templates/
COPY --from=builder-amd64 /app/static/ ./static/
COPY --from=builder-amd64 /app/db/ ./db/
COPY --from=builder-amd64 /app/src/ ./src/
COPY --from=builder-amd64 /app/utils/ ./utils/
COPY --from=builder-amd64 /app/run.py .


RUN mkdir -p /app/logs /app/data


ENV PATH="/root/.local/bin:/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app


EXPOSE 5050


HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD /app/.venv/bin/python -c "import requests; requests.get('http://localhost:5050/health')" || exit 1

CMD ["/app/.venv/bin/python", "run.py"]


# ═══════════════════════════════════════════════════════════════════
# STAGE FINAL ARM64 (Jetson Orin NX - JetPack 7.2 / L4T r39.2.0)
# Base CUDA 13.2 Ubuntu 24.04 ; les plugins GStreamer NVIDIA
# (nvv4l2decoder, nvvidconv) viennent du dépôt apt Jetson r39.2
# ═══════════════════════════════════════════════════════════════════
FROM nvcr.io/nvidia/cuda:13.2.1-runtime-ubuntu24.04 AS final-arm64


WORKDIR /app


ENV DEBIAN_FRONTEND=noninteractive


COPY --from=builder-arm64 /root/.local /root/.local
COPY --from=builder-arm64 /app/.venv /app/.venv


RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    libglib2.0-0t64 \
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
    libgtk-3-0t64 \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libtbb-dev \
    libatlas-base-dev \
    libhdf5-dev \
    iputils-ping \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean


# Plugins GStreamer NVIDIA (nvv4l2decoder, nvvidconv) depuis le dépôt L4T r39.2
# (common + som). Le fichier .nv-l4t-disable-boot-fw-update-in-preinstall permet
# d'installer les paquets BSP hors du Jetson (le preinst saute la détection de
# plateforme et la vérification rootfs A/B).
RUN curl -fsSL https://repo.download.nvidia.com/jetson/jetson-ota-public.asc \
    -o /etc/apt/trusted.gpg.d/jetson-ota-public.asc \
    && printf 'deb https://repo.download.nvidia.com/jetson/common r39.2 main\ndeb https://repo.download.nvidia.com/jetson/som r39.2 main\n' \
    > /etc/apt/sources.list.d/nvidia-l4t.list \
    && mkdir -p /opt/nvidia/l4t-packages \
    && touch /opt/nvidia/l4t-packages/.nv-l4t-disable-boot-fw-update-in-preinstall \
    && apt-get update && apt-get install -y --no-install-recommends \
    nvidia-l4t-gstreamer \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean


COPY --from=builder-arm64 /app/config/ ./config/
COPY --from=builder-arm64 /app/templates/ ./templates/
COPY --from=builder-arm64 /app/static/ ./static/
COPY --from=builder-arm64 /app/db/ ./db/
COPY --from=builder-arm64 /app/src/ ./src/
COPY --from=builder-arm64 /app/utils/ ./utils/
COPY --from=builder-arm64 /app/run.py .


RUN mkdir -p /app/logs /app/data


ENV PATH="/root/.local/bin:/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app
# Nécessaire pour que le runtime nvidia monte les libs vidéo (nvv4l2, NVENC/NVDEC)
ENV NVIDIA_DRIVER_CAPABILITIES=all


EXPOSE 5050


HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD /app/.venv/bin/python -c "import requests; requests.get('http://localhost:5050/health')" || exit 1

CMD ["/app/.venv/bin/python", "run.py"]