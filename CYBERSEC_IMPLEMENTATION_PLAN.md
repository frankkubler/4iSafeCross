# Plan d'implémentation — Corrections cybersécurité 4iSafeCross

> Ce document découle du rapport `RAPPORT_CYBERSEC.md` (audit du 26 mai 2026).  
> Chaque étape est indépendamment vérifiable. Les phases sont ordonnées par criticité.  
> **Aucune modification de comportement fonctionnel** — uniquement des ajouts de sécurité.

---

## Phase 1 — Immédiat (< 24 h) · Sans risque de régression

### Étape 1.1 — Supprimer les credentials VNC du README

| | |
|---|---|
| **Fichier** | `README.md` ligne 477 |
| **Risque corrigé** | Credentials VNC en clair dans un dépôt public (Q4 — Critique) |
| **Dépendances** | Aucune |

**Avant :**
```markdown
- **eth2** est réservé pour la connexion VNC de maintenance (port 5999), avec l'adresse IP 192.168.3.122. (masque 255.255.255.0) user : user-4itec / mdp : ***REMOVED-PASSWORD***
```

**Après :**
```markdown
- **eth2** est réservé pour la connexion VNC de maintenance (port 5999), avec l'adresse IP 192.168.3.122. (masque 255.255.255.0) — Credentials disponibles dans le gestionnaire de mots de passe interne 4iTec.
```

**Action système requise (hors dépôt) :**
```bash
# Sur le Jetson de production — à exécuter manuellement
passwd user-4itec
# Saisir un nouveau mot de passe fort (≥ 16 caractères, alphanumérique + symboles)
```

**Vérification :**
```bash
grep -n "***REMOVED-PASSWORD***" README.md
# → Aucun résultat attendu
```

---

### Étape 1.2 — Restreindre le port 5050 via UFW

| | |
|---|---|
| **Fichier** | `scripts/install_xrdp_jetson.sh` |
| **Risque corrigé** | Port Flask 5050 accessible sans restriction réseau (Q9 — Critique) |
| **Dépendances** | Aucune (parallèle avec 1.1) |

**Modification à apporter dans `install_xrdp_jetson.sh`**, après le bloc de règles UFW existant pour le port VNC :

```bash
# Restreindre l'interface Flask au sous-réseau de maintenance
ufw allow from "${MAINTENANCE_SUBNET}" to any port 5050 comment "Flask 4iSafeCross - maintenance uniquement"
ufw deny 5050 comment "Flask 4iSafeCross - refus global"
```

**Vérification (sur le Jetson après ré-exécution du script) :**
```bash
ufw status verbose | grep 5050
# → Attendu : allow from 192.168.3.0/24 to any port 5050
# → Attendu : deny 5050
```

---

## Phase 2 — Court terme (< 2 semaines) · Authentification Flask

### Étape 2.1 — Ajouter `flask-httpauth` aux dépendances

| | |
|---|---|
| **Fichier** | `pyproject.toml` |
| **Dépendances** | Aucune (avant 2.2) |

**Modification à apporter dans `pyproject.toml`**, dans le bloc `dependencies` :

```toml
"flask-httpauth>=4.8.0",
```

Mettre à jour le lockfile :
```bash
uv lock
```

---

### Étape 2.2 — Créer le module d'authentification

| | |
|---|---|
| **Fichier** | `utils/auth.py` (nouveau fichier) |
| **Dépendances** | Étape 2.1 |

```python
"""
utils/auth.py — Authentification HTTP Basic pour l'interface Flask.

Le mot de passe est lu depuis la variable d'environnement FLASK_PASSWORD.
Ne jamais hardcoder de credentials dans ce fichier.
"""
import os
import hmac
from flask_httpauth import HTTPBasicAuth

auth = HTTPBasicAuth()

FLASK_USER = os.environ.get("FLASK_USER", "admin")
FLASK_PASSWORD = os.environ.get("FLASK_PASSWORD", "")

if not FLASK_PASSWORD:
    import logging
    logging.getLogger(__name__).warning(
        "⚠️  FLASK_PASSWORD non défini — interface web non protégée. "
        "Définir FLASK_PASSWORD dans le fichier .env."
    )


@auth.verify_password
def verify_password(username: str, password: str) -> bool:
    """Vérifie les credentials en temps constant (résistance au timing attack)."""
    user_ok = hmac.compare_digest(username.encode(), FLASK_USER.encode())
    pass_ok = hmac.compare_digest(password.encode(), FLASK_PASSWORD.encode())
    return user_ok and pass_ok and bool(FLASK_PASSWORD)
```

---

### Étape 2.3 — Protéger les endpoints sensibles dans `app.py`

| | |
|---|---|
| **Fichier** | `app.py` |
| **Dépendances** | Étape 2.2 |

**Import à ajouter** en tête de `app.py` :
```python
from utils.auth import auth
```

**Décorateur `@auth.login_required` à ajouter sur les routes suivantes** (écriture/contrôle d'état) :

| Route | Ligne approx. | Justification |
|---|---|---|
| `POST /api/zones/<cam_id>` | ~1140 | Modification des zones de détection |
| `POST /api/masks/<cam_id>` | ~1160 | Modification des masques d'exclusion |
| `POST /set_motion_param/<int:cid>` | ~977 | Modification des paramètres MOG2 |
| `POST /set_control/<int:cid>` | ~1047 | Contrôle général caméra |
| `POST /toggle_detection/<int:cid>` | ~1063 | Activation/désactivation détection |
| `POST /toggle_stream/<int:cid>` | ~1090 | Activation/désactivation stream |
| `GET /zone_editor/<cam_id>` | ~1200 | Interface éditeur de zones |
| `POST /toggle_telegram_alert` | ~1117 | Activation/désactivation alertes |

Routes **exemptées** (lecture seule, nécessaires au monitoring) :
- `GET /` — tableau de bord
- `GET /video_feed/<cid>` — flux vidéo (peut être protégé si requis)
- `GET /failsafe_status` — monitoring watchdog

Exemple d'application :
```python
@app.route('/api/zones/<cam_id>', methods=['POST'])
@auth.login_required   # ← ajouter cette ligne
def save_zones(cam_id):
    ...
```

---

### Étape 2.4 — Ajouter `FLASK_PASSWORD` dans `.env.example`

| | |
|---|---|
| **Fichier** | `.env.example` |
| **Dépendances** | Étape 2.2 |

**Ajout à la fin du fichier `.env.example`** :
```bash
# Authentification interface web Flask (port 5050)
FLASK_USER=admin
FLASK_PASSWORD=<mot_de_passe_interface_web_fort>
```

**Vérification d'ensemble (Phase 2) :**
```bash
# Depuis un hôte du réseau local, sans credentials
curl -s -o /dev/null -w "%{http_code}" http://192.168.3.122:5050/zone_editor/0
# → Attendu : 401

# Avec credentials corrects
curl -u admin:mon_mdp http://192.168.3.122:5050/zone_editor/0
# → Attendu : 200
```

---

## Phase 3 — Court terme (< 6 semaines) · CI/CD sécurisé

### Étape 3.1 — Ajouter un stage `security` dans `.gitlab-ci.yml`

| | |
|---|---|
| **Fichier** | `.gitlab-ci.yml` |
| **Risque corrigé** | Absence de SAST/SCA en CI/CD (Q5 — Haute urgence) |
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

### Étape 3.2 — Corriger le Dockerfile (supply chain `uv`)

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
ARG UV_VERSION=0.6.14
RUN curl -LsSf "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz" \
      -o /tmp/uv.tar.gz \
    && curl -LsSf "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz.sha256" \
      -o /tmp/uv.tar.gz.sha256 \
    && sha256sum -c /tmp/uv.tar.gz.sha256 \
    && tar -xzf /tmp/uv.tar.gz -C /root/.local/bin --strip-components=1 \
    && rm /tmp/uv.tar.gz /tmp/uv.tar.gz.sha256
```

---

### Étape 3.3 — Créer `ANALYSE_RISQUES_CYBER.md`

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
| R04 | Elevation of Privilege | Interface Flask port 5050 | Modification zones, désactivation détection | UFW subnet (Phase 1) | Authentification HTTP Basic (Phase 2) |
| R05 | Information Disclosure | Bot Telegram | Exfiltration captures vidéo si token compromis | Token en var d'env ✅ | Rotation périodique du token, restriction IP Telegram |

---

## Phase 4 — Moyen terme (3-6 mois)

| Étape | Fichier(s) | Action |
|---|---|---|
| 4.1 | `.gitlab-ci.yml` | Ajouter génération SBOM CycloneDX : `cyclonedx-bom -o sbom.json` |
| 4.2 | `MODEL_PERFORMANCE.md` (nouveau) | Documenter métriques précision/rappel/F1 sur jeu de test représentatif |
| 4.3 | Script systemd (`scripts/`) | Vérification SHA256 des poids modèles au démarrage |
| 4.4 | — | Consultation juridique : classification AI Act (Haut Risque probable) |

---

## Phase 5 — Long terme (6-12 mois)

| Étape | Action |
|---|---|
| 5.1 | Reverse proxy Caddy avec TLS automatique devant le port 5050 |
| 5.2 | Monitoring data drift (distribution scores de confiance) — alerter si dérive > ±20 % |
| 5.3 | Tests de robustesse documentés (adversarial patch, occultation partielle, variations lumière) |
| 5.4 | Documentation technique AI Act Art. 11 si classification Haut Risque confirmée |

---

## Checklist de validation finale

```bash
# Phase 1
grep -n "***REMOVED-PASSWORD***" README.md                          # → 0 résultat
grep -n "5050" scripts/install_xrdp_jetson.sh          # → règle UFW présente

# Phase 2
curl -s -o /dev/null -w "%{http_code}" http://jetson:5050/zone_editor/0
# → 401
pip show flask-httpauth                                 # → installé

# Phase 3
cat .gitlab-ci.yml | grep "stages" -A5                 # → stage security présent
cat Dockerfile | grep "sha256sum"                       # → vérification présente
```
