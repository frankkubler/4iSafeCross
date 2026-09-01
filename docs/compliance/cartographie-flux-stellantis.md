# Cartographie des flux — modèle Stellantis (STLA-CS_STD_004 §1.4.3)

> **Exigence** : `CS-143-01` — fournir la cartographie des flux au modèle
> Stellantis, en **deux livrables** : un fichier **IT ↔ OT** et un fichier
> **OT ↔ OT**. Voir `CYBER_AUDIT.md` (les constats et l'état de correction par
> flux y sont détaillés).
>
> Ce document est la version **rédigée et à jour** de la cartographie. Si le
> référent technique impose un gabarit tableur officiel (STLA-CS_FOR_317 /
> matrice de flux), transcrire les deux tableaux ci-dessous tels quels — les
> colonnes sont alignées sur ce gabarit.

- **Équipement** : appliance de vision 4iSafeCross — Nvidia Jetson Orin NX (reServer Industrial J4012)
- **Modèle de déploiement** : autonome, **sans Internet** en exploitation (RUN) ; clé 4G **provisoire** en mise au point sur site (déclarée au Plant IT Leader)
- **Date** : 2026-09-01 · **Révision** : 11 (suit `CYBER_AUDIT.md`)
- **État** : rédigé côté fournisseur — **à valider par le référent technique Stellantis** (bloc de validation en fin de document)

---

## 1. Zones et conduits

| Zone / conduit | Contenu | Adressage | Remarque |
|---|---|---|---|
| **Zone 0 — Internet** | — | — | **RUN : non raccordé.** Présente uniquement en mise au point, via clé 4G temporaire (fenêtre déclarée PIL — `CS-145-xx`) |
| **Zone 1 — IT fournisseur** | PC de maintenance 4itec, poste 4itec de mise au point, machine relais de MAJ | variable | Dans le périmètre **STLA-CS_FOR_502** (`CS-15-xx`) |
| **Conduit IT↔OT (RUN)** | Câble RJ45 **point-à-point** `eth2` + pare-feu hôte UFW | `192.168.3.0/24` | Accès physique requis. `default deny incoming`, ports ouverts au seul `192.168.3.0/24` |
| **Conduit IT↔OT (mise au point)** | Clé **4G** USB — temporaire | CGNAT opérateur | Retirée à la livraison, retrait attesté à la recette |
| **Zone 2 — OT Supervision** | Services d'accès du boîtier : Caddy (443), TigerVNC (5999), SSH (22) ; IHM Flask | `192.168.3.122` (eth2) | Pare-feu hôte + fail2ban |
| **Zone 3 — OT Process / Terrain** | Sous-réseau caméras `eth1` ; module relais Yoctopuce (USB) | `192.168.2.0/24` (eth1) | Sous-réseau caméras **dédié et isolé** |
| **Intra-hôte (loopback)** | Flux `127.0.0.1` sur le Jetson (Caddy→waitress, client d'inférence→serveurs YOLO/RF-DETR) | `127.0.0.1` | Comptés OT↔OT ; **ne traversent aucun média réseau** |

### Schéma

```
   ZONE 0 ── Internet ──  RUN : NON raccordé
   (Internet)             mise au point : clé 4G (temporaire, déclarée PIL)
                                 │  IO-06 / IO-07 (sortant, 4G)
   ─────────────────────────────┼───────────────────────────────────────
   ZONE 1                        │   PC maintenance 4itec │ Poste 4itec
   (IT fournisseur)              │   machine relais MAJ   │ (STLA-CS_FOR_502)
                    IO-01 HTTPS 443 │ IO-02 VNC 5999 │ IO-03 SSH 22
                    IO-04 RustDesk  │ IO-05 Tailscale│ (mise au point)
   ═══ conduit eth2 (RJ45 point-à-point, 192.168.3.0/24, UFW) ══════════
   ZONE 2                        │  Boîtier 4iSafeCross — Jetson Orin NX
   (OT Supervision)              │  Caddy:443  ──►  waitress:5050  (OO-04, loopback)
                                 │  TigerVNC:5999   SSH:22   UFW default deny
   intra-hôte (127.0.0.1)        │  client inférence ─► YOLO:8004 / RF-DETR:8002 (OO-02/03)
                    OO-01 RTSP 554 │ (eth1)                    OO-05 USB │
   ZONE 3                  ┌──────┴─────────────┐        ┌──────────────┴────┐
   (OT Process)            │ Caméras IP         │        │ Module relais     │
                           │ 192.168.2.156/157  │        │ Yoctopuce (USB)   │
                           └────────────────────┘        └───────────────────┘
```

---

## 2. Fichier 1 — Flux **IT ↔ OT**

| N° | Source (Zone) | Destination (Zone) | Protocole / service | Port · sens | Chiffrement | Authentification | Phase |
|---|---|---|---|---|---|---|---|
| IO-01 | PC maintenance 4itec — Z1 (`192.168.3.0/24`, eth2) | Boîtier / IHM supervision — Z2 (`192.168.3.122`) | HTTPS (TLS) | 443/TCP · requête unidir., session bidir. | **Oui** — Caddy `tls internal`, CA interne | **Oui** — HTTP Basic **obligatoire** (`SAFECROSS_AUTH_*`, refus de démarrage sans) | RUN |
| IO-02 | PC maintenance 4itec — Z1 (eth2) | Boîtier / bureau distant de maintenance — Z2 | VNC (TigerVNC) | 5999/TCP · bidir. | **Oui** — `-SecurityTypes X509Vnc,RA2ne` (TLS/X509 ou RSA-AES) | **Oui** — mot de passe VNC **unique par boîtier** | RUN — *seul accès graphique d'exploitation* |
| IO-03 | Poste 4itec — Z1 | Boîtier / SSH — Z2 | SSH v2 | 22/TCP · bidir. | **Oui** | **Oui** — clé + mot de passe compte | Mise au point + interventions ponctuelles |
| IO-04 | Poste 4itec via clé 4G / relais — Z1↔Z0 | Boîtier / RustDesk (relais self-hosted) — Z2 | RustDesk (propriétaire) | port relais · bidir. (sortant des 2 côtés) | **Oui** — chiffrement de bout en bout RustDesk | **Oui** — ID + clé RustDesk | **Mise au point uniquement** — à désinstaller (`CS-1143-04/05`) |
| IO-05 | Poste 4itec via clé 4G — Z1↔Z0 | Boîtier / Tailscale — Z2 | WireGuard + HTTPS | 41641/UDP, 443/TCP · bidir. | **Oui** | **Oui** — tailnet | **Mise au point, optionnel** — à retirer du RUN (`CS-1143-04`) |
| IO-06 | Boîtier via clé 4G — Z2↔Z0 | `api.telegram.org` — Z0 | HTTPS | 443/TCP · sortant | **Oui** — vérification TLS par défaut | **Oui** — token bot | **Mise au point uniquement** — inerte en cible ; retirer du boot RUN (`CS-127-01`) |
| IO-07 | Boîtier via clé 4G — Z2↔Z0 | Registres / dépôts : `registry.gitlab.4itec.ddns.net`, `repo.download.nvidia.com`, `ghcr.io` — Z0 | HTTPS | 443/TCP · sortant | **Oui** | Token (registre GitLab) · non (dépôts publics NVIDIA, signés GPG) | **Mise au point uniquement** — `docker pull` + paquets L4T ; en RUN, support local (`CS-145-01/02/03`) |
| IO-08 | Machine relais 4itec — Z1 | `ports.ubuntu.com` (`noble-security`), `repo.download.nvidia.com` (`jetson r39.2`) — Z0 | HTTPS | 443/TCP · sortant | **Oui** | Non (dépôts signés GPG) | **Fenêtre de MAJ déclarée** — n'implique **pas** le boîtier ; alimente le support amovible (`maj-l4t-hors-ligne.md`) |
| IO-09 | `eth0` (DHCP) | — | — | — | — | — | **Aucun flux** — port non raccordé en cible ; à désactiver logiquement (annexe audit §1.1.2) |

## 3. Fichier 2 — Flux **OT ↔ OT**

| N° | Source (Zone) | Destination (Zone) | Protocole / service | Port · sens | Chiffrement | Authentification | Phase |
|---|---|---|---|---|---|---|---|
| OO-01 | Boîtier 4iSafeCross — Z2/Z3 (`192.168.2.100`, eth1) | Caméras IP `192.168.2.156`, `192.168.2.157` — Z3 (`192.168.2.0/24`) | RTSP + RTP/RTCP interleaved over TCP | 554/TCP · requête + flux retour même session | **Non** | **Oui** — `RTSP_LOGIN` / `RTSP_PASSWORD` | RUN (permanent) |
| OO-02 | Client d'inférence 4iSafeCross — intra-hôte | Serveur YOLO `inf_jetson_yolo` — intra-hôte | HTTP | 8004/TCP `127.0.0.1` · requête→réponse | **Non** — boucle locale, ne traverse aucun média | Non | RUN |
| OO-03 | Client d'inférence 4iSafeCross — intra-hôte | Serveur RF-DETR `inf_jetson_rf-detr` — intra-hôte | HTTP | 8002/TCP `127.0.0.1` · requête→réponse | **Non** — boucle locale | Non | RUN |
| OO-04 | Reverse-proxy Caddy — intra-hôte | `waitress` / IHM Flask — intra-hôte | HTTP | 5050/TCP `127.0.0.1` · requête→réponse | **Non** — terminaison TLS en amont (Caddy, IO-01) | **Oui** — HTTP Basic appliqué par l'application | RUN |
| OO-05 | Boîtier 4iSafeCross — Z3 | Module relais Yoctopuce Yocto-MaxRelay — Z3 | Bus **USB** (lib `yoctopuce`) | s.o. (bus local) | s.o. | s.o. — accès physique au bus | RUN — pilotage avertisseurs lumineux / sonores |

---

## 4. Justification, filtrage et conformité par flux

| N° | Justification (besoin métier) | Équipement / règle de filtrage | Statut de conformité |
|---|---|---|---|
| IO-01 | Supervision, édition des zones et masques, toggle détection, réglage des seuils | UFW : `allow from 192.168.3.0/24 to any port 443` ; `default deny incoming` (`scripts/install_vnc_jetson.sh`). `waitress` lié à `127.0.0.1` (`run.py`) | `CS-1143-01` / `CS-143-02` / `CS-1144-01` — **corrigé côté dépôt (rév. 8 et 10)** ; contrôle `curl → 401` et certificat à la recette FOR_509 |
| IO-02 | Bureau distant de maintenance — seul accès graphique en RUN | UFW : `allow from 192.168.3.0/24 to any port 5999` ; fail2ban `tigervnc-auth` | `CS-1143-01` (`Majeure`) — chiffrement forcé côté script ; **à confirmer sur cible** |
| IO-03 | Administration, `scripts/deploy-jetson.sh`, diagnostics | UFW : `allow from <IP SSH> to any port 22` (anti-lockout) | Acceptable si borné et local ; à verrouiller / retirer si non requis en RUN |
| IO-04 | Réglage graphique à distance pendant la mise au point | Sortant via clé 4G ; relais RustDesk self-hosted 4itec | `CS-1143-04` / `CS-1143-05` — **à désinstaller à la livraison**, retrait attesté à la recette |
| IO-05 | Accès distant optionnel pendant la mise au point (`install_vnc_jetson.sh --tailscale`) | UFW `allow in on tailscale0 ...` (option) | `CS-1143-04` — **à retirer du livrable RUN** |
| IO-06 | Bot Telegram : alertes + commandes `/take`, `/status` | Sortant via clé 4G | `CS-127-01` — **inerte en cible** (pas d'Internet) ; code à retirer du boot RUN |
| IO-07 | `docker pull` de l'image applicative, paquets L4T | Sortant via clé 4G | `CS-145-01/02/03` — **fenêtre 4G à déclarer au PIL** ; en RUN, déploiement par support local |
| IO-08 | Constitution du support de mise à jour L4T de sécurité (hors ligne) | Machine relais 4itec en Zone IT ; le boîtier ne se connecte jamais | `CS-1141-02` / `CS-123-03` — procédure `docs/deployment/maj-l4t-hors-ligne.md` ; cadence trimestrielle |
| IO-09 | — | Port `eth0` non câblé ; désactivation logique demandée (annexe §1.1.2) | **Résolu par l'architecture** — à attester sur cible |
| OO-01 | Réception des flux vidéo H.264 des caméras | Sous-réseau caméras **dédié** sur `eth1`, isolé physiquement du reste | `CS-1143-01` **résiduel** — transport non chiffré ; isoler strictement ; évaluer RTSPS si le modèle caméra le permet |
| OO-02 | `POST` frame → détections (pipeline d'inférence YOLO) | `127.0.0.1` — non joignable hors hôte | Acceptable (intra-hôte). Retirer `network_mode: host` (`CS-1143-03`) pour cloisonner les conteneurs |
| OO-03 | `POST` frame → détections (pipeline RF-DETR) | `127.0.0.1` — non joignable hors hôte | Idem OO-02. **Incohérence de n° de port** entre `config/config.ini`, `README.md`, `docs/security/analyse-risques-cyber.md` — à fixer |
| OO-04 | Terminaison TLS (Caddy) → application (waitress) | `run.py` lie `waitress` à `127.0.0.1` seul ; aucune règle n'ouvre 5050 | `CS-143-02` — **conforme** ; l'authentification applicative s'applique aussi à ce segment |
| OO-05 | Pilotage des avertisseurs lumineux / sonores (fail-safe) | Bus USB local ; bibliothèque constructeur `yoctopuce` | Conforme. Accès `/dev` — cf. durcissement conteneur (`CS-1143-03`) |

---

## 5. Synthèse

- **Flux permanents en RUN** : IO-01, IO-02, (IO-03 si conservé), OO-01, OO-02, OO-03, OO-04, OO-05.
- **Flux de mise au point uniquement, à retirer + attester à la livraison** : IO-04, IO-05, IO-06, IO-07 (et la clé 4G elle-même).
- **Aucun flux entrant depuis Internet.** Aucun flux vers Internet en RUN.
- **Transport non chiffré résiduel** : OO-01 (RTSP caméras, sous-réseau dédié isolé) ; les flux `127.0.0.1` (OO-02/03/04) ne traversent aucun média réseau.
- **Point-à-point `eth2`** : accès physique requis ; pare-feu hôte `default deny` ; seuls 443 et 5999 (et 22 borné) ouverts, au seul `192.168.3.0/24`.

---

## 6. Validation

| Rôle | Nom | Visa | Date |
|---|---|---|---|
| Fournisseur (4itec) — rédaction | | | 2026-09-01 |
| Référent technique Stellantis — revue de la cartographie | | | |
| Plant IT Leader — fenêtre 4G de mise au point (flux IO-04 à IO-08) | | | |
| Comité Cybersécurité — approbation (`CS-145-03`) | | | |

---

## 7. Renvois

- `CYBER_AUDIT.md` — constats par flux, `## Cartographie des flux` (base de travail), `CS-143-01`, `CS-143-02`, `CS-1143-01`, `CS-1144-01`, `CS-145-xx`
- [docs/deployment/scripts-deploiement.md](../deployment/scripts-deploiement.md) — VNC chiffré, IHM HTTPS Caddy, UFW
- [docs/deployment/maj-l4t-hors-ligne.md](../deployment/maj-l4t-hors-ligne.md) — flux IO-08
- [../../scripts/install_vnc_jetson.sh](../../scripts/install_vnc_jetson.sh) — règles UFW (443, 5999, 22)
- [../../config/Caddyfile](../../config/Caddyfile) — terminaison TLS (IO-01, OO-04)
