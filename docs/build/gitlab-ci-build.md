# Pipeline GitLab CI/CD — Image Docker ARM64

Ce document décrit le pipeline `.gitlab-ci.yml` utilisé pour compiler et publier l'image Docker ARM64 de 4iSafeCross sur le Jetson Orin NX.

## Architecture du pipeline

```
┌──────────────┐      ┌──────────────────────┐      ┌─────────────────┐
│   security   │  →   │    build:docker:arm64 │  →   │    release      │
│ SAST + audit │      │  Cython + Docker push │      │  (tags only)    │
└──────────────┘      └──────────────────────┘      └─────────────────┘
```

### Stage 1 : security

- **Bandit** : analyse statique SAST sur `src/`, `utils/`, `app.py`
- **pip-audit** : audit des CVE dans les dépendances Python
- Les rapports JSON sont publiés en artefacts (30 jours)
- `allow_failure: true` — n'interrompt pas le build (mode progressif)

### Stage 2 : build:docker:arm64

- Émulation ARM64 via QEMU (`multiarch/qemu-user-static`)
- Build multi-stage : `nvcr.io/nvidia/cuda:13.2.1-devel-ubuntu24.04` (builder) → `nvcr.io/nvidia/cuda:13.2.1-runtime-ubuntu24.04` (image finale) — JetPack 7.2 / L4T r39.2.0 (plus d'image `l4t-jetpack` pour JetPack 7)
- Plugins GStreamer NVIDIA (`nvv4l2decoder`, `nvvidconv`) installés via `nvidia-l4t-gstreamer` depuis le dépôt apt Jetson r39.2 (`common` + `som`)
- Compilation Cython avec `-OO` → tous les `.py` deviennent des `.so`
- Push des tags `:<sha>` et `:latest` dans le registry GitLab

### Stage 3 : release

- Uniquement pour les tags (`v*.*.*`)
- Crée une release GitLab avec les instructions de déploiement Docker

## Déclenchement

| Événement | security | build | release |
|-----------|----------|-------|---------|
| Push sur `main` | ✅ | ✅ | — |
| Push sur `jetson_gpu` | — | ✅ | — |
| Tag `v*.*.*` | — | ✅ | ✅ |
| Merge Request | ✅ | — | — |

## Prérequis Runner

Le Runner GitLab doit être configuré avec :

```toml
[[runners]]
  executor = "docker"
  [runners.docker]
    privileged = true
    volumes = ["/cache", "/var/run/docker.sock:/var/run/docker.sock"]
```

Les tags `docker` sont requis. Vérifier dans **Settings > CI/CD > Runners**.

## Variables CI/CD à configurer

Dans **Settings > CI/CD > Variables** :

| Variable | Source | Usage |
|----------|--------|-------|
| `CI_REGISTRY_USER` | Auto (GitLab) | Login registry |
| `CI_REGISTRY_PASSWORD` | Auto (GitLab) | Login registry |
| `CI_REGISTRY_IMAGE` | Auto (GitLab) | Nom de l'image |

Aucune variable manuelle n'est requise — GitLab injecte automatiquement les credentials du registry intégré.

## Image produite

```
registry.gitlab.4itec.ddns.net/frank-k/4isafecross:<sha>
registry.gitlab.4itec.ddns.net/frank-k/4isafecross:latest
```

L'image contient :
- Les binaires Cython `.so` (code source supprimé)
- Le runtime Python 3.12 (Ubuntu 24.04) + dépendances GStreamer/NVIDIA
- `run.py` comme point d'entrée (non compilé, importe `app` depuis le `.so`)

## Déploiement sur le Jetson

```bash
# Connexion au registry
docker login registry.gitlab.4itec.ddns.net -u frank-k

# Télécharger l'image
docker pull registry.gitlab.4itec.ddns.net/frank-k/4isafecross:latest

# Lancer le conteneur
docker run -d \
  --name 4isafecross \
  --runtime nvidia \
  --restart unless-stopped \
  --privileged \
  -p 5000:5000 \
  -v /data/4isafecross:/app/data \
  registry.gitlab.4itec.ddns.net/frank-k/4isafecross:latest
```

Ou via le script automatisé :

```bash
bash scripts/deploy-jetson.sh latest
bash scripts/deploy-jetson.sh v1.2.0
```

## Dépannage

### Runner offline

```bash
sudo gitlab-runner status
sudo gitlab-runner start
```

Vérifier le tag `docker` dans **Settings > CI/CD > Runners**.

### Timeout du job

Augmenter dans **Settings > CI/CD > General pipelines** (60 min recommandé).
Le build Docker ARM64 avec QEMU prend ~15–25 min.

### Espace disque insuffisant

```bash
# Sur le serveur Runner
docker system prune -af --volumes
```

Le pipeline nettoie automatiquement via `docker system prune -f` en `after_script`.

### Logs du pipeline

```bash
# Sur le serveur Runner
sudo journalctl -u gitlab-runner -f
```

Ou dans l'interface : **CI/CD > Pipelines > job échoué > logs**.

## Désactiver le pipeline pour un commit

```bash
git commit -m "chore: mise à jour doc [skip ci]"
```

## Checklist avant push

- [ ] Runner actif avec tag `docker` et `privileged = true`
- [ ] Tous les fichiers source commités
- [ ] `pyproject.toml` / `uv.lock` à jour
- [ ] Dockerfile valide localement
