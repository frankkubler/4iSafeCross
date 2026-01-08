# Multi-stage build pour image Docker ARM64 optimisee
# Base image Jetson compatible
FROM nvcr.io/nvidia/l4t-pytorch:r36.2.0-pth2.1-py3 AS base

WORKDIR /app

# Installation des dependances systeme
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3-pip \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1-mesa-glx \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Installation de uv pour gestion des dependances
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Copie des fichiers de dependances
COPY pyproject.toml uv.lock ./

# Installation des dependances Python
RUN uv sync --frozen --no-dev

# Stage final - Image minimale
FROM nvcr.io/nvidia/l4t-base:r36.2.0

WORKDIR /app

# Copie uniquement le necessaire depuis base
COPY --from=base /root/.local /root/.local
COPY --from=base /app/.venv /app/.venv

# Installation runtime minimal
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copie du code application
COPY config/ ./config/
COPY templates/ ./templates/
COPY static/ ./static/
COPY db/ ./db/
COPY src/ ./src/
COPY utils/ ./utils/
COPY app.py .

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
