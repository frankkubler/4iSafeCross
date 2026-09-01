# Plan d'implémentation — Corrections cybersécurité 4iSafeCross

> ⚠️ **Partiellement supersédé par l'audit fournisseur Stellantis (`CYBER_AUDIT.md`).**
> Les positions ci-dessous sur l'authentification Flask et le TLS du port 5050
> (« pas des priorités », checks 401 retirés) **ne s'appliquent plus** :
> - TLS de l'IHM : **fait** (rév. 8) — `waitress` sur `127.0.0.1` + reverse-proxy Caddy sur `eth2` (`CS-1143-01`, `CS-143-02`) ;
> - Authentification : **obligatoire** (rév. 10) — l'application refuse de démarrer sans `SAFECROSS_AUTH_*` (`CS-1144-01`). Le contrôle de recette FOR_509 teste l'endpoint HTTP directement (401 attendu) et l'air-gap n'y déroge pas.
> - **Plan réseau** (rév. 13) : « eth2 = maintenance » ci-dessous vaut pour le **site HAM**. Nouvelles installations = maintenance sur `eth1`, caméras sur `eth2`/`eth3`/`eth4` (`192.168.0.0/24`) — `README.md`, `docs/compliance/cartographie-flux-stellantis.md`.

> Ce document découle du rapport `RAPPORT_CYBERSEC.md` (audit 26 mai 2026, révision 2 du 27 mai 2026).  
> **Contexte de déploiement** : Jetson Orin NX air-gappé, eth0 non connecté, port de maintenance = câble RJ45 direct point-à-point (accès physique requis). Dépôt GitHub **privé**.  
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
| R04 | Elevation of Privilege | Interface Flask port 5050 | Modification zones, désactivation détection | TLS Caddy sur `eth2` + `waitress` sur `127.0.0.1` (rév. 8) ; **authentification HTTP Basic obligatoire** (rév. 10, `CS-1144-01`) ; UFW `443` restreint à `192.168.3.0/24` | Journal d'audit des écritures + rejets 401 (`CS-144-01`) ; séparation rôles Opérateur/Admin (`CS-113-02`) |
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

> ~~**Note** : L'authentification Flask (port 5050) et le reverse proxy TLS ne sont pas dans cette feuille de route…~~ **Supersédé** (`CYBER_AUDIT.md` rév. 8 et 10) : reverse-proxy TLS Caddy en place, authentification HTTP Basic **obligatoire** (refus de démarrage sans `SAFECROSS_AUTH_*`). Voir `CS-1143-01`, `CS-143-02`, `CS-1144-01`.

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
grep -nE "mdp *:|user-4itec.*/ *mdp" README.md         # → 0 résultat (identifiants retirés)
```

> ~~**Note** : Les vérifications `curl … http://jetson:5050/zone_editor/0` attendant un 401 ont été retirées — Flask sans authentification est acceptable dans ce contexte air-gap.~~
> **Supersédé (`CS-1144-01`, rév. 10)** : l'authentification est obligatoire. Contrôle de recette à rétablir — l'IHM répond en HTTPS via Caddy (`eth2`), `waitress` n'écoute plus que sur `127.0.0.1` :
> ```sh
> curl -k -o /dev/null -w "%{http_code}\n" https://192.168.3.122/zone_editor/0   # → 401
> curl -k -o /dev/null -w "%{http_code}\n" -u "$USER:$PWD" https://192.168.3.122/zone_editor/0   # → 200
> ```
