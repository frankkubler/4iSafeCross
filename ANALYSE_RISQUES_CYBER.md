# Analyse des risques cybersécurité — 4iSafeCross

> **Projet** : 4iSafeCross — Détection piétons en zone chariot élévateur  
> **Méthode** : STRIDE (Microsoft Threat Modeling)  
> **Date** : 27 mai 2026  
> **Version** : 1.0  
> **Auteur** : Équipe 4iTec  
> **Contexte** : Ce document découle du rapport `RAPPORT_CYBERSEC.md` (audit 26 mai 2026, révision 2).

---

## 1. Hypothèses de déploiement (air-gap)

Le déploiement physique élimine structurellement la majorité des vecteurs d'attaque réseau classiques.

| Interface | État | Conséquence sur les menaces |
|---|---|---|
| `eth0` | Non connectée | Aucun accès internet entrant ou sortant |
| `eth1` | Sous-réseau caméras `192.168.2.x` | Seuls les équipements caméras dédiés, sans TCP sortant |
| `eth2` | Câble RJ45 **direct** point-à-point vers PC maintenance `192.168.3.122/24` | Accès Flask 5050 uniquement par connexion physique au boîtier |
| `eth3/eth4` | Non utilisées | — |

**Conséquence** : un attaquant doit disposer d'un **accès physique au site** (entrepôt logistique sécurisé) pour atteindre n'importe quelle interface réseau du système. Les menaces réseau distantes sont **structurellement éliminées**.

---

## 2. Actifs protégés

| ID | Actif | Localisation | Valeur métier | Confidentialité | Intégrité | Disponibilité |
|---|---|---|---|---|---|---|
| A01 | Poids modèle YOLO11m | `*.pt` dans le conteneur | Cœur de la détection piéton | Faible | **Critique** | Élevée |
| A02 | Dataset images | `dataset/` | Entraînement futur, traçabilité | Élevée (RGPD) | **Critique** | Moyenne |
| A03 | Configuration zones/masks | SQLite + JSON via API | Paramétrage opérationnel des zones dangereuses | Moyenne | **Critique** | Élevée |
| A04 | Token Telegram | Variable d'environnement `.env` | Déclenchement alertes opérateurs | Élevée | Élevée | Moyenne |
| A05 | Relais Yoctopuce (sorties physiques) | Matériel USB sur Jetson | Arrêt/activation barrière physique chariot | Faible | **Critique** | **Critique** |
| A06 | Captures `/detections/` | Système de fichiers local | Traçabilité RGPD, preuves incidents | Élevée (RGPD) | Moyenne | Faible |

---

## 3. Surface d'attaque

### Ports et interfaces exposés

| Port | Service | Liaison réseau | Accessible depuis |
|---|---|---|---|
| **5050** | Flask/Waitress (32 routes) | `0.0.0.0` | Uniquement eth2 (câble RJ45 direct) |
| **8001** | Serveur inférence YOLO | `localhost` | Uniquement processus locaux (interne Docker) |
| **8002** | Serveur inférence RF-DETR | `localhost` | Uniquement processus locaux (interne Docker) |

### Routes Flask à surface critique (app.py)

| Route | Méthode | Impact si compromise |
|---|---|---|
| `/set_zones` | POST | Désactivation silencieuse des zones dangereuses |
| `/toggle_detection/<cid>` | POST | Arrêt de la détection piéton |
| `/shutdown` | GET | Arrêt complet du système |
| `/quit` | POST | Arrêt complet du système |
| `/api/zones/<cid>` | POST | Modification des polygones de détection |
| `/api/relay_positions/<cid>` | POST | Modification des positions déclenchant le relais |
| `/detections/<filename>` | GET | Accès aux captures RGPD |

---

## 4. Scénarios STRIDE

> **Légende** :  
> **Probabilité** : TF = Très Faible · F = Faible · M = Moyenne  
> **Impact** : F = Faible · M = Moyen · É = Élevé  
> **Score brut** : Probabilité × Impact (TF=1, F=2, M=3) × (F=1, M=2, É=3)  
> **Traitement** : ✅ Accepté (≤2) · ⚠️ Surveillé (3-4) · 🔴 Traité (≥5)

### Spoofing — Usurpation d'identité

| ID | Composant | Scénario | Prob. | Impact | Score | Mitig. existante | Mitig. manquante | Traitement |
|---|---|---|---|---|---|---|---|---|
| R01 | Flux RTSP caméra (eth1) | Une caméra IP compromise injecte des frames manipulées (aucun piéton visible) pour masquer une intrusion en zone dangereuse. | F | É | **6** | Filtre MOG2 détecte les anomalies statistiques de mouvement ; watchdog fail-safe 30 s | Authentification RTSP (`rtsp://user:pass@...`), vérification hash frame périodique | 🔴 Traité — Phase 3 |
| R06 | Requêtes HTTP Flask port 5050 | Via câble RJ45 physique, un technicien envoie des requêtes forgées à `/toggle_detection` ou `/set_zones` pour désactiver la détection. | TF | É | **3** | Accès physique requis (câble RJ45 direct, site sécurisé) ✅ | Journalisation horodatée des actions admin (voir R09) | ⚠️ Surveillé |

### Tampering — Altération de données

| ID | Composant | Scénario | Prob. | Impact | Score | Mitig. existante | Mitig. manquante | Traitement |
|---|---|---|---|---|---|---|---|---|
| R02 | Dataset `dataset/` | Un opérateur malveillant ou un technicien de maintenance injecte physiquement des images biaisant le prochain réentraînement (data poisoning). | F | É | **6** | Purge automatique RGPD (30 jours) | Manifeste `dataset/manifest.sha256`, validation humaine obligatoire avant réentraînement | 🔴 Traité — Phase 3 |
| R07 | Poids modèle `*.pt` | Remplacement du fichier de poids lors d'une maintenance physique → modèle biaisé ne détectant plus certains piétons. | TF | É | **3** | Modèle embarqué dans le conteneur Docker immuable | Vérification SHA256 des poids au démarrage (`systemd` / Docker `HEALTHCHECK`) | ⚠️ Surveillé — Phase 2 |
| R08 | Zones/masks via `/set_zones` | Modification silencieuse des polygones de zones dangereuses via l'UI ou l'API, sans journal d'audit permettant de détecter la modification. | F | É | **6** | Zones stockées en DB SQLite (persistance) | Journalisation horodatée des modifications de zones, hash des zones actives | 🔴 Traité — Phase 3 |

### Repudiation — Non-répudiation

| ID | Composant | Scénario | Prob. | Impact | Score | Mitig. existante | Mitig. manquante | Traitement |
|---|---|---|---|---|---|---|---|---|
| R09 | Actions admin Flask | Les routes `/shutdown`, `/quit`, `/toggle_detection`, `/set_zones` n'enregistrent pas qui a fait quelle action ni quand → impossible d'auditer après incident. | F | F | **2** | Logs systemd horodatés (stderr/stdout du processus) présents partiellement | Middleware Flask loggant IP source + action + horodatage sur les routes critiques | ✅ Accepté — hygiène à améliorer |

### Information Disclosure — Divulgation d'informations

| ID | Composant | Scénario | Prob. | Impact | Score | Mitig. existante | Mitig. manquante | Traitement |
|---|---|---|---|---|---|---|---|---|
| R05 | Token Telegram (`.env`) | Le token du bot Telegram est exfiltré (copie du fichier `.env`, accès physique au stockage). Un attaquant peut envoyer de faux messages ou récupérer les captures RGPD envoyées par le bot. | F | M | **4** | Token en variable d'environnement (non hardcodé dans le code) ✅ | Rotation périodique du token, restriction IP du bot Telegram si API supporte | ⚠️ Surveillé |
| R10 | Route `/detections/<filename>` | Les captures RGPD stockées dans `/detections/` sont accessibles via HTTP sans authentification depuis eth2 (câble direct). | TF | M | **2** | Accès physique requis (câble RJ45) ; les captures sont purgées sous 30 jours | Aucune action requise tant que déploiement reste air-gappé | ✅ Accepté |

### Denial of Service — Déni de service

| ID | Composant | Scénario | Prob. | Impact | Score | Mitig. existante | Mitig. manquante | Traitement |
|---|---|---|---|---|---|---|---|---|
| R03 | Serveur inférence port 8001/8002 | Un processus local consomme toute la mémoire ou le CPU GPU → le serveur d'inférence crashe, plus de détection. | F | É | **6** | **Watchdog fail-safe 30 s** : si l'inférence ne répond plus, le système passe en mode fail-safe (relais activé = barrière) ✅ | Rate limiting inter-services, redémarrage automatique `restart: always` dans docker-compose | 🔴 Traité — Phase 1 (fail-safe existant atténue) |
| R11 | Espace disque `/detections/` | Saturation du stockage par accumulation de captures (purge RGPD défaillante ou volume de détections anormalement élevé) → crash du système d'exploitation. | M | É | **9** | Purge automatique RGPD 30 jours | Monitoring espace disque + alerte Telegram si < 500 MB ; limite max `/detections/` par quota Docker | 🔴 Traité — Phase 2 |

### Elevation of Privilege — Élévation de privilèges

| ID | Composant | Scénario | Prob. | Impact | Score | Mitig. existante | Mitig. manquante | Traitement |
|---|---|---|---|---|---|---|---|---|
| R04 | Interface Flask port 5050 | Via eth2, un technicien accède aux routes d'administration (modification zones, désactivation détection, arrêt système) sans authentification. | TF | É | **3** | **Accès physique requis (câble RJ45 direct)** — pas de réseau partagé ✅ | Aucune action requise sauf évolution de l'architecture réseau | ⚠️ Surveillé — réévaluer si architecture évolue |
| R12 | Conteneur Docker (runtime) | Le conteneur tourne sans `--cap-drop=ALL` ni `--security-opt no-new-privileges` → un exploit applicatif peut élever au niveau du host Jetson. | TF | É | **3** | Conteneur lancé sans `--privileged` | `--cap-drop=ALL --cap-add=SYS_RAWIO` (pour Yoctopuce USB) + `--security-opt no-new-privileges` | ⚠️ Surveillé — Phase 3 |

---

## 5. Matrice de risque

```
                      IMPACT
                  Faible    Moyen    Élevé
               ┌─────────┬─────────┬──────────┐
  Très faible  │ ✅ R06†  │ ✅ R10  │ ⚠️ R04  │
               │          │         │  R07 R12 │
  P ─ ─ ─ ─ ─ ├─────────┼─────────┼──────────┤
  R  Faible    │ ✅ R09   │ ⚠️ R05  │ 🔴 R01  │
  O            │          │         │  R02 R03 │
  B            │          │         │  R08     │
  A ─ ─ ─ ─ ─ ├─────────┼─────────┼──────────┤
     Moyenne   │          │         │ 🔴 R11   │
               └─────────┴─────────┴──────────┘
```

> † R06 est "Très faible × Élevé" = score 3, classé ⚠️ Surveillé malgré la cellule TF×É.

### Synthèse par priorité

| Priorité | Scénarios | Action |
|---|---|---|
| 🔴 Traité (score ≥ 5) | R01, R02, R08, R11 + R03 (fail-safe existant) | Planifier dans la phase en cours |
| ⚠️ Surveillé (score 3-4) | R04, R05, R06, R07, R12 | Monitoring + action planifiée |
| ✅ Accepté (score ≤ 2) | R09, R10 | Aucune action immédiate |

---

## 6. Plan de traitement (synthèse)

| ID | Scénario | Phase | Action retenue |
|---|---|---|---|
| R11 | Saturation espace disque | Phase 2 | Monitoring disque + alerte Telegram + quota `/detections/` |
| R01 | Spoofing RTSP caméra | Phase 3 | Authentification RTSP sur caméras ; documenter dans `MODEL_PERFORMANCE.md` |
| R02 | Data poisoning dataset | Phase 3 | Manifeste `dataset/manifest.sha256` + validation humaine réentraînement |
| R08 | Modification zones sans audit | Phase 3 | Log horodaté sur routes `/set_zones`, `/api/zones`, `/api/masks` |
| R03 | DoS inférence | Existant | Watchdog fail-safe 30 s ✅ ; ajouter `restart: always` docker-compose |
| R07 | Remplacement poids modèle | Phase 2 | SHA256 poids au démarrage (systemd ou HEALTHCHECK Docker) |
| R05 | Token Telegram exfiltré | Phase 3 | Rotation périodique du token dans `.env` |
| R04 | Flask sans auth (port 5050) | Architecture | Acceptable en air-gap ; réévaluer si eth2 évolue vers réseau partagé |
| R06 | Requêtes forgées Flask | Phase 3 | Journalisation IP + action sur routes critiques |
| R12 | Élévation privilèges Docker | Phase 3 | `--cap-drop=ALL` + `--cap-add=SYS_RAWIO` dans `docker-compose.yml` |
| R09 | Repudiation actions admin | Phase 3 | Middleware logging Flask (IP + route + horodatage) |
| R10 | Captures accessibles HTTP | Accepté | Accès physique requis ✅ ; réévaluer si architecture évolue |

---

## 7. Hors périmètre (menaces structurellement éliminées)

Les menaces suivantes sont **éliminées par l'architecture air-gap** et ne nécessitent aucune mitigation applicative :

| Menace | Raison de l'élimination |
|---|---|
| Attaque distante depuis internet | eth0 non connectée |
| Scan de ports / exploitation CVE distante | Aucun accès réseau sans câble physique |
| Brute force authentification HTTP | Port 5050 accessible uniquement par câble RJ45 direct |
| Interception TLS (MITM) | Pas de trafic réseau partagé |
| Exfiltration données via réseau | Pas de connexion sortante |
| Accès employé réseau usine | Pas de réseau usine connecté |

> **Note de révision** : Ce document doit être mis à jour si l'architecture réseau évolue (ajout VPN, connexion LAN usine, accès distant, etc.). Toute connexion de eth0 invalide les hypothèses de la Section 1 et reclasse plusieurs scénarios Acceptés → Traités.
