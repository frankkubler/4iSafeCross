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

- Émulation ARM64 via QEMU (`tonistiigi/binfmt`, l'installeur binfmt officiel de buildx)
- Build multi-stage : `nvcr.io/nvidia/cuda:13.2.1-devel-ubuntu24.04` (builder) → `nvcr.io/nvidia/cuda:13.2.1-runtime-ubuntu24.04` (image finale) — JetPack 7.2 / L4T r39.2.0 (plus d'image `l4t-jetpack` pour JetPack 7)
- Plugins GStreamer NVIDIA (`nvv4l2decoder`, `nvvidconv`) installés via `nvidia-l4t-gstreamer` depuis le dépôt apt Jetson r39.2 (`common` + `som`)
- Compilation Cython avec `-OO` → tous les `.py` deviennent des `.so`
- Push des tags `:<sha>` et `:latest` dans le registry GitLab

### Stage 3 : release

- Uniquement pour les tags (`v*.*.*`)
- Crée une release GitLab avec les instructions de déploiement Docker

## Déclenchement

| Événement | `sast` | `gitleaks` | build images | release |
|-----------|--------|------------|--------------|---------|
| Push sur `main` | ✅ | ✅ | ▶ manuel | — |
| Push sur une autre branche | — | — | ▶ manuel | — |
| Tag `v*.*.*` | — | ✅ | ✅ | ✅ |
| Merge request | ✅ | ✅ | — | — |

**Une image n'est construite automatiquement que sur un tag.** C'est la seule
livraison, et un build ARM64 sous QEMU est long — les deux jobs partagent le daemon
Docker de l'hôte (`resource_group: docker-host`) et ne peuvent pas tourner en parallèle.
Un push sur `main` déclenche donc les contrôles de sécurité, mais pas de build.

Pour construire sans taguer (mise au point, image de test) : ouvrir le pipeline dans
**CI/CD → Pipelines**, puis cliquer ▶ sur `build:docker:arm64` ou `build:docker:amd64`.
Le job produit `<sha-court>-<arch>` et, sur `main`, met aussi à jour `latest-<arch>`.

> ⚠️ **`latest-arm64` / `latest-amd64` ne suivent plus chaque push sur `main`** : ils ne
> bougent qu'à un tag ou à un build lancé manuellement. Un déploiement qui pointerait
> `latest-*` peut donc rester sur une image ancienne sans que rien ne le signale — raison
> de plus pour déployer un tag de version en production (§ 3.1 d'install-prod).

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

Tous les tags portent le suffixe d'architecture — il n'existe pas d'index multi-arch :

```
registry.gitlab.4itec.ddns.net/frank-k/4isafecross:<sha-court>-arm64   # toute exécution
registry.gitlab.4itec.ddns.net/frank-k/4isafecross:latest-arm64        # main et tags Git
registry.gitlab.4itec.ddns.net/frank-k/4isafecross:<tag-git>-arm64     # tags Git seulement
```

(idem en `-amd64`.) Un tag Git est donc **la seule façon d'obtenir une image de version
figée** : sans lui, le registre ne contient que des SHA, `latest-*` et des tags de branche.

L'image contient :
- Les binaires Cython `.so` (code source supprimé)
- Le runtime Python 3.12 (Ubuntu 24.04) + dépendances GStreamer/NVIDIA
- `run.py` comme point d'entrée (non compilé, importe `app` depuis le `.so`)

### Nettoyage automatique du registre

Une politique d'expiration tourne quotidiennement (`keep_n: 10`, `older_than: 90d`,
`name_regex: .*`). Les tags de version et `latest*` en sont **exclus** via
`name_regex_keep` :

```
([vV]\d+\.\d+\.\d+.*|latest.*)
```

Les tags SHA et les tags de branche restent, eux, nettoyables. Ne pas retirer cette
exclusion : une image de production doit rester récupérable au-delà de 90 jours
(rollback, preuve d'identité de version `CS-1141-01`).

## Déploiement sur le Jetson

```bash
# Connexion au registry
docker login registry.gitlab.4itec.ddns.net -u frank-k

# Télécharger l'image
docker pull registry.gitlab.4itec.ddns.net/frank-k/4isafecross:v3.0.0-arm64

# Lancer le conteneur
docker run -d \
  --name 4isafecross \
  --runtime nvidia \
  --restart unless-stopped \
  --privileged \
  -p 5000:5000 \
  -v /data/4isafecross:/app/data \
  registry.gitlab.4itec.ddns.net/frank-k/4isafecross:v3.0.0-arm64
```

Ou via le script automatisé :

```bash
bash scripts/deploy-jetson.sh latest-arm64
bash scripts/deploy-jetson.sh v3.0.0-arm64
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

Le pipeline nettoie automatiquement en `after_script` : `docker buildx prune --keep-storage 10GB` (cache de build borné) et `docker image prune -f` (images sans tag).

Si cela ne suffit pas, sur le serveur Runner :

```bash
docker buildx prune -af          # tout le cache de build (builds suivants plus lents)
docker image prune -a --filter "until=168h"
```

> ⚠️ **Ne jamais lancer `docker system prune -af --volumes` pendant qu'un pipeline tourne.**
> Le Runner utilise le daemon Docker de l'hôte (socket monté), partagé par tous les jobs :
> la garbage collection de containerd supprime les blobs en cours de téléchargement des
> autres jobs, qui échouent alors sur `failed to Lchown ... no such file or directory` ou
> `failed commit on ref ... no such file or directory`. `--volumes` supprime en plus les
> volumes des autres services de l'hôte.

### Jobs de build sérialisés

`build:docker:arm64` et `build:docker:amd64` partagent le `resource_group: docker-host` :
ils ne tournent jamais en parallèle, pour la même raison (daemon Docker unique et partagé).
Le pipeline complet dure donc la somme des deux builds.

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

## Publier une version

La version du projet est déclarée **au seul endroit** `pyproject.toml` (`[project] version`) :

```bash
sed -i '3s|^version = ".*"|version = "X.Y.Z"|' pyproject.toml
git add pyproject.toml && git commit -m "chore(release): vX.Y.Z"
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push gitlab-https main vX.Y.Z      # le tag déclenche le build des images
```

Rien à modifier dans `config/config.ini` : l'application lit la version dans
`pyproject.toml` en exécution depuis les sources, et dans la variable d'environnement
`APP_VERSION` en conteneur — gravée au build par la CI avec le tag Git.

## Checklist avant push

- [ ] Version portée dans `pyproject.toml` si c'est une livraison
- [ ] Runner actif avec tag `docker` et `privileged = true`
- [ ] Tous les fichiers source commités
- [ ] `pyproject.toml` / `uv.lock` à jour
- [ ] Dockerfile valide localement
