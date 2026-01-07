# 🦊 Compilation automatique avec GitLab CI/CD

Ce document explique comment utiliser le pipeline GitLab CI/CD pour compiler automatiquement votre application 4iSafeCross en un exécutable ARM64 pour Nvidia Jetson Orin NX sur votre instance GitLab auto-hébergée.

## 📋 Prérequis

### 1. GitLab Runner configuré

Votre instance GitLab doit avoir au moins un Runner avec :
- **Executor : Docker**
- **Tag : `docker`**
- **Privilèges : Activés** (pour QEMU et émulation ARM64)

#### Vérifier les Runners disponibles

Dans votre projet GitLab :
1. Allez dans **Settings** > **CI/CD** > **Runners**
2. Vérifiez qu'au moins un Runner est actif et a le tag `docker`

#### Installer un Runner sur votre serveur GitLab (si nécessaire)

```bash
# Sur votre serveur GitLab
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
sudo apt-get install gitlab-runner

# Enregistrer le Runner
sudo gitlab-runner register \
  --url "https://votre-gitlab.com/" \
  --registration-token "VOTRE_TOKEN" \
  --executor "docker" \
  --docker-image "docker:24.0" \
  --docker-privileged \
  --tag-list "docker"

# Démarrer le Runner
sudo gitlab-runner start
```

### 2. Docker-in-Docker activé

Le Runner doit pouvoir exécuter Docker dans Docker (DinD) pour l'émulation ARM64.

Vérifiez dans `/etc/gitlab-runner/config.toml` :
```toml
[[runners]]
  [runners.docker]
    privileged = true
    volumes = ["/cache", "/var/run/docker.sock:/var/run/docker.sock"]
```

## 🎯 Déclenchement du pipeline

Le pipeline se déclenche automatiquement dans les cas suivants :

### 1. Push sur les branches principales
```bash
git push origin main
# ou
git push origin jetson_gpu
```

### 2. Merge Request
Créez une Merge Request vers `main` ou `jetson_gpu`.

### 3. Tag de version (avec release automatique)
```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```
**🎉 Crée automatiquement une release GitLab avec l'exécutable en pièce jointe.**

### 4. Déclenchement manuel
Via l'interface GitLab :
1. Allez dans **CI/CD** > **Pipelines**
2. Cliquez sur **Run Pipeline**
3. Sélectionnez la branche
4. Cliquez sur **Run Pipeline**

### 5. Job de test manuel
Pour tester la compilation sans déclencher tout le pipeline :
1. Allez dans **CI/CD** > **Pipelines**
2. Cliquez sur une pipeline en cours ou terminée
3. Dans le job `test:local`, cliquez sur le bouton ▶️ **Play**

## 📊 Stages du Pipeline

Le pipeline se compose de 3 stages :

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   build     │  →   │  package    │  →   │  release    │
│   (ARM64)   │      │  (tar.gz)   │      │  (tags)     │
└─────────────┘      └─────────────┘      └─────────────┘
```

### Stage 1 : Build (15-30 min)
- Configure QEMU pour émulation ARM64
- Lance un conteneur Docker ARM64
- Installe les dépendances système et Python
- Compile avec Nuitka
- Génère l'exécutable dans `dist/`

### Stage 2 : Package (1-2 min)
- Crée une archive `.tar.gz` de l'exécutable
- Optimise la taille
- Publie l'artefact

### Stage 3 : Release (30 sec)
- **Uniquement pour les tags**
- Crée une release GitLab
- Attache l'archive comme asset
- Génère une description avec instructions de déploiement

## 📥 Téléchargement des artefacts

### Via l'interface GitLab

#### Pour une pipeline normale (branche)
1. Allez dans **CI/CD** > **Pipelines**
2. Cliquez sur la pipeline réussie
3. Dans le job `package:arm64`, cliquez sur **Download artifacts** (⬇️)
4. Extrayez l'archive `4isafecross-arm64-jetson.tar.gz`

#### Pour une release (tag)
1. Allez dans **Deployments** > **Releases**
2. Cliquez sur la release souhaitée
3. Téléchargez `4isafecross-arm64-jetson.tar.gz` dans les assets

### Via GitLab CLI (glab)

```bash
# Installer glab
brew install glab  # macOS
# ou
sudo apt install glab  # Ubuntu

# Se connecter à votre GitLab
glab auth login --hostname votre-gitlab.com

# Télécharger l'artefact de la dernière pipeline
glab ci artifact download -n 4isafecross-arm64-jetson

# Télécharger depuis une release
glab release download v1.0.0
```

### Via curl (API GitLab)

```bash
# Définir les variables
GITLAB_URL="https://votre-gitlab.com"
PROJECT_ID="123"  # ID de votre projet
TOKEN="votre-token-privé"
REF="main"  # ou nom du tag

# Télécharger l'artefact
curl --header "PRIVATE-TOKEN: ${TOKEN}" \
  "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/jobs/artifacts/${REF}/download?job=package:arm64" \
  -o artifacts.zip

# Extraire
unzip artifacts.zip
```

## 🔧 Déploiement sur Jetson Orin NX

### 1. Transférer l'archive
```bash
scp 4isafecross-arm64-jetson.tar.gz user-4itec@<jetson-ip>:/home/user-4itec/
```

### 2. Se connecter au Jetson
```bash
ssh user-4itec@<jetson-ip>
```

### 3. Extraire et lancer
```bash
# Extraire
tar -xzf 4isafecross-arm64-jetson.tar.gz

# Si l'archive contient un dossier app.dist/
cd app.dist/
chmod +x app
./app

# Si l'archive contient un fichier unique 4isafecross
chmod +x 4isafecross
./4isafecross
```

### 4. Mise à jour du service systemd

```bash
# Arrêter le service
sudo systemctl stop 4isafecross.service

# Mettre à jour l'exécutable
sudo cp app /usr/local/bin/4isafecross
# ou copier tout le dossier
sudo cp -r app.dist/ /opt/4isafecross/

# Éditer le service
sudo nano /etc/systemd/system/4isafecross.service
```

Mettez à jour `ExecStart` :
```ini
[Service]
ExecStart=/opt/4isafecross/app
WorkingDirectory=/opt/4isafecross
User=user-4itec
```

Redémarrez :
```bash
sudo systemctl daemon-reload
sudo systemctl start 4isafecross.service
sudo systemctl status 4isafecross.service
```

## 🐛 Dépannage

### Problème : Runner ne démarre pas le pipeline

**Erreur :**
```
This job is stuck because the project doesn't have any runners online
```

**Solutions :**
1. Vérifier que le Runner est actif :
   ```bash
   sudo gitlab-runner status
   sudo gitlab-runner start
   ```

2. Vérifier que le Runner a le bon tag (`docker`)

3. Vérifier que le Runner n'est pas en pause dans **Settings** > **CI/CD** > **Runners**

### Problème : Erreur QEMU / émulation ARM64

**Erreur :**
```
exec /bin/bash: exec format error
```

**Solution :**
Le Runner doit avoir les privilèges pour QEMU. Dans `/etc/gitlab-runner/config.toml` :
```toml
[[runners]]
  [runners.docker]
    privileged = true
```

Redémarrer le Runner :
```bash
sudo gitlab-runner restart
```

### Problème : Timeout du job

**Erreur :**
```
Job execution timeout
```

**Solution :**
Augmenter le timeout dans **Settings** > **CI/CD** > **General pipelines** :
- Timeout : 60 minutes (au lieu de 30)

Ou dans `.gitlab-ci.yml`, ajouter :
```yaml
build:arm64:
  timeout: 60 minutes
```

### Problème : Manque d'espace disque sur le Runner

**Erreur :**
```
no space left on device
```

**Solution :**
Nettoyer les images Docker sur le serveur du Runner :
```bash
# Sur le serveur du Runner
docker system prune -af --volumes
```

### Problème : Compilation Nuitka échoue

**Vérifier les logs :**
1. Dans GitLab : **CI/CD** > **Pipelines** > Cliquez sur le job échoué
2. Consultez les logs détaillés

**Causes courantes :**
- Dépendance manquante dans `requirements.txt`
- Chemin incorrect dans `--include-data-file`
- Version Python incompatible

## ⚙️ Configuration avancée

### Modifier les branches déclenchant le pipeline

Dans `.gitlab-ci.yml`, modifiez les sections `only:` :
```yaml
only:
  - main
  - develop
  - jetson_gpu
```

### Désactiver le pipeline pour certains commits

Ajoutez `[skip ci]` ou `[ci skip]` dans votre message de commit :
```bash
git commit -m "Documentation update [skip ci]"
```

### Ajouter des notifications

#### Slack
Dans **Settings** > **Integrations** > **Slack notifications** :
- Cochez "Pipeline"
- Entrez le Webhook URL

#### Email
GitLab envoie automatiquement des emails pour les pipelines échouées.

### Cache pour accélérer les builds

Ajoutez dans `.gitlab-ci.yml` :
```yaml
build:arm64:
  cache:
    key: ${CI_COMMIT_REF_SLUG}
    paths:
      - .venv/
      - .nuitka/
```

### Variables d'environnement

Dans **Settings** > **CI/CD** > **Variables**, ajoutez :
- `JETSON_HOST` : IP du Jetson
- `JETSON_USER` : Utilisateur SSH
- `JETSON_SSH_KEY` : Clé privée SSH (type: File)

Utilisez-les dans le pipeline :
```yaml
deploy:
  stage: deploy
  script:
    - scp dist/*.tar.gz ${JETSON_USER}@${JETSON_HOST}:/home/user-4itec/
  only:
    - main
```

## 📊 Monitoring et statistiques

### Voir l'historique des pipelines
**CI/CD** > **Pipelines** > Filtrez par branche/tag

### Statistiques de durée
**CI/CD** > **Pipelines** > **Charts**

### Artefacts stockés
**CI/CD** > **Artifacts** > Voir tous les artefacts du projet

### Runners actifs
**Settings** > **CI/CD** > **Runners** > Statistiques

## 🔐 Sécurité

### Protéger les branches
**Settings** > **Repository** > **Protected branches**
- Protégez `main` et `jetson_gpu`
- Limiter les pushs aux Maintainers

### Protéger les tags
**Settings** > **Repository** > **Protected tags**
- Protégez `v*.*.*`
- Seuls les Maintainers peuvent créer des releases

### Runner dédié au projet
Pour plus de sécurité, utilisez un Runner spécifique :
1. **Settings** > **CI/CD** > **Runners**
2. Cliquez sur **New project runner**
3. Suivez les instructions

## 📝 Checklist avant compilation

- [ ] Le Runner GitLab est actif et a le tag `docker`
- [ ] Docker-in-Docker est configuré
- [ ] Tous les fichiers source sont commités
- [ ] `requirements.txt` ou `pyproject.toml` à jour
- [ ] Les chemins dans `.gitlab-ci.yml` sont corrects
- [ ] Le fichier `.so` Yoctopuce existe
- [ ] La branche est poussée sur GitLab

## 🎓 Ressources

- [Documentation GitLab CI/CD](https://docs.gitlab.com/ee/ci/)
- [GitLab Runner](https://docs.gitlab.com/runner/)
- [Docker Executor](https://docs.gitlab.com/runner/executors/docker.html)
- [GitLab API](https://docs.gitlab.com/ee/api/)
- [Documentation Nuitka](https://nuitka.net/doc/user-manual.html)

## 💡 Astuces

### Accélérer les builds
- Utilisez un Runner local sur un serveur ARM64 (pas d'émulation nécessaire)
- Activez le cache GitLab CI
- Utilisez `--lto=no` pendant le développement

### Débugger un job
Activez le mode debug dans le job :
```yaml
variables:
  CI_DEBUG_TRACE: "true"
```

### Paralléliser les builds
Pour compiler en parallèle (x86 + ARM64) :
```yaml
build:x86:
  extends: .build_template
  image: ubuntu:22.04

build:arm64:
  extends: .build_template
  image: arm64v8/ubuntu:22.04
  
.build_template:
  stage: build
  script:
    - echo "Build pour $CI_JOB_NAME"
```

## 📞 Support

En cas de problème avec GitLab CI/CD :
1. Consulter les logs du job dans GitLab
2. Vérifier l'état du Runner : `sudo gitlab-runner status`
3. Consulter les logs du Runner : `sudo journalctl -u gitlab-runner -f`
4. Tester localement : `bash scripts/test-build-local.sh`

---

**Version :** 1.0.0  
**Date :** 7 janvier 2026  
**Compatibilité :** GitLab CE/EE 15.0+ | Nvidia Jetson Orin NX (JetPack 6.1)
