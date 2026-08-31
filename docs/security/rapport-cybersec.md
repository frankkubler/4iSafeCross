# Rapport d'audit de maturité cybersécurité — 4iSafeCross

**Date d'audit** : 26 mai 2026 — **Révision 2** : 27 mai 2026 (air-gap + accès physique direct uniquement + dépôt privé) — **Révision 3** : 24 juillet 2026 (migration base image JetPack 7.2 / CUDA 13.2, voir Q3)  
**Dépôt** : `frankkubler/4iSafeCross` — branche `main`  
**Méthode** : Analyse statique du dépôt GitHub (code source, configuration, CI/CD, documentation)  
**Référentiel** : ANSSI, OWASP ML Security Top 10, AI Act UE 2024/1689, NIST AI RMF  

> Chaque affirmation est fondée sur un fichier observable dans le dépôt.  
> Absence de preuve → ❌ "Non observable dans le dépôt."

---

## Contexte de déploiement — Air-gap documenté

**Source** : `REGISTRE_TRAITEMENTS_RGPD.md` §4 Mesures de sécurité (observable dans le dépôt) :

> *"Isolation réseau : Système non connecté à internet en production — accès uniquement par câble RJ45 local"*  
> *"En configuration de production standard (`TELEGRAM_ENABLED = false`), aucune donnée ne quitte le réseau local du site, pas de clé 4G branchée au PC IA."*

**Architecture réseau documentée** (`README.md` §Ports réseau) :

| Interface | Adresse | Fonction | Actif en production |
|---|---|---|:---:|
| eth0 | DHCP | Internet / réseau principal | ❌ **Non connecté** |
| eth1 | 192.168.2.x | Sous-réseau caméras IP dédié | ✅ |
| eth2 | 192.168.3.122 | **Câble RJ45 direct** PC maintenance (point-à-point) | Occasionnel |
| eth3/eth4 | — | Non utilisés | ❌ |

> **Précision architecture** : eth2 est un lien **point-à-point physique** entre le Jetson et un PC de maintenance. Il n'y a **ni routeur, ni switch, ni réseau d'usine** partagé. L'accès à l'interface Flask ou au VNC nécessite obligatoirement d'être physiquement présent et de brancher un câble RJ45 directement sur le boîtier.

### Modèle de menace révisé

L'absence de connexion internet **et** l'absence de réseau partagé éliminent la quasi-totalité des vecteurs d'attaque distants.

| Acteur de menace | Vecteur d'accès | Probabilité | Commentaire |
|---|---|---|---|
| Attaquant externe (internet) | — | ❌ Éliminé | eth0 non connecté |
| Employé / opérateur réseau usine | — | ❌ Éliminé | Pas de réseau partagé |
| Technicien de maintenance | Câble RJ45 physique sur eth2 | Très faible | Accès physique requis |
| Caméra IP compromise (eth1) | Flask port 5050 via eth1 | Très faible | Caméras = équipements dédiés sans TCP sortant |
| Accès physique direct au boîtier | USB, clavier, câble direct | Très faible | Même niveau qu'ouvrir le boîtier |
| **Supply chain (build)** | Dépendances compromises à la **compilation** | Faible | Seul vecteur distant réaliste |
| **Manipulation dataset** | Accès physique au stockage | Faible | Réentraînement biaisé |

**Conséquence sur les priorités** : les risques réseau (Flask sans auth, Flask sans TLS) sont **non pertinents dans ce déploiement**. Les priorités réelles sont la **conformité AI Act**, l'**intégrité du dataset** et la **supply chain de build**.

---

## Tableau de scoring global

| Q | Thème | Score (0-3) | Éléments observés | Urgence |
|---|---|:---:|---|:---:|
| Q1 | Analyse des risques | **1** | `REGISTRE_TRAITEMENTS_RGPD.md` (AIPD incluse), `FAILSAFE_MODE.md` — aucun EBIOS/STRIDE | Haute |
| Q2 | AI Act | **1** | RGPD/AIPD documentés, AI Act absent du dépôt — système candidat Haut Risque | Haute |
| Q3 | SBOM / composants | **1** | `uv.lock` + hachages SHA256, pas de SBOM formel, pas de scan CVE en CI/CD | Moyenne |
| Q4 | DevSecOps | **2** | `.env.example` + `chmod 600`, UFW/Fail2ban — credentials VNC dans README (dépôt privé, accès physique requis) | Faible |
| Q5 | Tests sécurité | **0** | Tests fonctionnels uniquement, aucun SAST/SCA dans les deux pipelines CI | Haute |
| Q6 | Données entraînement | **1** | Collecte auto documentée + purge RGPD, boucle rétroaction labels, aucune signature intégrité | Moyenne |
| Q7 | Explicabilité XAI | **2** | Logs décision + images annotées Telegram, filtres documentés — aucune métrique F1/précision | **Haute** |
| Q8 | Protection modèles | **2** | Cython + Nuitka + Docker multi-stage, poids hors dépôt — aucune vérif SHA256 au démarrage | Moyenne |
| Q9 | API / interactions | **3** | Flask accessible uniquement via câble physique direct — Telegram HTTPS ✅ — contexte air-gap validé | ✅ N/A |
| Q10 | Attaques adversariales | **1** | 3 filtres empiriques + MOG2 — aucun test adversarial formel | Faible |
| **TOTAL** | | **15/30** | | |

**Niveau de maturité : N2 — En développement** (seuil 11-20/30)  
> Score révisé à la hausse (+3) grâce à la prise en compte du contexte de déploiement réel (air-gap + accès physique uniquement).

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

**Recommandation (Haute urgence)** : Créer un document `ANALYSE_RISQUES_CYBER.md` avec les scénarios STRIDE adaptés au contexte air-gap : Spoofing flux RTSP via caméra compromise (eth1), Tampering dataset lors d'une maintenance physique, DoS serveur d'inférence interne, Adversarial patch physique sur chariot, Compromission supply chain au build.

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
  *Révision 3 (24 juil. 2026)* : bases migrées vers `nvcr.io/nvidia/cuda:13.2.1-devel-ubuntu24.04` (builder) et `:13.2.1-runtime-ubuntu24.04` (finale) — JetPack 7.2 / L4T r39.2.0, toujours épinglées à un tag précis ✅. Ajout du dépôt apt `repo.download.nvidia.com/jetson` (r39.2, clé GPG NVIDIA) pour `nvidia-l4t-gstreamer`.
- `Dockerfile` L.33 : `curl -LsSf https://astral.sh/uv/install.sh | sh` — téléchargement **sans vérification de hash** ⚠️
  *Révision 3 (24 juil. 2026)* : résolu — `uv` est copié depuis l'image épinglée `ghcr.io/astral-sh/uv:0.11.16` (`COPY --from`), plus de `curl | sh` dans le `Dockerfile`.

**Lacunes :**
- ❌ `.gitlab-ci.yml` : pipeline uniquement `build` + `release` — aucun job Trivy, pip-audit, Safety, Dependabot.
- ❌ `.github/workflows/build-linux-executable.yml` : pipeline Nuitka — aucune analyse de sécurité.
- ❌ Aucun fichier SBOM (CycloneDX, SPDX) généré ou stocké.
- ❌ Dépôts d'inférence externes (`4itec-org/inf_jetson_rf-detr`, `4itec-org/inf_jetson_yolo`) non audités, référencés dans `README.md` sans mention de vérification.

**Recommandation (Moyenne urgence)** :
1. Ajouter dans `.gitlab-ci.yml` un job `security:scan` avec `trivy image` + `pip-audit`.
2. ~~Remplacer `curl | sh` par un téléchargement avec vérification de hash dans le `Dockerfile`.~~ ✅ Résolu (Révision 3) : `COPY --from` d'une image `uv` épinglée.

---

### Q4 — Bonnes pratiques DevSecOps · Score : 2/3

**Observable dans le dépôt (positif) :**
- `.env.example` : template avec instructions `chmod 600` — secrets externalisés ✅
- `.gitignore` : `.env` et `.env.*` explicitement exclus ✅
- `scripts/install_xrdp_jetson.sh` : `apt install -y ... ufw fail2ban` — UFW et Fail2ban installés et configurés ✅
- `README.md §VNC` : restriction du port 5999 au sous-réseau `192.168.3.0/24` ✅

**⚠️ Observable dans le dépôt — risque résiduel :**
- `README.md §eth2` : les identifiants du compte de maintenance étaient présents en clair dans le README.

  **Corrigé (2026-08-31)** : retirés du README et de l'historique git (`git filter-repo`), remplacés par un pointeur vers le coffre-fort 4itec (Vaultwarden), identifiants désormais uniques par boîtier. Voir `CYBER_AUDIT.md`, constat `CS-113-04`.

**Lacunes supplémentaires :**
- ❌ Aucun guide de référence explicite cité (OWASP, ANSSI, NIST SP 800-218).
- ❌ Aucun outil SAST (Bandit, Semgrep) dans les deux pipelines CI/CD.
- ❌ `Dockerfile` L.33 : `curl | sh` sans vérification (risque supply chain au moment du build).

**Recommandation (Faible urgence)** : Retirer le mot de passe du README lors de la prochaine intervention de maintenance. Priorité plus haute : ajouter `bandit` + `pip-audit` dans la CI/CD (supply chain).

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

### Q9 — Sécurisation des interactions et des API · Score : 3/3 ✅

**Observable dans le dépôt :**
- `app.py` ligne **1568** : `serve(app, host='0.0.0.0', port=5050)` — Flask sans authentification (confirmé par analyse des 20+ routes).
- `src/inference.py` : appels `POST /infer` et `POST /pose` vers `http://localhost:8001` et `http://localhost:8002` — HTTP en clair sur loopback (localhost uniquement).
- `src/bot_aiogram.py` : API Telegram via **HTTPS**, token lu depuis variable d'environnement ✅

**Évaluation dans le contexte de déploiement réel :**

L'absence d'authentification sur Flask serait critique dans un déploiement connecté. Dans le contexte documenté du projet :
- eth0 n'est **pas connecté** — aucun accès internet ou réseau d'entreprise
- eth1 dessert uniquement les **caméras IP** (équipements sans capacité TCP sortante)
- eth2 est un **câble point-à-point physique** — atteindre le port 5050 nécessite d'être physiquement branché sur le boîtier
- Les appels HTTP vers localhost (ports 8001/8002) ne quittent jamais la machine

➡️ **Flask sans authentification est acceptable dans ce contexte air-gap.** Un acteur qui peut brancher un câble sur le boîtier peut aussi l'ouvrir physiquement — l'authentification Flask n'apporterait pas de valeur de sécurité supplémentaire.

**Recommandation** : Aucune action requise sur ce point. Si le déploiement évolue vers un réseau partagé, réévaluer à ce moment.

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

## Points de vigilance prioritaires — contexte air-gap

### 🟠 PRIORITÉ #1 — Absence de conformité AI Act documentée
**Fichiers** : aucun fichier AI Act dans le dépôt  
Le système surveille des personnes et pilote des actionneurs physiques en milieu industriel → candidat probable **Haut Risque** (Annexe III §6). Aucune documentation technique Art. 11, aucune métrique de performance, aucune évaluation de conformité.  
**Action** : Consultation juridique + création `MODEL_PERFORMANCE.md` avec métriques mesurées.

### 🟠 PRIORITÉ #2 — Aucune analyse de vulnérabilités en CI/CD (supply chain)
**Fichiers** : `.gitlab-ci.yml`, `.github/workflows/build-linux-executable.yml`  
Le seul vecteur d'attaque distant réaliste dans ce déploiement est la **supply chain au moment du build**. Aucun des deux pipelines ne comprend de scan CVE ou d'analyse statique.  
**Action** : Ajouter un stage `security` avec `bandit` + `pip-audit` + corriger le `curl | sh` dans le `Dockerfile`.

### 🟡 PRIORITÉ #3 — Credentials VNC dans README (dépôt privé)
**Fichier** : `README.md` ligne 477  
Dépôt confirmé privé (HTTP 404). Accès VNC nécessite un câble physique. Risque limité aux collaborateurs avec accès repo.  
**Action** : Retirer lors de la prochaine intervention de maintenance — pas urgent.

---

## Feuille de route

### Phase 1 — Court terme (< 6 semaines) · Supply chain + CI/CD

- [x] Ajouter un stage `security` dans `.gitlab-ci.yml` (`bandit` + `pip-audit`) avant le stage `build`
- [x] Corriger `Dockerfile` L.33 : remplacer `curl | sh` par téléchargement `uv` avec vérification SHA256
- [x] Créer `ANALYSE_RISQUES_CYBER.md` avec scénarios STRIDE adaptés au contexte air-gap

### Phase 2 — Moyen terme (1-3 mois) · Conformité AI Act

- [ ] Consultation juridique : évaluation classification AI Act (Haut Risque probable Annexe III §6)
- [ ] Créer `MODEL_PERFORMANCE.md` avec métriques précision/rappel/F1 mesurées sur jeu de test
- [ ] Générer un SBOM (CycloneDX) dans la CI/CD
- [ ] Ajouter vérification SHA256 des poids modèles au démarrage systemd/Docker

### Phase 3 — Moyen terme (3-6 mois) · Intégrité dataset + robustesse

- [ ] Ajouter un manifeste d'intégrité `dataset/manifest.sha256` mis à jour à chaque capture
- [ ] Formaliser la validation humaine obligatoire avant tout réentraînement
- [ ] Tests de robustesse documentés (adversarial patch physique, occultation, variations lumière)
- [ ] Monitoring data drift (distribution scores de confiance)

### Phase 4 — Long terme (6-12 mois) · Documentation réglementaire

- [ ] Documentation technique AI Act Art. 11 si classification Haut Risque confirmée
- [ ] Retirer les credentials VNC du `README.md` L.477 lors d'une maintenance

> **Note** : L'authentification Flask (port 5050) et le TLS ne sont **pas dans la feuille de route** tant que le déploiement reste air-gappé avec accès physique uniquement. À réévaluer si l'architecture réseau évolue.

---

## Références

- [ANSSI — Maîtriser les risques liés aux systèmes d'IA](https://www.ssi.gouv.fr/guide/intelligence-artificielle-et-securite/)
- [OWASP ML Security Top 10](https://owasp.org/www-project-machine-learning-security-top-10/)
- [AI Act UE 2024/1689](https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32024R1689)
- [NIST AI RMF 1.0](https://airc.nist.gov/RMF_Overview)
- [IBM Adversarial Robustness Toolbox](https://github.com/Trusted-AI/adversarial-robustness-toolbox)
- [CycloneDX SBOM Specification](https://cyclonedx.org/)
