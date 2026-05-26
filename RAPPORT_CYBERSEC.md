# Rapport d'audit de maturité cybersécurité — 4iSafeCross

**Date d'audit** : 26 mai 2026  
**Dépôt** : `frankkubler/4iSafeCross` — branche `main`  
**Méthode** : Analyse statique du dépôt GitHub (code source, configuration, CI/CD, documentation)  
**Référentiel** : ANSSI, OWASP ML Security Top 10, AI Act UE 2024/1689, NIST AI RMF  

> Chaque affirmation est fondée sur un fichier observable dans le dépôt.  
> Absence de preuve → ❌ "Non observable dans le dépôt."

---

## Tableau de scoring global

| Q | Thème | Score (0-3) | Éléments observés | Urgence |
|---|---|:---:|---|:---:|
| Q1 | Analyse des risques | **1** | `REGISTRE_TRAITEMENTS_RGPD.md` (AIPD incluse), `FAILSAFE_MODE.md` — aucun EBIOS/STRIDE | Haute |
| Q2 | AI Act | **1** | RGPD/AIPD documentés, AI Act absent du dépôt — système candidat Haut Risque | Haute |
| Q3 | SBOM / composants | **1** | `uv.lock` + hachages SHA256, pas de SBOM formel, pas de scan CVE en CI/CD | Moyenne |
| Q4 | DevSecOps | **2** | `.env.example` + `chmod 600`, UFW/Fail2ban dans script — credentials VNC en clair (`README.md` L.477) | **Critique** |
| Q5 | Tests sécurité | **0** | Tests fonctionnels uniquement, aucun SAST/DAST/SCA dans les deux pipelines CI | Haute |
| Q6 | Données entraînement | **1** | Collecte auto documentée + purge RGPD, boucle rétroaction labels, aucune signature intégrité | Moyenne |
| Q7 | Explicabilité XAI | **2** | Logs décision + images annotées Telegram, filtres documentés — aucune métrique F1/précision | Faible |
| Q8 | Protection modèles | **2** | Cython + Nuitka + Docker multi-stage, poids hors dépôt — aucune vérif SHA256 au démarrage | Moyenne |
| Q9 | API / interactions | **1** | Flask `0.0.0.0:5050` sans auth (`app.py` L.1568), HTTP interne ports 8001/8002 — Telegram HTTPS ✅ | **Critique** |
| Q10 | Attaques adversariales | **1** | 3 filtres empiriques + MOG2 — aucun test adversarial formel | Faible |
| **TOTAL** | | **12/30** | | |

**Niveau de maturité : N2 — En développement** (seuil 11-20/30)

---

## Analyse détaillée

### Q1 — Analyse des risques cybersécurité · Score : 1/3

**Observable dans le dépôt :**
- `REGISTRE_TRAITEMENTS_RGPD.md` : registre complet Art. 30 RGPD + AIPD Art. 35, test de mise en balance documenté. Traite les **risques RGPD** (isolation réseau, rétention, base légale).
- `FAILSAFE_MODE.md` + `app.py` L.70-76 : identification du risque de faux négatif (absence d'alerte sur crash) → implémentation watchdog fail-safe 30 s.
- `src/inference.py` : 3 filtres anti-faux-positifs (keypoints, debounce, driver) — réponse à un risque de sécurité physique.

**Lacunes :**
- ❌ Aucun document EBIOS RM, STRIDE, ISO 27005 ou analyse de menaces **cyber** formalisée dans le dépôt.
- ❌ Les risques cyber spécifiques ne sont pas documentés : attaque du serveur d'inférence HTTP interne (ports 8001/8002), compromission du bot Telegram, data poisoning du dataset, injection de flux RTSP falsifié.
- ⚠️ Le registre RGPD n'est **pas** une analyse de risques cyber au sens de l'AI Act — il traite de la protection des données, pas des menaces sur le système IA lui-même.

**Recommandation (Haute urgence)** : Créer un document `ANALYSE_RISQUES_CYBER.md` avec au minimum 5 scénarios STRIDE : Spoofing flux RTSP, Tampering dataset, DoS serveur d'inférence, Escalade via Flask non authentifié, Compromission token Telegram.

---

### Q2 — Conformité réglementaire (AI Act) · Score : 1/3

**Observable dans le dépôt :**
- `REGISTRE_TRAITEMENTS_RGPD.md` : conformité RGPD et AIPD documentées — preuve d'une démarche réglementaire.
- ❌ Aucune occurrence du terme "AI Act", "Règlement 2024/1689", "haut risque IA", "Annex III" dans aucun fichier du dépôt.

**Analyse de classification probable :**  
Le système relève **probablement de la catégorie Haut Risque** (AI Act Art. 6 + Annexe III §6) :
- Composant de sécurité d'un système physique (chariots élévateurs en milieu industriel)
- Pilote des actionneurs physiques (relais Yoctopuce → avertisseurs lumineux/sonores)
- Surveille des personnes physiques en milieu de travail

**Obligations AI Act Haut Risque non visibles dans le dépôt :**
- ❌ Documentation technique Art. 11 (dont métriques de performance du modèle)
- ❌ Système de gestion des risques Art. 9
- ❌ Supervision humaine formalisée Art. 14 (Label Studio mentionné dans README mais non formalisé)
- ❌ Enregistrement des logs pour auditabilité réglementaire Art. 12

**Recommandation (Haute urgence)** : Évaluer formellement la classification AI Act (consultation juridique). Si Haut Risque confirmé, créer la documentation technique Art. 11 et nommer un responsable conformité.

---

### Q3 — Cartographie des composants tiers (SBOM) · Score : 1/3

**Observable dans le dépôt :**
- `uv.lock` : verrouillage de toutes les dépendances transitives avec hachages SHA256 — traçabilité partielle ✅
- `pyproject.toml` : 9 dépendances directes déclarées (aiogram, flask, waitress, opencv-python, psutil, requests, yoctopuce, nuitka, gunicorn).
- `Dockerfile` L.1 : `FROM nvcr.io/nvidia/l4t-jetpack:r36.4.0` — image de base épinglée à un tag précis ✅
- `Dockerfile` L.33 : `curl -LsSf https://astral.sh/uv/install.sh | sh` — téléchargement **sans vérification de hash** ⚠️

**Lacunes :**
- ❌ `.gitlab-ci.yml` : pipeline uniquement `build` + `release` — aucun job Trivy, pip-audit, Safety, Dependabot.
- ❌ `.github/workflows/build-linux-executable.yml` : pipeline Nuitka — aucune analyse de sécurité.
- ❌ Aucun fichier SBOM (CycloneDX, SPDX) généré ou stocké.
- ❌ Dépôts d'inférence externes (`4itec-org/inf_jetson_rf-detr`, `4itec-org/inf_jetson_yolo`) non audités, référencés dans `README.md` sans mention de vérification.

**Recommandation (Moyenne urgence)** :
1. Ajouter dans `.gitlab-ci.yml` un job `security:scan` avec `trivy image` + `pip-audit`.
2. Remplacer `curl | sh` par un téléchargement avec vérification de hash dans le `Dockerfile`.

---

### Q4 — Bonnes pratiques DevSecOps · Score : 2/3

**Observable dans le dépôt (positif) :**
- `.env.example` : template avec instructions `chmod 600` — secrets externalisés ✅
- `.gitignore` : `.env` et `.env.*` explicitement exclus ✅
- `scripts/install_xrdp_jetson.sh` : `apt install -y ... ufw fail2ban` — UFW et Fail2ban installés et configurés ✅
- `README.md §VNC` : restriction du port 5999 au sous-réseau `192.168.3.0/24` ✅

**🚨 CRITIQUE — Observable dans le dépôt :**
- `README.md` ligne **477** (dépôt public GitHub) :
  ```
  user : user-4itec / mdp : ***REMOVED-PASSWORD***
  ```
  Credentials VNC en clair dans un dépôt public. Vecteur d'intrusion direct sur le système de production.

**Lacunes supplémentaires :**
- ❌ Aucun guide de référence explicite cité (OWASP, ANSSI, NIST SP 800-218).
- ❌ Aucun outil SAST (Bandit, Semgrep) dans les deux pipelines CI/CD.
- ❌ `Dockerfile` L.33 : `curl | sh` sans vérification (risque supply chain).

**Recommandation (Critique — immédiat)** : Supprimer le mot de passe du README et tourner le credential sur le Jetson de production. Ajouter ensuite `bandit` dans la CI/CD.

---

### Q5 — Tests de sécurité automatisés · Score : 0/3

**Observable dans le dépôt :**
- `test_detections_format.py` : tests fonctionnels sur le format des détections YOLO.
- `test_zone_editor.py` : tests fonctionnels sur l'éditeur de zones.
- `.gitlab-ci.yml` : 2 stages (`build`, `release`) — **aucun stage `security` ou `test`**.
- `.github/workflows/build-linux-executable.yml` : build Nuitka ARM64 — **aucune étape de sécurité**.

**Lacunes :**
- ❌ Aucun SAST (Bandit, Semgrep) — pas de détection de `eval()`, injections, secrets hardcodés.
- ❌ Aucun SCA (pip-audit, Safety, Trivy) — pas de scan CVE sur les 9 dépendances directes.
- ❌ Aucun DAST — les endpoints Flask (`/api/masks/<cam_id>`, `/zone_editor/<cam_id>`, `/set_motion_param/<int:cid>`) ne sont jamais testés pour leur surface d'attaque.
- ❌ Aucun fuzzing des endpoints REST.

**Recommandation (Haute urgence)** : Ajouter un stage `security` dans `.gitlab-ci.yml` avec `bandit -r src/ utils/ app.py -ll` et `pip-audit --require-hashes -r requirements.txt`.

---

### Q6 — Risques liés aux données d'entraînement · Score : 1/3

**Observable dans le dépôt :**
- `src/collect_dataset.py` L.57-68 : remapping `TRANSFERT_TO_DATASET` — les labels du dataset sont les **prédictions du modèle en production**. Boucle de rétroaction (confirmation bias) documentée mais non mitigée dans le code.
- `REGISTRE_TRAITEMENTS_RGPD.md` §2.4 : collecte dataset documentée, quota 30/h par classe, purge automatique au démarrage ✅
- `README.md §Flux de travail recommandé` : vérification manuelle via Label Studio préconisée — **non implémentée automatiquement**.

**Lacunes :**
- ❌ Aucune signature d'intégrité (hash SHA256) des images collectées dans `dataset/`.
- ❌ Aucun mécanisme de détection de tampering sur le dataset.
- ❌ Vecteur de **data poisoning** : un accès réseau ou physique permet d'injecter des images qui seront étiquetées automatiquement par le modèle compromis.
- ❌ Images de personnes dans `dataset/` : risque RGPD résiduel si les fichiers sont accessibles sans contrôle d'accès.

**Recommandation (Moyenne urgence)** : Séparer formellement le pipeline de collecte (production) de la validation avant réentraînement (humaine obligatoire). Ajouter un manifeste d'intégrité `dataset/manifest.sha256` mis à jour à chaque capture.

---

### Q7 — Explicabilité des modèles IA (XAI) · Score : 2/3

**Observable dans le dépôt :**
- `src/bot_aiogram.py` : envoi d'une image annotée (boîtes, zones, stature) à chaque alerte Telegram — traçabilité opérationnelle ✅
- `README.md §Pipeline` + `KEYPOINT_FILTER_README.md` + `POSE_DETECTION_README.md` : logique de décision entièrement documentée (3 filtres, seuils configurables).
- Logs applicatifs : messages explicites `Filtre keypoints bypassé`, `Faux positif écarté — pose=[] zones=[]` — traçabilité runtime ✅
- `app.py` : endpoint `/failsafe_status` retourne l'état du watchdog et des relais — monitoring exposé ✅

**Lacunes :**
- ❌ Aucune métrique de performance du modèle (précision, rappel, F1, taux de faux positifs/négatifs) dans aucun fichier du dépôt.
- ❌ Aucun outil XAI formel (Grad-CAM, SHAP, LIME).
- ⚠️ L'absence de métriques documentées est un obstacle bloquant à une certification AI Act Haut Risque (Art. 11 §1-b).

**Recommandation (Faible urgence)** : Créer un fichier `MODEL_PERFORMANCE.md` avec les métriques mesurées sur un jeu de test représentatif. Enregistrer ces métriques dans la base SQLite lors du réentraînement.

---

### Q8 — Protection des modèles IA · Score : 2/3

**Observable dans le dépôt :**
- `CYTHON_README.md` + `setup_cython.py` : compilation Cython → `.so` ARM64 — obfuscation du code source ✅ (pas des poids)
- `.gitlab-ci-nuitka.yml` + `.github/workflows/build-linux-executable.yml` : compilation Nuitka exécutable ARM64 autonome ✅
- `Dockerfile` : multi-stage build — seuls les binaires `.so` sont dans l'image finale (sources `.py` supprimées) ✅
- Poids des modèles dans des dépôts séparés (`4itec-org/inf_jetson_yolo`, `4itec-org/inf_jetson_rf-detr`) — isolation architecturale ✅

**Lacunes :**
- ❌ Aucune vérification SHA256 des poids au démarrage du service systemd ou du conteneur Docker.
- ❌ Aucune signature des artefacts modèles (pas de cosign, pas de sigstore).
- ⚠️ `CYTHON_README.md` §Sécurité : "Strings hardcodées visibles avec `strings`" — risque résiduel documenté mais non mitigé.

**Recommandation (Moyenne urgence)** : Ajouter dans le script de démarrage systemd une vérification :
```bash
sha256sum -c /app/models/model.sha256 || { echo "Intégrité modèle compromise" ; exit 1 ; }
```

---

### Q9 — Sécurisation des interactions et des API · Score : 1/3

**Observable dans le dépôt :**
- `app.py` ligne **1568** : `serve(app, host='0.0.0.0', port=5050)` — Flask exposé sur toutes les interfaces ✅ (confirmé)
- Analyse de `app.py` (20+ routes) : aucun décorateur `@login_required`, aucun middleware JWT, aucune clé API.
- `src/inference.py` : appels `POST /infer` et `POST /pose` vers `http://localhost:8001` et `http://localhost:8002` — **HTTP en clair** sur le réseau interne.
- `src/bot_aiogram.py` : API Telegram via **HTTPS**, token lu depuis variable d'environnement ✅
- `scripts/install_xrdp_jetson.sh` : règle UFW pour le port VNC — **aucune règle UFW pour le port 5050**.

**Lacunes critiques :**
- ❌ Flask sans authentification sur `0.0.0.0:5050` : n'importe quel hôte du réseau peut modifier les zones de détection, désactiver la détection, modifier les paramètres MOG2 ou accéder au flux vidéo MJPEG en temps réel.
- ❌ Aucun HTTPS — pas de TLS, pas de reverse proxy Nginx/Caddy.
- ❌ Port 5050 non restreint par UFW dans la documentation d'installation.

**Recommandation (Critique urgence)** :
1. **Court terme** : `flask-httpauth` avec `HTTPBasicAuth` + mot de passe depuis `.env`
2. **Moyen terme** : Reverse proxy Caddy avec TLS
3. **Court terme** : `ufw allow from 192.168.3.0/24 to any port 5050` dans `install_xrdp_jetson.sh`

---

### Q10 — Protection contre les attaques adversariales · Score : 1/3

**Observable dans le dépôt :**
- `README.md §Filtres` + `src/inference.py` : 3 filtres empiriques en cascade (keypoints, debounce, driver) — défenses indirectes ✅
- `src/motion.py` : MOG2 en pré-filtre — résistance partielle aux frames figées injectées ✅
- `README.md §Fail-safe` : philosophie "alerter en cas de doute" — protection contre la suppression de détection ✅

**Lacunes :**
- ❌ Aucune référence aux attaques adversariales formelles (FGSM, PGD, adversarial patch physique) dans aucun fichier.
- ❌ Aucun outil de robustesse (IBM ART, Foolbox, CleverHans).
- ❌ Aucun test de robustesse documenté (occlusion, variations lumière, patch autocollant sur chariot).
- ❌ Aucun monitoring de data drift en production.
- ⚠️ Vecteur réaliste : un adversarial patch physique (autocollant sur un chariot) peut tromper YOLO11m et supprimer la détection — les filtres empiriques ne protègent pas contre ce vecteur.

**Recommandation (Faible urgence)** : Documenter les tests de robustesse réalisés sur site. Ajouter un monitoring de la distribution des scores de confiance pour détecter un drift silencieux.

---

## Points forts

1. **Mode fail-safe implémenté et documenté** — `app.py` L.70-76 + `FAILSAFE_MODE.md` + watchdog 30 s : relais ON par défaut en cas de crash. Approche de sécurité physique robuste et rare pour un système industriel IA.

2. **Gestion des secrets conforme** — `.env.example` + `.gitignore` (exclusion `.env`) + instructions `chmod 600` + README §Credentials : la chaîne complète est documentée et implémentée.

3. **Registre RGPD + AIPD complets** — `REGISTRE_TRAITEMENTS_RGPD.md` : 150+ lignes couvrant base légale, durées de conservation, mesures techniques, droits des personnes et AIPD Art. 35. Niveau de maturité RGPD nettement supérieur à la moyenne des projets industriels.

---

## Points critiques immédiats

### 🔴 CRITIQUE #1 — Credentials VNC en clair dans un dépôt public
**Fichier** : `README.md` ligne 477  
Accès VNC direct au Jetson de production visible par tout lecteur du dépôt GitHub public.  
**Action** : Supprimer la ligne + tourner le mot de passe sur le Jetson.

### 🔴 CRITIQUE #2 — Flask sans authentification sur `0.0.0.0:5050`
**Fichier** : `app.py` ligne 1568  
Tous les endpoints de contrôle sont accessibles sans authentification depuis n'importe quel hôte du réseau local (désactivation détection, modification zones, flux vidéo live).  
**Action** : Ajouter `flask-httpauth` avec `HTTPBasicAuth` + restriction UFW port 5050.

### 🟠 HAUTE #3 — Aucune analyse de vulnérabilités en CI/CD
**Fichiers** : `.gitlab-ci.yml`, `.github/workflows/build-linux-executable.yml`  
Aucun des deux pipelines ne comprend de scan CVE ou d'analyse statique de sécurité.  
**Action** : Ajouter un stage `security` avec `bandit` + `pip-audit`.

---

## Feuille de route

### Phase 1 — Immédiat (< 24 h)

- [ ] Supprimer les credentials VNC du `README.md` L.477 et tourner le mot de passe sur le Jetson
- [ ] Ajouter `ufw allow from 192.168.3.0/24 to any port 5050` dans `scripts/install_xrdp_jetson.sh`

### Phase 2 — Court terme (< 2 semaines)

- [ ] Ajouter `flask-httpauth>=4.8.0` dans `pyproject.toml`
- [ ] Créer `utils/auth.py` avec `HTTPBasicAuth` — mot de passe depuis `os.environ["FLASK_PASSWORD"]`
- [ ] Protéger les endpoints sensibles de `app.py` avec `@auth.login_required`
- [ ] Ajouter `FLASK_PASSWORD=<mot_de_passe_interface_web>` dans `.env.example`

### Phase 3 — Court terme (< 6 semaines)

- [ ] Ajouter un stage `security` dans `.gitlab-ci.yml` (`bandit` + `pip-audit`) avant le stage `build`
- [ ] Corriger `Dockerfile` L.33 : remplacer `curl | sh` par téléchargement avec vérification SHA256
- [ ] Créer `ANALYSE_RISQUES_CYBER.md` avec 5 scénarios STRIDE

### Phase 4 — Moyen terme (3-6 mois)

- [ ] Générer un SBOM (CycloneDX) dans la CI/CD
- [ ] Créer `MODEL_PERFORMANCE.md` avec métriques précision/rappel/F1
- [ ] Ajouter vérification SHA256 des poids au démarrage systemd/Docker
- [ ] Évaluation AI Act : consultation juridique sur la classification Haut Risque

### Phase 5 — Long terme (6-12 mois)

- [ ] Déployer reverse proxy Caddy avec TLS sur le port 5050
- [ ] Monitoring data drift (alerter si distribution scores de confiance dérive de ±20 %)
- [ ] Tests de robustesse documentés (adversarial patch, occultation, variations lumière)
- [ ] Documentation technique AI Act Art. 11 si classification Haut Risque confirmée

---

## Références

- [ANSSI — Maîtriser les risques liés aux systèmes d'IA](https://www.ssi.gouv.fr/guide/intelligence-artificielle-et-securite/)
- [OWASP ML Security Top 10](https://owasp.org/www-project-machine-learning-security-top-10/)
- [AI Act UE 2024/1689](https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32024R1689)
- [NIST AI RMF 1.0](https://airc.nist.gov/RMF_Overview)
- [IBM Adversarial Robustness Toolbox](https://github.com/Trusted-AI/adversarial-robustness-toolbox)
- [CycloneDX SBOM Specification](https://cyclonedx.org/)
