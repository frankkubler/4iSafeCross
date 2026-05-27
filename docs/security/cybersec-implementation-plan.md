# Plan d'implémentation — Corrections cybersécurité 4iSafeCross

> Ce document découle du rapport `RAPPORT_CYBERSEC.md` (audit 26 mai 2026, révision 2 du 27 mai 2026).  
> **Contexte de déploiement** : Jetson Orin NX air-gappé, eth0 non connecté, eth2 = câble RJ45 direct point-à-point (accès physique requis). Dépôt GitHub **privé**.  
> L'authentification Flask et le TLS sur le port 5050 ne sont **pas des priorités** dans ce contexte — seuls un accès physique au boîtier permet d'atteindre ce port.  
> Chaque étape est indépendamment vérifiable. **Aucune modification de comportement fonctionnel.**

---

## Phase 1 — Court terme (< 6 semaines) · Supply chain CI/CD ← Priorité réelle #1

> **Pourquoi c'est la vraie priorité** : le seul vecteur d'attaque distant réaliste dans ce déploiement est la compromission de dépendances au moment du **build** (pas du runtime). La CI/CD est donc le seul point d'entrée non physique.

### Étape 1.1 — Ajouter un stage `security` dans `.gitlab-ci.yml` ✅ Complété

| | |
|---|---|
| **Fichier** | `.gitlab-ci.yml` |
| **Risque corrigé** | Absence de SAST/SCA en CI/CD — seul vecteur distant réaliste dans ce déploiement air-gap (Q5 — Haute urgence) |
| **Dépendances** | Aucune |

**Modification de `.gitlab-ci.yml`** :

```yaml
stages:
  - security   # ← ajouter avant build (fail fast)
  - build
  - release

# --- Analyse statique de sécurité (SAST) ---
security:sast:
  stage: security
  image: python:3.10-slim
  before_script:
    - pip install bandit pip-audit --quiet
  script:
    - echo "=== Analyse SAST avec Bandit ==="
    - bandit -r src/ utils/ app.py -ll -f json -o bandit-report.json || true
    - bandit -r src/ utils/ app.py -ll  # Affichage console
    - echo "=== Audit des dépendances avec pip-audit ==="
    - pip install -r requirements.txt --quiet
    - pip-audit --require-hashes -r requirements.txt -f json -o pip-audit-report.json || true
    - pip-audit -r requirements.txt  # Affichage console
  artifacts:
    when: always
    paths:
      - bandit-report.json
      - pip-audit-report.json
    expire_in: 30 days
  allow_failure: true  # Ne bloque pas le build dans un premier temps — passer à false après stabilisation
  only:
    - main
    - merge_requests
```

> **Note** : `allow_failure: true` permet une intégration progressive. Passer à `false` une fois les premiers résultats traités.

---

### Étape 1.2 — Corriger le Dockerfile (supply chain `uv`)

| | |
|---|---|
| **Fichier** | `Dockerfile` ligne 33 |
| **Risque corrigé** | Téléchargement `uv` sans vérification d'intégrité (Q3 — Moyenne urgence) |
| **Dépendances** | Aucune (parallèle avec 3.1) |

**Avant (ligne 33) :**
```dockerfile
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Après** (vérifier le hash sur https://github.com/astral-sh/uv/releases pour la version cible) :
```dockerfile
# Installer uv avec vérification d'intégrité
ARG UV_VERSION=0.11.16
RUN set -eux \
    && cd /tmp \
    && curl -LsSf \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz" \
        -o uv-aarch64-unknown-linux-gnu.tar.gz \
    && curl -LsSf \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz.sha256" \
        -o uv-aarch64-unknown-linux-gnu.tar.gz.sha256 \
    && sha256sum --check uv-aarch64-unknown-linux-gnu.tar.gz.sha256 \
    && mkdir -p /root/.local/bin \
    && tar -xzf uv-aarch64-unknown-linux-gnu.tar.gz -C /root/.local/bin --strip-components=1 \
    && rm uv-aarch64-unknown-linux-gnu.tar.gz uv-aarch64-unknown-linux-gnu.tar.gz.sha256
```

---

### Étape 1.3 — Créer `ANALYSE_RISQUES_CYBER.md` ✅ Complété

| | |
|---|---|
| **Fichier** | `ANALYSE_RISQUES_CYBER.md` (nouveau) |
| **Risque corrigé** | Absence d'analyse de menaces cyber formalisée (Q1 — Haute urgence) |
| **Dépendances** | Aucune |

Structure minimale à rédiger (5 scénarios STRIDE) :

| ID | Catégorie STRIDE | Composant ciblé | Impact | Mitigation existante | Mitigation manquante |
|---|---|---|---|---|---|
| R01 | Spoofing | Flux RTSP caméra | Injection de frames manipulées | MOG2 pré-filtre | Authentification RTSP, vérification intégrité flux |
| R02 | Tampering | Dataset `dataset/` | Data poisoning → réentraînement biaisé | Purge automatique RGPD | Signature SHA256 images, validation humaine obligatoire |
| R03 | Denial of Service | Serveur inférence HTTP (port 8001/8002) | Arrêt détection → fail-safe activé | Watchdog 30 s fail-safe | Rate limiting, authentification entre services |
| R04 | Elevation of Privilege | Interface Flask port 5050 | Modification zones, désactivation détection | Accès physique requis (câble RJ45 direct) ✅ | Aucune action requise sauf évolution architecture |
| R05 | Information Disclosure | Bot Telegram | Exfiltration captures vidéo si token compromis | Token en var d'env ✅ | Rotation périodique du token |

---

## Phase 2 — Moyen terme (1-3 mois) · Conformité AI Act + intégrité modèles

| Étape | Fichier(s) | Action |
|---|---|---|
| 2.1 | `.gitlab-ci.yml` | Ajouter génération SBOM CycloneDX : `cyclonedx-bom -o sbom.json` |
| 2.2 | `MODEL_PERFORMANCE.md` (nouveau) | Documenter métriques précision/rappel/F1 sur jeu de test représentatif |
| 2.3 | Script systemd (`scripts/`) | Vérification SHA256 des poids modèles au démarrage |
| 2.4 | — | Consultation juridique : classification AI Act (Haut Risque probable Annexe III §6) |
| 2.5 | `dataset/` | Ajouter manifeste `dataset/manifest.sha256` mis à jour à chaque capture automatique |

---

## Phase 3 — Long terme (6-12 mois)

| Étape | Action |
|---|---|
| 3.1 | Retirer les credentials VNC du `README.md` L.477 lors d'une maintenance (hygiène git) |
| 3.2 | Monitoring data drift (distribution scores de confiance) — alerter si dérive > ±20 % |
| 3.3 | Tests de robustesse documentés (adversarial patch physique, occultation partielle, variations lumière) |
| 3.4 | Documentation technique AI Act Art. 11 si classification Haut Risque confirmée |

> **Note** : L'authentification Flask (port 5050) et le reverse proxy TLS ne sont **pas dans cette feuille de route** tant que le déploiement reste air-gappé avec accès physique uniquement. À réévaluer si l'architecture réseau évolue.

---

## Checklist de validation finale

```bash
# Phase 1 — CI/CD supply chain
cat .gitlab-ci.yml | grep "stages" -A5                 # → stage security présent
cat Dockerfile | grep "sha256sum"                       # → vérification présente
ls ANALYSE_RISQUES_CYBER.md && echo OK                  # → document STRIDE présent

# Phase 2 — AI Act + intégrité modèles
ls dataset/manifest.sha256 2>/dev/null && echo OK       # → manifeste présent
pip show cyclonedx-bom                                  # → installé

# Phase 3 — Long terme
grep -n "***REMOVED-PASSWORD***" README.md                          # → 0 résultat (après maintenance)
```

> **Note** : Les vérifications `curl -o /dev/null -w "%{http_code}" http://jetson:5050/zone_editor/0` attendant un 401 ont été **retirées** — Flask sans authentification est acceptable dans ce contexte air-gap (accès physique requis sur eth2).
