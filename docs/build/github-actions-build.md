# 🚀 Compilation automatique avec GitHub Actions

Ce document explique comment utiliser le workflow GitHub Actions pour compiler automatiquement votre application 4iSafeCross en un exécutable ARM64 pour Nvidia Jetson Orin NX.

## 📋 Vue d'ensemble

Le workflow `.github/workflows/build-linux-executable.yml` utilise :
- **QEMU** pour émuler l'architecture ARM64
- **Docker** avec une image Ubuntu 22.04 ARM64
- **uv** pour gérer les dépendances Python
- **Nuitka** pour compiler l'application en exécutable natif

## 🎯 Déclenchement du workflow

Le workflow se déclenche automatiquement dans les cas suivants :

### 1. Push sur les branches principales
```bash
git push origin main
# ou
git push origin jetson_gpu
```

### 2. Pull Request
Créez une Pull Request vers `main` ou `jetson_gpu`.

### 3. Tag de version
```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```
**Bonus :** Crée automatiquement une release GitHub avec l'exécutable en pièce jointe.

### 4. Déclenchement manuel
Via l'interface GitHub :
1. Allez dans l'onglet **Actions**
2. Sélectionnez le workflow "Build Linux Executable for Jetson Orin NX"
3. Cliquez sur **Run workflow**
4. Choisissez la branche
5. Cliquez sur **Run workflow**

## 📦 Artefacts générés

Après compilation réussie, le workflow génère :

### 1. Archive TAR.GZ
- **Nom :** `4isafecross-arm64-jetson.tar.gz`
- **Contenu :** Exécutable + dépendances nécessaires
- **Localisation :** Onglet "Artifacts" dans l'exécution du workflow
- **Rétention :** 30 jours

### 2. Dossier app.dist/
Contient :
- L'exécutable principal `app`
- Les bibliothèques partagées nécessaires
- Les fichiers de données (config, templates, static, etc.)

## 📥 Téléchargement des artefacts

### Via l'interface GitHub

1. Accédez à l'onglet **Actions** de votre dépôt
2. Cliquez sur l'exécution du workflow souhaitée
3. Descendez jusqu'à la section **Artifacts**
4. Cliquez sur `4isafecross-linux-arm64-executable` pour télécharger

### Via GitHub CLI

```bash
# Lister les workflows récents
gh run list --workflow=build-linux-executable.yml

# Télécharger l'artefact du dernier run
gh run download --name 4isafecross-linux-arm64-executable
```

## 🔧 Déploiement sur Jetson Orin NX

### 1. Extraction de l'archive
```bash
# Transférer l'archive vers le Jetson
scp 4isafecross-arm64-jetson.tar.gz user-4itec@<jetson-ip>:/home/user-4itec/

# Se connecter au Jetson
ssh user-4itec@<jetson-ip>

# Extraire l'archive
tar -xzf 4isafecross-arm64-jetson.tar.gz
cd app.dist/
```

### 2. Vérification de l'exécutable
```bash
# Vérifier le type de fichier
file app

# Devrait afficher quelque chose comme :
# app: ELF 64-bit LSB executable, ARM aarch64, version 1 (SYSV), dynamically linked, ...
```

### 3. Rendre l'exécutable... exécutable
```bash
chmod +x app
```

### 4. Test de l'exécutable
```bash
# Test rapide
./app --help

# Lancement de l'application
./app
```

### 5. Mise à jour du service systemd
Si vous utilisez systemd, mettez à jour le service :

```bash
# Éditer le fichier service
sudo nano /etc/systemd/system/4isafecross.service
```

Modifiez la ligne `ExecStart` :
```ini
[Service]
ExecStart=/home/user-4itec/app.dist/app
WorkingDirectory=/home/user-4itec/app.dist
```

Rechargez et redémarrez :
```bash
sudo systemctl daemon-reload
sudo systemctl restart 4isafecross.service
sudo systemctl status 4isafecross.service
```

## 🐛 Dépannage

### Problème : Bibliothèque manquante (.so)

**Erreur :**
```
./app: error while loading shared libraries: libXXX.so: cannot open shared object file
```

**Solution :**
```bash
# Identifier les dépendances manquantes
ldd app | grep "not found"

# Installer les bibliothèques manquantes
sudo apt-get update
sudo apt-get install <package-name>
```

Bibliothèques courantes pour Jetson :
```bash
sudo apt-get install -y \
  libglib2.0-0 \
  libsm6 \
  libxrender1 \
  libxext6 \
  libgl1-mesa-glx
```

### Problème : Erreur de permissions

**Erreur :**
```
bash: ./app: Permission denied
```

**Solution :**
```bash
chmod +x app
```

### Problème : Architecture incompatible

**Erreur :**
```
cannot execute binary file: Exec format error
```

**Cause :** L'exécutable n'a pas été compilé pour ARM64.

**Vérification :**
```bash
file app
# Devrait afficher "ARM aarch64" pas "x86-64"

uname -m
# Devrait afficher "aarch64" sur Jetson
```

**Solution :** Re-déclencher le workflow et vérifier les logs.

### Problème : Erreur Nuitka dans le workflow

**Vérifier les logs GitHub Actions :**
1. Onglet **Actions**
2. Cliquer sur l'exécution échouée
3. Examiner les logs de l'étape "Build in ARM64 Docker container"

**Erreurs courantes :**
- Dépendance manquante dans `requirements.txt` ou `pyproject.toml`
- Chemin incorrect pour `--include-data-file`
- Version Python incompatible

## ⚙️ Configuration avancée

### Modifier la commande Nuitka

Éditez `.github/workflows/build-linux-executable.yml` :

```yaml
# Ajouter des optimisations
uv run nuitka \
  --standalone \
  --onefile \
  --lto=yes \              # Link-Time Optimization
  --prefer-source-code \   # Préférer le code source
  # ... reste de la commande
```

### Optimisations Nuitka

```bash
# Compilation plus rapide (pour développement)
--lto=no

# Optimisation maximale (pour production)
--lto=yes

# Créer un seul fichier au lieu d'un dossier
--onefile

# Désactiver la console (pour GUI)
--disable-console

# Inclure tous les plugins automatiquement
--follow-imports
```

### Changer la version Python

Dans le workflow, modifiez :
```yaml
apt-get install -y python3.10 python3.10-dev python3.10-venv
```

Par :
```yaml
apt-get install -y python3.12 python3.12-dev python3.12-venv
```

**⚠️ Attention :** Vérifiez la compatibilité avec Jetson JetPack 6.1 (Python 3.10 par défaut).

## 📊 Temps de compilation

| Tâche | Durée approximative |
|-------|---------------------|
| Setup QEMU + Docker | 1-2 min |
| Installation dépendances | 3-5 min |
| Compilation Nuitka | 10-20 min |
| Upload artefacts | 1-2 min |
| **Total** | **15-30 min** |

> Les temps peuvent varier selon la charge de GitHub Actions et la complexité de votre code.

## 🔐 Secrets GitHub (optionnel)

Pour déployer automatiquement, ajoutez des secrets :

1. Allez dans **Settings** > **Secrets and variables** > **Actions**
2. Ajoutez les secrets suivants :
   - `JETSON_HOST` : Adresse IP du Jetson
   - `JETSON_USER` : Nom d'utilisateur SSH
   - `JETSON_SSH_KEY` : Clé privée SSH

Puis ajoutez une étape de déploiement au workflow :
```yaml
- name: Deploy to Jetson
  uses: appleboy/scp-action@v0.1.4
  with:
    host: ${{ secrets.JETSON_HOST }}
    username: ${{ secrets.JETSON_USER }}
    key: ${{ secrets.JETSON_SSH_KEY }}
    source: "dist/*.tar.gz"
    target: "/home/user-4itec/"
```

## 📝 Checklist avant compilation

- [ ] Tous les fichiers source sont commités
- [ ] `requirements.txt` ou `pyproject.toml` à jour
- [ ] Les chemins dans `--include-data-dir` sont corrects
- [ ] Le fichier `.so` Yoctopuce existe dans le chemin spécifié
- [ ] La branche est poussée sur GitHub

## 🎓 Ressources

- [Documentation Nuitka](https://nuitka.net/doc/user-manual.html)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [QEMU User Emulation](https://www.qemu.org/docs/master/user/main.html)
- [uv Documentation](https://github.com/astral-sh/uv)

## 📞 Support

En cas de problème :
1. Vérifier les logs GitHub Actions
2. Tester la compilation localement dans Docker :
   ```bash
   docker run --platform=linux/arm64 -it -v $(pwd):/workspace -w /workspace arm64v8/ubuntu:22.04 bash
   ```
3. Consulter les [issues GitHub](https://github.com/<votre-repo>/issues)

---

**Version :** 1.0.0  
**Date :** 7 janvier 2026  
**Compatibilité :** Nvidia Jetson Orin NX (JetPack 6.1)
