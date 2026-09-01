# Prompt : Audit de maturité cybersécurité — Projet 4iSafeCross
## (Réponses fondées exclusivement sur le code et la documentation du dépôt GitHub frankkubler/4iSafeCross)

---

Tu es un expert en cybersécurité spécialisé dans les systèmes d'intelligence artificielle industriels.
Tu dois évaluer la maturité cybersécurité du projet **4iSafeCross** en te basant **uniquement** sur les
éléments observables dans le dépôt GitHub (code source, fichiers de configuration, documentation,
CI/CD, Dockerfile, scripts). Tu ne dois **jamais supposer** ni extrapoler.

Si une pratique n'est pas visible dans le code ou la documentation, la réponse doit être :
> ❌ Non observable dans le dépôt — absence de preuve.

---

## CONTEXTE DU PROJET (extrait du dépôt)

- **Nom** : 4iSafeCross
- **Secteur** : Industrie / Sécurité physique en milieu logistique (entrepôts, chariots élévateurs)
- **Objectif** : Détecter la présence de piétons dans des zones de circulation de chariots élévateurs
  et déclencher des alertes physiques (relais Yoctopuce) et numériques (Telegram)
- **Modèles IA** : YOLO11m (détection d'objets) + YOLOv8-pose (estimation de pose COCO-17),
  avec mode `transfert` (modèle réentraîné sur site : classes `forklift`, `driver`, `person`)
- **Infrastructure** : Nvidia Jetson Orin NX (JetPack 7.2 / L4T r39.2), serveurs d'inférence HTTP dédiés
  (ports 8001/8002), Flask + Waitress, Docker, GitLab CI/CD
- **Données traitées** : Flux RTSP H.264 de caméras industrielles, captures annotées (piétons),
  base SQLite locale des événements, dataset d'entraînement collecté automatiquement
- **Stack** : Python 3.10, Flask, aiogram 3.x, OpenCV/GStreamer, SQLite, uv, systemd
- **Stade** : Production (déployé sur site industriel — site Chaunay mentionné dans la documentation)

---

## MISSION

Pour chacune des 10 questions de l'Annexe 4 (critères de maturité cybersécurité), tu dois :

1. **Analyser ce qui est observable** dans le dépôt : fichiers source, configuration, CI/CD,
   documentation (README, FAILSAFE_MODE.md, REGISTRE_TRAITEMENTS_RGPD.md, etc.)
2. **Citer précisément** le fichier et la section pertinente
3. **Attribuer un score de maturité** de 0 à 3 :
   - 0 = Aucune trace dans le dépôt
   - 1 = Conscience du sujet (documentation uniquement, aucune implémentation)
   - 2 = Implémentation partielle ou en cours
   - 3 = Traitement complet, documenté ET implémenté dans le code
4. **Identifier les lacunes** par rapport aux bonnes pratiques (ANSSI, OWASP, AI Act)
5. **Formuler une recommandation concrète et priorisée** (haute / moyenne / faible urgence)

---

## QUESTIONS D'AUTO-ÉVALUATION

### Q1 — Analyse des risques cybersécurité
**Question** : Le projet a-t-il mené une analyse des risques cyber ? Peut-il identifier les 2 risques majeurs ?

**Ce qui est observable dans le dépôt :**
- `REGISTRE_TRAITEMENTS_RGPD.md` : registre RGPD avec analyse des traitements de données vidéo
- `README.md §Mode fail-safe` : identification du risque de faux négatif → relais maintenus ON,
  watchdog heartbeat, timer minimum 11 s
- `src/inference.py`, `src/pose_analyser.py` : 3 filtres anti-faux-positifs en cascade
- Aucun document EBIOS RM, STRIDE, ISO 27005 ou analyse de menaces cyber formalisée dans le dépôt

**Analyse attendue de l'IA :**
- Identifier les risques cyber spécifiques : disponibilité du système, attaque du serveur
  d'inférence HTTP interne, compromission du bot Telegram, data poisoning du dataset
- Distinguer risques sécurité physique et risques cybersécurité
- Évaluer si le registre RGPD constitue une analyse de risques cyber au sens de l'AI Act

---

### Q2 — Conformité réglementaire (AI Act)
**Question** : Le projet connaît-il la réglementation applicable ? A-t-il identifié sa catégorie de risque AI Act ?

**Ce qui est observable dans le dépôt :**
- `REGISTRE_TRAITEMENTS_RGPD.md` : registre RGPD formel avec base légale, durée de conservation,
  mesures techniques
- Aucune mention de l'AI Act dans aucun fichier du dépôt
- Le système surveille des personnes physiques et pilote des actionneurs physiques (relais) →
  candidat probable à la catégorie **Haut risque** (AI Act, Annex III, §6 : safety components)
- Aucun fichier de conformité AI Act, AIPD ou documentation technique réglementaire présent

**Analyse attendue de l'IA :**
- Évaluer la classification AI Act probable (haut risque)
- Identifier l'absence de documentation réglementaire AI Act dans le dépôt
- Signaler les obligations associées (documentation technique, supervision humaine, métriques de précision)

---

### Q3 — Cartographie des composants tiers (SBOM)
**Question** : Le projet a-t-il cartographié ses composants logiciels et matériels tiers ?

**Ce qui est observable dans le dépôt :**
- `requirements.txt` : dépendances Python directes
- `uv.lock` : verrouillage complet des dépendances avec hachages SHA256
- `pyproject.toml` : dépendances directes déclarées
- `Dockerfile` : image de base et dépendances système via apt
- `.gitlab-ci.yml` : pipeline CI/CD sans scan de vulnérabilités (Trivy, pip-audit, Safety)
- `README.md` : serveurs d'inférence dans des dépôts externes non audités
  (`4itec-org/inf_jetson_rf-detr`, `4itec-org/inf_jetson_yolo`)
- Aucun fichier SBOM (CycloneDX, SPDX) généré

**Analyse attendue de l'IA :**
- Évaluer positivement le `uv.lock` avec hachages (traçabilité partielle)
- Signaler l'absence de SBOM formel et de scan CVE automatisé dans la CI/CD
- Identifier le risque lié aux dépôts d'inférence externes non audités

---

### Q4 — Bonnes pratiques de développement sécurisé (DevSecOps)
**Question** : Le projet applique-t-il des guides de développement sécurisé ? Lesquels ?

**Ce qui est observable dans le dépôt :**
- `README.md §Credentials sensibles` : token Telegram via variables d'environnement uniquement
- `.env.example` : template fourni avec instructions `chmod 600`
- `.gitignore` : `.env` explicitement exclu du dépôt
- `scripts/install_vnc_jetson.sh` : UFW (deny incoming), Fail2ban (jail VNC), anti-lockout SSH
- `README.md §VNC` : port VNC restreint au sous-réseau `192.168.3.0/24`, option Tailscale
- ⚠️ `README.md §eth2` : identifiants du compte de maintenance jadis en clair — **corrigé** (retirés du README et de l'historique, déplacés vers le coffre-fort 4itec)
- Aucun guide de référence explicite (OWASP, ANSSI, NIST SP 800-218) cité
- Aucune analyse statique de sécurité (Bandit, Semgrep) dans la CI/CD

**Analyse attendue de l'IA :**
- Valoriser la gestion des secrets et les mesures réseau (UFW, Fail2ban, Tailscale)
- Signaler comme **critique** les credentials VNC en clair dans README.md public
- Recommander l'ajout d'analyse statique de sécurité dans la CI/CD

---

### Q5 — Tests de sécurité automatisés
**Question** : Le projet a-t-il prévu des tests de sécurité automatisés ?

**Ce qui est observable dans le dépôt :**
- `test_detections_format.py` : tests unitaires sur le format des détections YOLO
- `test_zone_editor.py` : tests sur l'éditeur de zones
- `.gitlab-ci.yml` : pipeline axé build/déploiement, aucun job de sécurité visible
- `.github/` : dossier présent (contenu à vérifier dans les workflows GitHub Actions)
- Aucun outil de sécurité (Bandit, Safety, pip-audit, OWASP ZAP, Trivy) référencé

**Analyse attendue de l'IA :**
- Distinguer tests fonctionnels présents et tests de sécurité absents
- Recommander `bandit` + `pip-audit` dans la CI/CD comme première étape réaliste
- Signaler l'interface Flask exposée sans test de sécurité (endpoints `/api/masks`, `/zone_editor`)

---

### Q6 — Risques liés aux données d'entraînement
**Question** : Le projet a-t-il évalué les risques cyber liés aux données d'entraînement ?

**Ce qui est observable dans le dépôt :**
- `README.md §Collecte automatique de dataset` : `DatasetCollectionThread` intégré,
  4 stratégies (temporal, event, background, hard_negatives), collecte en production
- `src/collect_dataset.py` : labels = prédictions du modèle en production
  → risque de boucle de rétroaction (confirmation bias)
- `README.md §Flux de travail recommandé` : vérification manuelle via Label Studio préconisée
  mais non automatisée
- Aucune signature d'intégrité des images collectées, aucun anti-tampering du dataset
- `REGISTRE_TRAITEMENTS_RGPD.md` : collecte vidéo mentionnée, base légale documentée,
  mais aucune mesure technique de protection du dataset contre la manipulation

**Analyse attendue de l'IA :**
- Identifier le risque de data poisoning via le pipeline de collecte automatique
- Évaluer le risque RGPD lié aux images de personnes dans `dataset/`
- Recommander la séparation du pipeline de collecte et la validation humaine avant réentraînement

---

### Q7 — Explicabilité des modèles IA (XAI)
**Question** : Le projet prend-il en compte l'explicabilité de ses modèles IA ?

**Ce qui est observable dans le dépôt :**
- `README.md §Pipeline` : logique de décision documentée (3 filtres, seuils configurables)
- `README.md §Filtres` : justification du seuil 4 keypoints / 0.40 avec observation terrain
- `src/bot_aiogram.py` : image annotée (boîtes, zones, stature) envoyée à chaque alerte Telegram
- Logs détaillés : `Filtre keypoints bypassé`, `Faux positif écarté — pose=[] zones=[]`
- Aucun outil XAI (SHAP, LIME, Grad-CAM) intégré
- Aucune documentation sur les performances du modèle (précision, rappel, F1) dans le dépôt

**Analyse attendue de l'IA :**
- Valoriser la traçabilité des décisions via logs et images annotées
- Signaler l'absence de métriques documentées comme obstacle à la certification AI Act haut risque
- Recommander Grad-CAM ou visualisation des zones d'activation pour l'audit terrain

---

### Q8 — Protection des modèles IA (intégrité et confidentialité)
**Question** : Le projet prévoit-il des mesures pour protéger ses modèles IA ?

**Ce qui est observable dans le dépôt :**
- `CYTHON_README.md`, `setup_cython.py` : compilation Cython → obfuscation partielle du code
  (pas des poids du modèle)
- `.gitlab-ci-nuitka.yml` : compilation Nuitka en exécutable ARM64 autonome
- `README.md §inf_jetson` : serveurs d'inférence dans des conteneurs Docker dédiés —
  isolation architecturale
- Poids des modèles non stockés dans ce dépôt (dépôts séparés `4itec-org/`)
- Aucune signature des poids, aucun chiffrement des artefacts modèles, aucune vérification
  d'intégrité au chargement documentée

**Analyse attendue de l'IA :**
- Valoriser la séparation architecturale (modèles dans conteneurs dédiés)
- Identifier l'absence de vérification d'intégrité des poids au démarrage
- Recommander l'ajout d'un hash SHA256 des poids vérifiés au démarrage systemd

---

### Q9 — Sécurisation des interactions et des API
**Question** : Comment le projet sécurise-t-il les interactions entre modèles IA et applications ?

**Ce qui est observable dans le dépôt :**
- `app.py` : Flask sur port 5050 (`waitress-serve --host=0.0.0.0`), endpoints REST exposés :
  `/api/masks/<cam_id>`, `/zone_editor/<cam_id>`, `/api/zones/<cam_id>`, flux MJPEG, stats
- `src/inference.py` : appels `POST /infer` et `POST /pose` vers ports 8001/8002 — HTTP en clair
- `src/bot_aiogram.py` : API Telegram via HTTPS, token en variable d'environnement ✅
- Aucune authentification sur l'interface Flask (pas de login, JWT, clé API) visible dans le code
- Aucun HTTPS configuré (pas de TLS, pas de reverse proxy nginx/caddy)
- Port 5050 sans restriction UFW documentée (contrairement au port VNC 5999)

**Analyse attendue de l'IA :**
- Identifier comme **critique** : Flask sans authentification sur 0.0.0.0
- Signaler l'absence de TLS sur les communications internes HTTP
- Recommander : authentification Flask + restriction UFW du port 5050

---

### Q10 — Protection contre les attaques adversariales
**Question** : Le projet prévoit-il des mesures contre les adversarial attacks ?

**Ce qui est observable dans le dépôt :**
- `README.md §Filtres` : 3 filtres en cascade (défenses empiriques) :
  - Keypoints : résistance aux faux positifs sur métaux réfléchissants
  - Debounce temporel : résistance aux attaques frame-by-frame transitoires
  - Label driver : filtrage des conducteurs
- `README.md §Fail-safe` : philosophie "alerter en cas de doute" → protection contre la
  suppression de détection
- `src/motion.py` : MOG2 en pré-filtre → résistance partielle aux frames figées injectées
- Aucune référence aux adversarial attacks (FGSM, PGD, patch adversarial)
- Aucun outil de robustesse adversariale (ART/IBM, Foolbox, CleverHans) utilisé
- Aucun test de robustesse documenté, aucun monitoring de data drift en production

**Analyse attendue de l'IA :**
- Reconnaître les défenses empiriques sans les confondre avec une défense adversariale formalisée
- Identifier le risque d'adversarial patch physique (autocollant sur chariot) comme vecteur
  d'attaque réaliste dans ce contexte industriel
- Recommander des tests de robustesse (occlusion, variations lumière) et monitoring drift

---

## SYNTHÈSE ET RAPPORT FINAL

Génère un rapport structuré comprenant :

### 1. Tableau de scoring global

| Q | Thème | Score (0-3) | Éléments observés | Urgence |
|---|---|---|---|---|
| Q1 | Analyse des risques | ? | REGISTRE_TRAITEMENTS_RGPD.md, fail-safe | ? |
| Q2 | AI Act | ? | RGPD présent, AI Act absent | ? |
| Q3 | SBOM / composants | ? | uv.lock, pas de scan CVE | ? |
| Q4 | DevSecOps | ? | .env + UFW/Fail2ban, credentials en clair | ? |
| Q5 | Tests sécurité | ? | Tests fonctionnels, pas de SAST/DAST | ? |
| Q6 | Données entraînement | ? | Collecte auto, boucle rétroaction | ? |
| Q7 | Explicabilité XAI | ? | Logs, images annotées, pas de métriques | ? |
| Q8 | Protection modèles | ? | Conteneurs dédiés, pas de vérif intégrité | ? |
| Q9 | API / interactions | ? | Flask 0.0.0.0 sans auth, HTTP interne | ? |
| Q10 | Attaques adversariales | ? | Filtres empiriques, pas de test formel | ? |

**Niveaux de maturité :** 0-10 = Initiale (N1) | 11-20 = En développement (N2) |
21-27 = Avancée (N3) | 28-30 = Optimisée (N4)

### 2. Points forts (max 3, avec référence fichier)

### 3. Points de vigilance critiques (avec référence fichier)
⚠️ `README.md §eth2` : credentials VNC en clair — traitement immédiat requis.

### 4. Feuille de route

**Court terme (< 3 mois) :**
- [ ] Supprimer les credentials VNC du README
- [ ] Ajouter authentification sur Flask port 5050
- [ ] Intégrer `bandit` + `pip-audit` dans la CI/CD GitLab

**Moyen terme (3-12 mois) :**
- [ ] Générer un SBOM (CycloneDX) dans la CI/CD
- [ ] Documenter les métriques modèle pour la conformité AI Act
- [ ] Ajouter vérification SHA256 des poids au démarrage systemd
- [ ] Restreindre le port 5050 via UFW

### 5. Références utiles
- [ANSSI — Sécurité IA](https://www.ssi.gouv.fr/guide/intelligence-artificielle-et-securite/)
- [OWASP ML Security Top 10](https://owasp.org/www-project-machine-learning-security-top-10/)
- [AI Act UE 2024/1689](https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32024R1689)
- [NIST AI RMF](https://airc.nist.gov/RMF_Overview)
- [IBM Adversarial Robustness Toolbox](https://github.com/Trusted-AI/adversarial-robustness-toolbox)

---

**Règle impérative :**
> Chaque affirmation = référence exacte au fichier du dépôt.
> Absence de preuve → ❌ "Non observable dans le dépôt."
> Ne jamais supposer qu'une pratique est appliquée parce qu'elle est recommandée.
