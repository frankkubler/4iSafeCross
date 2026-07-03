# Multi-stage build - ARM64 (Jetson Orin NX) + AMD64 (Intel/x86_64)

# ═══════════════════════════════════════════════════════════════════
# BUILDER AMD64
# ═══════════════════════════════════════════════════════════════════
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:0.11.16 AS uv-binary-amd64

FROM ubuntu:22.04 AS builder-amd64

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

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
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1-mesa-glx \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv copié depuis l'image officielle Astral (plus de téléchargement réseau manuel)
COPY --from=uv-binary-amd64 /uv /root/.local/bin/uv
ENV PATH="/root/.local/bin:$PATH"

RUN python3.10 -m pip install --no-cache-dir cython setuptools wheel

ARG UV_INDEX_USERNAME
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=uv_index_token \
    TOKEN="$(cat /run/secrets/uv_index_token)" && \
    printf '[[index]]\nname = "gitlab-license-validator"\nurl = "https://%s:%s@gitlab.4itec.ddns.net/api/v4/projects/38/packages/pypi/simple"\nexplicit = true\n' "${UV_INDEX_USERNAME}" "$TOKEN" > uv.toml && \
    uv sync --frozen --no-dev && \
    rm -f uv.toml

COPY config/ ./config/
COPY templates/ ./templates/
COPY static/ ./static/
COPY db/ ./db/
COPY src/ ./src/
COPY utils/ ./utils/
COPY app.py .
COPY setup_cython.py .

# Compilation Cython - build verbeux pour diagnostic en cas d'echec
RUN python3.10 setup_cython.py build_ext --inplace && \
    find src/ -name "*.py" -type f -delete && \
    find utils/ -name "*.py" -type f -delete && \
    rm -rf build/ *.c src/**/*.c utils/**/*.c
# ═══════════════════════════════════════════════════════════════════
# BUILDER ARM64 (Jetson Orin NX)
# ═══════════════════════════════════════════════════════════════════
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:0.11.16 AS uv-binary-arm64

FROM nvcr.io/nvidia/l4t-jetpack:r36.4.0 AS builder-arm64

WORKDIR /app

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

# uv copié depuis l'image officielle Astral (plus de téléchargement réseau manuel)
COPY --from=uv-binary-arm64 /uv /root/.local/bin/uv
ENV PATH="/root/.local/bin:$PATH"

RUN python3.10 -m pip install --no-cache-dir cython setuptools wheel

ARG UV_INDEX_USERNAME
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=uv_index_token \
    TOKEN="$(cat /run/secrets/uv_index_token)" && \
    printf '[[index]]\nname = "gitlab-license-validator"\nurl = "https://%s:%s@gitlab.4itec.ddns.net/api/v4/projects/38/packages/pypi/simple"\nexplicit = true\n' "${UV_INDEX_USERNAME}" "$TOKEN" > uv.toml && \
    uv sync --frozen --no-dev && \
    rm -f uv.toml

COPY config/ ./config/
COPY templates/ ./templates/
COPY static/ ./static/
COPY db/ ./db/
COPY src/ ./src/
COPY utils/ ./utils/
COPY app.py .
COPY run.py .
COPY setup_cython.py .

RUN python3.10 setup_cython.py build_ext --inplace && \
    find src/ -name "*.py" -type f -delete && \
    find utils/ -name "*.py" -type f -delete && \
    rm -rf build/ *.c src/**/*.c utils/**/*.c

# ═══════════════════════════════════════════════════════════════════
# STAGE FINAL AMD64 (Intel iGPU - VA-API)
# ═══════════════════════════════════════════════════════════════════
FROM ubuntu:22.04 AS final-amd64

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

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
    libgl1-mesa-glx \
    libgomp1 \
    libgtk-3-0 \
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
COPY --from=builder-amd64 /app/app.py .

RUN mkdir -p /app/logs /app/data

ENV PATH="/root/.local/bin:/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import requests; requests.get('http://localhost:5000/health')" || exit 1

CMD ["python3", "app.py"]

# ═══════════════════════════════════════════════════════════════════
# STAGE FINAL ARM64 (Jetson Orin NX - NVIDIA JetPack)
# ═══════════════════════════════════════════════════════════════════
FROM nvcr.io/nvidia/l4t-jetpack:r36.4.0 AS final-arm64

WORKDIR /app

COPY --from=builder-arm64 /root/.local /root/.local
COPY --from=builder-arm64 /app/.venv /app/.venv

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

COPY --from=builder-arm64 /app/config/ ./config/
COPY --from=builder-arm64 /app/templates/ ./templates/
COPY --from=builder-arm64 /app/static/ ./static/
COPY --from=builder-arm64 /app/db/ ./db/
COPY --from=builder-arm64 /app/src/ ./src/
COPY --from=builder-arm64 /app/utils/ ./utils/
COPY --from=builder-arm64 /app/app.py .

RUN mkdir -p /app/logs /app/data

ENV PATH="/root/.local/bin:/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import requests; requests.get('http://localhost:5000/health')" || exit 1

CMD ["python3", "app.py"]