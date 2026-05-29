# GitHub Actions — Référence (non utilisé)

> **Note :** Ce projet utilise GitLab CI/CD comme pipeline actif.
> Voir [`gitlab-ci-build.md`](./gitlab-ci-build.md) pour la documentation du pipeline en production.
> Ce document est conservé comme référence si une migration GitHub Actions est envisagée.

---

## Vue d'ensemble (référence)

Un workflow GitHub Actions équivalent utiliserait :
- **QEMU** pour émuler l'architecture ARM64
- **Docker Buildx** pour construire l'image ARM64
- **GitHub Container Registry (ghcr.io)** pour stocker l'image

## Fichier de configuration

`.github/workflows/build-docker-arm64.yml` (à créer si nécessaire)

```yaml
name: Build Docker ARM64

on:
  push:
    branches: [main]
  tags:
    - 'v*.*.*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push ARM64 image
        uses: docker/build-push-action@v5
        with:
          context: .
          platforms: linux/arm64
          push: true
          tags: |
            ghcr.io/${{ github.repository }}:${{ github.sha }}
            ghcr.io/${{ github.repository }}:latest
```

## Comparaison avec GitLab CI

| Critère | GitLab CI (actif) | GitHub Actions (référence) |
|---------|-------------------|---------------------------|
| **Registry** | `registry.gitlab.4itec.ddns.net` | `ghcr.io` |
| **Runners** | Auto-hébergés (illimités) | Hébergés par GitHub (limités) |
| **Credentials registry** | Injectés automatiquement | `GITHUB_TOKEN` automatique |
| **SAST intégré** | Bandit + pip-audit | Actions Marketplace |
| **Coût** | Gratuit (auto-hébergé) | 2000 min/mois gratuit |

## Ressources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [docker/build-push-action](https://github.com/docker/build-push-action)
- [setup-qemu-action](https://github.com/docker/setup-qemu-action)
