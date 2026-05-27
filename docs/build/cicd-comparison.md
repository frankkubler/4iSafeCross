# Migration GitHub Actions ↔ GitLab CI/CD

Ce document explique les différences entre les deux systèmes CI/CD et comment passer de l'un à l'autre.

## 📊 Comparaison rapide

| Critère | GitHub Actions | GitLab CI/CD |
|---------|---------------|--------------|
| **Plateforme** | GitHub uniquement | GitLab (cloud ou auto-hébergé) |
| **Fichier de config** | `.github/workflows/*.yml` | `.gitlab-ci.yml` |
| **Runners** | Hébergés par GitHub | Auto-hébergés ou cloud |
| **Émulation ARM64** | QEMU dans Docker | QEMU dans Docker |
| **Artifacts** | Rétention 90 jours (gratuit) | Configurable |
| **Release** | GitHub Releases | GitLab Releases |
| **Coût** | Minutes limitées (gratuit) | Illimité (auto-hébergé) |

## 🔄 Structure équivalente

### GitHub Actions
```
.github/
  workflows/
    build-linux-executable.yml
```

### GitLab CI/CD
```
.gitlab-ci.yml (à la racine)
```

## 📝 Syntaxe équivalente

### Déclenchement

**GitHub Actions:**
```yaml
on:
  push:
    branches: [ main ]
  tags:
    - 'v*.*.*'
```

**GitLab CI:**
```yaml
only:
  - main
  - tags
```

### Jobs

**GitHub Actions:**
```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build
        run: echo "Building..."
```

**GitLab CI:**
```yaml
build:
  stage: build
  image: ubuntu:latest
  script:
    - echo "Building..."
```

### Artifacts

**GitHub Actions:**
```yaml
- uses: actions/upload-artifact@v4
  with:
    name: my-artifact
    path: dist/
```

**GitLab CI:**
```yaml
artifacts:
  name: my-artifact
  paths:
    - dist/
```

### Variables

**GitHub Actions:**
```yaml
env:
  MY_VAR: value
```

**GitLab CI:**
```yaml
variables:
  MY_VAR: value
```

## 🚀 Migration de GitHub vers GitLab

### Étape 1 : Copier le repository
```bash
# Cloner depuis GitHub
git clone https://github.com/votre-user/4iSafeCross.git
cd 4iSafeCross

# Ajouter le remote GitLab
git remote add gitlab https://votre-gitlab.com/votre-user/4iSafeCross.git

# Pousser vers GitLab
git push gitlab main --all
git push gitlab --tags
```

### Étape 2 : Configurer le Runner GitLab

Sur votre serveur GitLab :
```bash
# Installer le Runner
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
sudo apt-get install gitlab-runner

# Enregistrer
sudo gitlab-runner register \
  --url "https://votre-gitlab.com/" \
  --registration-token "VOTRE_TOKEN" \
  --executor "docker" \
  --docker-image "docker:24.0" \
  --docker-privileged \
  --tag-list "docker"
```

### Étape 3 : Adapter le workflow

Le fichier `.gitlab-ci.yml` est déjà configuré et équivalent au workflow GitHub Actions.

### Étape 4 : Tester

```bash
git add .gitlab-ci.yml
git commit -m "Add GitLab CI/CD pipeline"
git push gitlab main
```

Allez dans **CI/CD > Pipelines** pour voir le pipeline se lancer.

## 🔙 Migration de GitLab vers GitHub

### Étape 1 : Copier le repository
```bash
# Cloner depuis GitLab
git clone https://votre-gitlab.com/votre-user/4iSafeCross.git
cd 4iSafeCross

# Ajouter le remote GitHub
git remote add github https://github.com/votre-user/4iSafeCross.git

# Pousser vers GitHub
git push github main --all
git push github --tags
```

### Étape 2 : Activer GitHub Actions

GitHub Actions est automatiquement activé. Pas besoin de Runner.

### Étape 3 : Adapter le workflow

Le fichier `.github/workflows/build-linux-executable.yml` est déjà configuré.

### Étape 4 : Tester

```bash
git add .github/
git commit -m "Add GitHub Actions workflow"
git push github main
```

Allez dans l'onglet **Actions** pour voir le workflow se lancer.

## 🎯 Utiliser les deux en parallèle

Vous pouvez avoir **les deux** configurations dans votre projet :

```
projet/
  .github/
    workflows/
      build-linux-executable.yml    # Pour GitHub
  .gitlab-ci.yml                     # Pour GitLab
```

- Sur GitHub : Seul le fichier `.github/workflows/*.yml` sera utilisé
- Sur GitLab : Seul le fichier `.gitlab-ci.yml` sera utilisé

**Avantage :** Portabilité maximale entre plateformes.

## ⚙️ Configuration spécifique

### Runners auto-hébergés (GitLab)

**Avantages :**
- ✅ Pas de limite de temps
- ✅ Pas de limite de stockage artifacts
- ✅ Contrôle total sur l'environnement
- ✅ Peut être sur un serveur ARM64 (pas d'émulation)

**Inconvénients :**
- ❌ Maintenance du serveur
- ❌ Coût de l'infrastructure
- ❌ Mise à jour manuelle

### Runners hébergés (GitHub)

**Avantages :**
- ✅ Pas de maintenance
- ✅ Toujours à jour
- ✅ Disponibilité garantie

**Inconvénients :**
- ❌ Minutes limitées (2000/mois gratuit)
- ❌ Pas de serveurs ARM64 natifs
- ❌ Moins de contrôle

## 🔍 Débogage

### GitHub Actions
```bash
# Logs dans l'interface Web
# Onglet Actions > Cliquer sur le workflow > Voir les logs

# Via CLI
gh run list
gh run view <run-id>
gh run download <run-id>
```

### GitLab CI
```bash
# Logs dans l'interface Web
# CI/CD > Pipelines > Cliquer sur le job > Voir les logs

# Via CLI
glab ci view
glab ci list
glab ci artifact download
```

## 📦 Téléchargement des artifacts

### GitHub
```bash
# Interface Web : Actions > Workflow > Artifacts
# CLI
gh run download --name artifact-name
```

### GitLab
```bash
# Interface Web : CI/CD > Pipelines > Job > Download artifacts
# CLI
glab ci artifact download -n artifact-name
```

## 🎓 Recommandations

### Pour un projet open-source
→ **GitHub Actions** (gratuit, intégration parfaite)

### Pour une entreprise avec GitLab
→ **GitLab CI/CD** (contrôle, runners auto-hébergés)

### Pour ce projet (4iSafeCross)
→ **GitLab CI/CD** car :
- Vous avez déjà GitLab auto-hébergé
- Pas de limite de temps de build
- Contrôle total sur les runners
- Peut compiler directement sur ARM64 si Runner sur Jetson

## 💡 Optimisation

### Runner ARM64 natif sur Jetson

Au lieu d'émuler ARM64 avec QEMU, installez un Runner directement sur le Jetson :

```bash
# Sur le Jetson
curl -L "https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-linux-arm64" -o /usr/local/bin/gitlab-runner
chmod +x /usr/local/bin/gitlab-runner

# Enregistrer
gitlab-runner register \
  --url "https://votre-gitlab.com/" \
  --registration-token "VOTRE_TOKEN" \
  --executor "shell" \
  --tag-list "arm64,jetson"
```

Puis dans `.gitlab-ci.yml`, utilisez ce runner :
```yaml
build:arm64:
  tags:
    - arm64
    - jetson
  script:
    - uv sync
    - uv run nuitka ...  # Compilation native, beaucoup plus rapide !
```

**Avantage :** Compilation **5-10x plus rapide** (pas d'émulation).

## 📞 Support

- GitHub Actions : https://docs.github.com/en/actions
- GitLab CI/CD : https://docs.gitlab.com/ee/ci/

---

**Conseil :** Gardez les deux configurations pour maximiser la portabilité de votre projet.
