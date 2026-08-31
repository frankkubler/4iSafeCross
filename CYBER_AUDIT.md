# Revue de cybersécurité — 4iSafeCross

- **Référentiel** : STLA-CS_STD_004 V4 — 11/2025 (réf. DocInfo 01201_20_00137, révision 4.1 du 09/12/2025)
- **Complément** : passe d'hygiène cyber générique (hors référentiel, section dédiée)
- **Dépôt** : `frankkubler/4iSafeCross`
- **Commit audité** : `8d3c9cf` — branche `fix-mapping-classes-dataset`
- **Date** : 2026-08-31 (révision 7 — RustDesk repositionné comme accès distant provisoire de mise au point, comme la clé 4G. Rév. 6 : docs de déploiement fusionnées. Rév. 5 : chiffrement VNC forcé. Rév. 4 : RDP→TigerVNC. Rév. 3 : `CS-113-04` corrigé)
- **Méthode** : analyse statique du code, de la configuration, de la CI/CD, de l'historique git et de la documentation. Aucune vérification sur cible.
- **Périmètre retenu** : le boîtier livré (appliance de vision Jetson Orin NX) et son logiciel embarqué. Hors périmètre : le matériel au catalogue, les licences ACRONIS/CrowdStrike/StellarProtect, l'installation physique, l'exploitation, et les serveurs d'inférence externes (`inf_jetson_yolo`, `inf_jetson_rf-detr`) référencés mais non inclus dans ce dépôt.

---

## Synthèse

**Modèle de déploiement confirmé par le fournisseur (révision 2)** : le boîtier est destiné à fonctionner **autonome, sans connexion Internet**. Il est connecté **provisoirement, via une clé 4G, pendant la phase de mise au point sur site**. Une fois réglé, la clé 4G est retirée et le seul accès résiduel est **local, par câble RJ45, en VNC** (TigerVNC — révision 4 : le fournisseur a remplacé RDP/xrdp par TigerVNC ; la doc de déploiement a été réalignée en révision 6). Cette clarification résout la question ouverte n°2 et fait passer cinq non-conformités de `Bloquante` à `Majeure` (voir *Périmètre et limites*). Elle ne modifie pas les constats sur les secrets (traités séparément — `CS-113-04` corrigé).

**Décompte par verdict** (46 exigences du référentiel réduit) :

| Verdict | Nombre |
|---|---|
| Conforme | 3 |
| Non conforme | 24 |
| Dérogation requise | 8 |
| Non applicable | 3 |
| Hors dépôt | 8 |

**Décompte des non-conformités par sévérité** (constats `Non conforme` + `Dérogation requise`, 32 lignes ; `CS-R3-01` partage le constat de `CS-1143-01` et n'est pas compté deux fois) :

| Sévérité | Nombre |
|---|---|
| Bloquante | 0 |
| Majeure | 24 |
| Mineure | 7 |

**Aucune non-conformité bloquante ne subsiste après la révision 4.** Les deux qui l'ont été :

- `CS-113-04` (secrets — était `Bloquante`) — **corrigé le 2026-08-31**. Token du bot Telegram révoqué (BotFather), mots de passe des caméras RTSP et du compte `user-4itec` changés (uniques par boîtier, coffre-fort 4itec), clé HMAC de licence régénérée — **rotation attestée par 4itec** (hors dépôt). Identifiants retirés de l'arbre courant ; **historique git réécrit** (`git filter-repo`, 573 commits) et force-pushé sur GitHub et GitLab ; MR/PR et pipelines porteurs des anciens commits supprimés (GitLab Repository cleanup, dépôt GitHub recréé). Vérifié : **0 occurrence des secrets sur l'ensemble des refs des deux remotes** (contrôle `git clone --mirror` + `git log --all -S`, et scan CI `gitleaks` = aucune fuite). Barrière ajoutée : job CI `security:gitleaks` bloquant + hook `.githooks/pre-commit` + `.gitleaks.toml`.
- `CS-1143-01` / `CS-R3-01` (protocoles — était `Bloquante`) — **rétrogradé en `Majeure` (révision 4)**. RDP/xrdp remplacé par **TigerVNC**. Révision 5 : le service force désormais `-SecurityTypes X509Vnc,RA2ne` (`scripts/install_vnc_jetson.sh:120`) — session chiffrée, `VncAuth`/`None` refusés ; reste à confirmer sur la cible. Résiduels non corrigés : l'IHM Flask en **HTTP clair** (`run.py:32`) et le transport RTSP caméras en clair. Correctifs de niveau configuration.

---

## Périmètre et limites

**Ce que le dépôt permet de prouver** : la nature des protocoles réellement employés, la présence ou l'absence de contrôle d'accès sur les points d'écriture, la gestion des secrets dans le code et l'historique, la composition de l'image de production (multi-étapes, dépendances), l'exposition réseau déclarée dans le code et les fichiers `docker-compose`, et l'état des dépendances vis-à-vis des avis de sécurité publics.

**Ce que le dépôt ne permet pas de prouver** : la version de firmware/OS réellement installée sur le Jetson et son homologation par le référent technique Stellantis ; la présence des agents ACRONIS, CrowdStrike, StellarProtect ; le retrait effectif de la clé 4G, de RustDesk et de Tailscale à l'issue de la mise au point ; l'application effective d'une politique de pare-feu hôte ; la conformité de la console de télémaintenance 4itec (STLA-CS_FOR_502) ; le respect des références matérielles au catalogue.

**Effet du modèle de déploiement confirmé sur les sévérités.** Le référentiel Stellantis raisonne « exposition réseau ». Un boîtier autonome, sans réseau partagé, dont l'accès exige une présence physique et un câble point-à-point, réduit la vraisemblance des scénarios réseau distants — mais **pas** la non-conformité du protocole employé (la recette FOR_509 applique une *zero-tolerance* sur la liste des protocoles interdits, indépendamment du contexte). En conséquence :

- passent de `Bloquante` à `Majeure` : `CS-1143-05`, `CS-127-01`, `CS-143-01`, `CS-143-02`, `CS-1144-01` ;
- **révision 4/5** : `CS-1143-01` passe de `Bloquante` à `Majeure` — RDP/xrdp remplacé par TigerVNC, chiffrement de session VNC forcé dans le script (rév. 5) ; reste l'IHM à passer en TLS et une vérification sur cible (config, pas architecture) ;
- **corrigé (révision 3)** : `CS-113-04` (secrets — voir *Synthèse* et le détail plus bas) ;
- **apparaissent** comme dérogations à formaliser en phase d'étude : `CS-145-01` et `CS-145-02` (connexion Internet provisoire + clé 4G pendant la mise au point).

**Réponses de cadrage (Phase 2)** :

1. **PC ou équipement industriel ?** — Équipement industriel : appliance de vision sur **Nvidia Jetson Orin NX** (reServer Industrial J4012, Seeed Studio), traitant des flux RTSP par inférence embarquée et pilotant des relais physiques. Ce n'est pas un PC/VM/serveur. Checklist de recette applicable : **STLA-CS_FOR_509** (équipements hors PC). **Zone grise** : l'équipement embarque son propre calcul et exécute l'application métier (serveur Flask, pipeline de détection) — un référent Stellantis peut le requalifier fonctionnellement en IPC et le basculer sur **STLA-CS_FOR_317**. À faire arbitrer en phase d'étude (question ouverte n°1).

2. **Sur quelle machine le livrable s'exécute-t-il une fois installé ?** — Sur le Jetson Orin NX, sous **JetPack / L4T** (Linux embarqué = firmware au sens du §1.1.4.1), en atelier logistique, **hors responsabilité IT**. La liste Windows du §1.2.3 ne s'applique donc pas ; c'est le §1.1.4.1 (firmware approuvé, versions identiques par référence) qui prend le relais. L'environnement de développement (Linux/x86, CI GitLab) est sans incidence sur le §1.2.3.

3. **Communication avec un équipement d'automatisme ?** — Pas d'automate, robot, visseuse ni AGV. Les seules sorties « équipement » sont des **relais USB Yoctopuce** (module Yocto-MaxRelay) pilotant des avertisseurs lumineux et sonores, via la bibliothèque constructeur officielle `yoctopuce`. Aucun protocole d'automatisme (S7, MODBUS, EtherNet/IP…). Le §1.1.4.4 s'applique néanmoins : l'activation/désactivation de la détection et le mappage zone→relais sont des consignes de sécurité écrites via l'API web.

4. **Connecté ou autonome ?** — **Résolu (fournisseur, révision 2)** : autonome en exploitation, **sans connexion Internet**. Connexion **provisoire par clé 4G** pendant la mise au point sur site ; clé retirée ensuite. Accès résiduel en RUN : **local, RJ45, VNC (TigerVNC chiffré)**. Les fonctions de connectivité de la phase de mise au point — clé 4G, **RustDesk** (accès distant graphique), option Tailscale, bot Telegram, `pull` registry — sont à désinstaller/retirer du livrable RUN et leur retrait à attester à la recette. Verdict retenu : le dépôt contient toujours ce code actif et activable par configuration, d'où des constats maintenus mais rétrogradés en `Majeure`, et deux dérogations à formaliser pour la fenêtre 4G.

5. **Données classifiées C3/C4 ?** — Le système traite des **images de personnes** (piétons, opérateurs) : captures `detections/`, dataset `dataset/`, flux MJPEG de l'IHM, images annotées éventuellement envoyées via Telegram, base SQLite `db/detections.db`. Un registre RGPD (Art. 30) est présent (`docs/compliance/registre-traitements-rgpd.md`) : base légale intérêt légitime, pas d'identification nominative revendiquée. La classification Stellantis (C2 ? C3 ?) est à confirmer avec le pilote. Aucune donnée n'est chiffrée au repos.

---

## Modèle mental

4iSafeCross est un système de sécurité industrielle par vision par ordinateur, déployé sur un boîtier Nvidia Jetson Orin NX en entrepôt logistique. Il reçoit les flux RTSP H.264 de caméras IP fixes (sous-réseau dédié `192.168.2.x` sur `eth1`), applique une détection de mouvement MOG2 puis une inférence YOLO/RF-DETR déportée sur des serveurs HTTP tournant en local sur le même Jetson (`127.0.0.1:8002` et `:8004`), filtre les faux positifs (keypoints de pose, debounce temporel, exclusion du label `driver`), et lorsqu'un piéton est confirmé dans une zone il active des relais USB Yoctopuce (avertisseurs lumineux/sonores) et, en option, envoie une alerte Telegram avec image annotée. Un mode fail-safe force les relais à ON au démarrage et sur perte de heartbeat.

Une interface web Flask/Waitress (port 5050) sert le flux vidéo en direct, un éditeur graphique de zones et de masques, la galerie des détections et des pages de supervision système. Ces pages **modifient la configuration de sécurité en direct** : géométrie des zones de détection, masques d'exclusion du pipeline, seuil de déclenchement du mouvement, activation/désactivation de la détection par caméra, mappage zone→relais. L'application lit ses secrets (token Telegram, identifiants RTSP) depuis l'environnement (`.env` chargé par systemd) avec `config.ini` en dernier recours, et vérifie une licence RSA au démarrage via un paquet externe `license-validator` (registry GitLab privé 4itec), avec protection anti-retour d'horloge par état local signé HMAC.

**Cycle de vie** : pendant la mise au point sur site, le boîtier est connecté à Internet par une clé 4G (téléchargement d'image, réglages, accès distant graphique par RustDesk et/ou Tailscale, éventuellement Telegram). À la livraison, la clé 4G est retirée et RustDesk/Tailscale désinstallés : le boîtier devient autonome et le seul accès est un câble RJ45 point-à-point vers un PC de maintenance, en VNC (TigerVNC chiffré). L'image de production est construite en multi-étapes (Docker) avec compilation Cython du code Python, et lancée en `privileged` + `network_mode: host` + `-v /dev:/dev`, en utilisateur root.

---

## Tableau de conformité

**Lecture des identifiants `CS-…`** — numérotation interne stable de ce référentiel d'audit (réduction de la norme **STLA-CS_STD_004 V4** aux exigences vérifiables sur un dépôt) ; ce ne sont pas des références officielles Stellantis. Format : `CS` – `<chapitre de la norme, points retirés>` – `<n° d'exigence dans le chapitre>`. La colonne **Chapitre** ci-dessous donne la section réelle de la norme.

| Préfixe | Chapitre STLA-CS_STD_004 | Sujet |
|---|---|---|
| `CS-113-xx` | §1.1.3 | Contrôle d'accès logique — comptes, secrets, autologon |
| `CS-1141-xx` | §1.1.4.1 | OS / firmware et correctifs |
| `CS-1143-xx` | §1.1.4.3 | Protocoles et services sécurisés (protocoles interdits, TLS, services exposés) |
| `CS-1144-xx` | §1.1.4.4 | Contrôle d'accès à l'écriture des variables / consignes |
| `CS-123-xx` | §1.2.3 | OS approuvés (liste Windows) |
| `CS-127-xx` | §1.2.7 | Internet et messagerie sur machines Manufacturing |
| `CS-128-xx` | §1.2.8 | Outils de développement absents des machines de production |
| `CS-R1-xx` … `CS-R8-xx` | §1.2.9, Règles 1 à 8 | Développement d'applications industrielles (données, identité, journalisation, protocoles constructeur, guides sécurisés, MCO, compat OS, audits) |
| `CS-143-xx` | §1.4.3 | Filtrage des communications, cartographie des flux |
| `CS-144-xx` | §1.4.4 | Supervision réseau, journalisation des flux rejetés |
| `CS-145-xx` | §1.4.5 | Raccordement au réseau IT de l'usine, sans-fil, 3G/4G/5G |
| `CS-15-xx` | §1.5 | Consoles et postes de développement du fournisseur |

Exemple : **`CS-1143-01`** = §1.1.4.3, exigence n°1 — *« aucun protocole interdit n'est utilisé »* (HTTP en clair, FTP, TFTP, Telnet, SSHv1, SMBv1/2, RDP, SMTP en clair, SNMPv1/2, OPC-DA, MQTT non chiffré, MODBUS, Open Protocol). Quand deux exigences visent le même constat — typiquement `CS-1143-01` et `CS-R3-01` (§1.2.9 Règle 3, « protocoles non sécurisés proscrits ») — il n'est porté qu'une fois, l'autre ligne y renvoie.

| ID | Chapitre | Exigence | Verdict | Sévérité | Preuve (fichier:ligne) | Action |
|---|---|---|---|---|---|---|
| CS-113-01 | §1.1.3 | Authentification via serveurs centraux Stellantis (RADIUS / AD / PingFederate) | Dérogation requise | Majeure | `src/web/app_factory.py:23-25` (HTTP Basic locale, deux variables d'env) ; `scripts/install_vnc_jetson.sh` (compte local VNC) | Intégrer PingFederate pour l'IHM métier ; à défaut, formaliser par écrit le motif d'authentification locale (aucune solution centrale compatible sur équipement embarqué autonome) et adresser la dérogation au référent technique en phase d'étude |
| CS-113-02 | §1.1.3 | Au moins deux comptes distincts : Administrateur et Opérateur | Non conforme | Majeure | `src/web/app_factory.py:28-34` (une seule paire d'identifiants, un seul niveau) | Introduire un rôle Opérateur (consultation, acquittement) distinct du rôle Administrateur (édition des zones, toggle détection, arrêt) et l'appliquer dans le garde d'accès |
| CS-113-03 | §1.1.3 | Comptes par défaut supprimés, comptes inutilisés désactivés | Non conforme | Majeure | `utils/constants.py:202` (`fallback='admin'` pour `RTSP_LOGIN`) ; `README.md:719` (`user-4itec`) | Supprimer le fallback `admin` ; renommer le compte `user-4itec` en compte nominatif ; désactiver les comptes de démonstration à la recette. Constat lié à `CS-113-04` |
| CS-113-04 | §1.1.3 | Aucun secret en dur dans le code **ni dans l'historique git** | Conforme *(corrigé 2026-08-31 — était `Non conforme` / `Bloquante`)* | — | Arbre courant sans secret ; historique réécrit (`git filter-repo`, 573 commits) et force-pushé sur les deux remotes ; MR/PR + pipelines porteurs des anciens commits supprimés ; vérif `git clone --mirror` + `git log --all -S` = **0 occurrence sur toutes les refs** de GitHub et GitLab. Job CI `security:gitleaks` bloquant + hook `.githooks/pre-commit` ; scan CI = aucune fuite (un seul faux positif `admin:mon_mdp`, gabarit de doc, allowlisté) | Terminé. Rotation des secrets (token Telegram, mots de passe RTSP et `user-4itec`, clé HMAC) **attestée par 4itec** — hors dépôt, à confirmer au pilote |
| CS-113-05 | §1.1.3 | Autologon autorisé seulement si compte Opérateur + IHM runtime + pas d'accès OS + hors Internet | Non conforme | Majeure | `docs/deployment/scripts-deploiement.md` § « Session graphique headless (GDM3) » (`AutomaticLogin=user-4itec`) | En cible autonome, la condition « machine non connectée à Internet » est satisfaite, mais les deux autres non (session XFCE complète, accès shell, compte non Opérateur). Supprimer l'autologon ou le restreindre à un compte Opérateur sans accès OS (déjà signalé dans la doc de déploiement) |
| CS-113-06 | §1.1.3 | Politique de mot de passe Stellantis, rotation, changement des mots de passe par défaut à la recette | Non conforme | Majeure | `README.md:719` (mot de passe partagé du site) ; `git show 6e2c019:config/config.ini` (`PASSWORD` renseigné en clair) | Mot de passe faible réutilisé (maintenance + caméras RTSP). Appliquer la politique Stellantis, imposer un changement à la recette, mettre en place la rotation. Constat lié à `CS-113-04` |
| CS-1141-01 | §1.1.4.1 | Version d'OS/firmware/runtime = dernière approuvée, **identique pour les équipements de même référence** | Dérogation requise | Majeure | `README.md:312` (« JetPack 6.2 / L4T 36.4.3 ») vs `Dockerfile:253,296` (CUDA 13.2.1, dépôt apt L4T `r39.2` = JetPack 7.2) | Incohérence de version de firmware cible entre le README et l'image ARM64. Trancher la version officielle, la faire homologuer par le référent technique, garantir l'identité du firmware sur tout le parc de boîtiers d'une même référence |
| CS-1141-02 | §1.1.4.1 | Procédure et outils de mise à jour du firmware/OS livrés pour la phase RUN | Non conforme | Mineure | `docs/deployment/flash-jetson-reserver-j4012-jetpack62.md` (flash initial) ; `scripts/deploy-jetson.sh` (MAJ image applicative uniquement) | Ajouter une procédure de mise à jour L4T/JetPack **hors ligne** en phase RUN (le boîtier étant autonome), avec canal de sécurité et procédure de rollback |
| CS-1141-03 | §1.1.4.1 | Engagement à développer les correctifs en cas de faille en phase RUN | Hors dépôt | — | Aucun `SECURITY.md` ni politique de divulgation ; `docs/security/cve-2026-47265-suivi.md` (suivi CVE manuel ponctuel) | Formaliser l'engagement contractuel de MCO cyber ; ajouter `SECURITY.md` avec canal de signalement. À confirmer avec le pilote (volet contractuel) |
| CS-1143-01 | §1.1.4.3 | Aucun protocole interdit (HTTP, FTP, Telnet, RDP, SMBv1/2, SNMPv1/2, MQTT clair, MODBUS…) | Non conforme | Majeure | RDP/xrdp **abandonné** au profit de TigerVNC. VNC : `scripts/install_vnc_jetson.sh:120` force `-SecurityTypes X509Vnc,RA2ne` (session chiffrée, `VncAuth` refusé) — **à confirmer sur cible**. Résiduels : `run.py:32` (IHM en HTTP clair) ; `src/camera_manager.py:152` (`rtsp://` en clair) | Vérifier sur cible que TigerVNC négocie X509Vnc/RA2ne ; placer l'IHM derrière TLS et la binder sur `eth2` ; isoler strictement le sous-réseau caméras |
| CS-1143-02 | §1.1.4.3 | Protocoles autorisés employés correctement (TLS vérifié, SSHv2, SNMPv3, MQTTS…) | Conforme | — | `src/bot_aiogram.py:68,103` (HTTPS `api.telegram.org`, vérification TLS par défaut de `requests`/`aiohttp`) ; aucune occurrence de `verify=False` / `InsecureSkipVerify` dans le dépôt | Rien à signaler pour les flux TLS existants. Couverture faible : TLS globalement absent de l'IHM et de l'inférence (voir `CS-1143-01`) |
| CS-1143-03 | §1.1.4.3 | Seuls les protocoles et services nécessaires installés/activés ; éviter les options par défaut | Non conforme | Majeure | `docker-compose-arm64.yml:5,7,9` (`network_mode: host`, `privileged: true`, `ipc: host`) ; `scripts/deploy-jetson.sh:79-93` (`--privileged`, `-v /dev:/dev`, `--network host`) ; `Dockerfile` (aucun `USER`, exécution root ; `gstreamer1.0-tools`, `vainfo`, `curl`, `iputils-ping` dans le stage final) | Retirer `privileged`/`host`/`/dev:/dev` ; publier uniquement le port utile ; `cap_drop: [ALL]` + capacité minimale ; `security_opt: [no-new-privileges]` ; `USER` non-root ; purger les outils de diagnostic de l'image finale. **Non atténué par l'air-gap** (durcissement anti-évasion de conteneur) |
| CS-1143-04 | §1.1.4.3 | Protocoles de découverte automatique et de connexion à distance désactivés après vérification | Non conforme | Mineure | Accès distant de **mise au point** : `autostart/rustdesk-xhost.desktop` (RustDesk) et option `install_vnc_jetson.sh --tailscale`. En RUN : seul le VNC local doit rester ; RustDesk/Tailscale sont documentés comme à désinstaller (`docs/deployment/scripts-deploiement.md`, procédure de retrait). `scripts/security_audit.sh:336-344` (avahi/rpcbind/cups à contrôler sur cible) | À la recette : attester la désinstallation de RustDesk et Tailscale ; contrôler mDNS/Avahi/UPnP sur la cible (Hors dépôt) |
| CS-1143-05 | §1.1.4.3 | Besoin de communication externe exprimé au Plant IT Leader / Cybersecurity Leader dès le début du projet | Non conforme | Majeure | Connectivité de mise au point : clé 4G + **RustDesk** (`autostart/rustdesk-xhost.desktop`) + option Tailscale + `src/bot_aiogram.py` (Telegram) | Décrire au PIL la **fenêtre de mise au point** (durée, flux, outils : 4G, RustDesk, Tailscale, Telegram) et attester leur retrait + le retrait de la clé à la livraison |
| CS-1144-01 | §1.1.4.4 | Écriture de variables/consignes protégée par mot de passe (sauf impossibilité matérielle/logicielle) | Non conforme | Majeure | `src/web/app_factory.py:37-47` (auth optionnelle, warning seul) ; `src/web/routes_zones_api.py:39,72,122,164` ; `src/web/routes_detection.py:17,77` | Rendre l'authentification **obligatoire** (refus de démarrage si non configurée) sur toutes les routes d'écriture. Constat maintenu malgré l'air-gap : une session RDP (mot de passe unique, présent dans l'historique) donne accès sans second facteur à des consignes de sécurité, sans journal |
| CS-123-01 | §1.2.3 | OS approuvé (Windows 11 IoT Enterprise LTSC 2024 / Windows Server 2025) sur PC/VM/serveur Manufacturing hors IT | Non applicable | — | `README.md:5` (Jetson Orin NX, équipement embarqué) ; `Dockerfile:253` (L4T) | **Non applicable avec réserve** : équipement embarqué exécutant l'application métier, de nature contestable. À faire arbitrer par le référent technique en phase d'étude (question ouverte n°1). Contrôler `CS-1141-01` (firmware) et recetter au FOR_509 |
| CS-123-02 | §1.2.3 | Correctifs mensuels Windows depuis le WSUS interne Stellantis | Non applicable | — | Cible non Windows (`CS-123-01`) | Sans objet |
| CS-123-03 | §1.2.3 | En cas de dérogation d'OS, équivalent du correctif mensuel assuré sur l'OS retenu | Dérogation requise | Majeure | `Dockerfile:253,265-303` (Ubuntu 24.04 + dépôt apt L4T `r39.2`) ; aucun canal de mise à jour de sécurité documenté | Documenter l'origine des paquets, le canal de sécurité Ubuntu 24.04 LTS et L4T, la version encore supportée, et la **procédure de mise à jour hors ligne** du boîtier autonome. Lié à `CS-1141-01` |
| CS-127-01 | §1.2.7 | Internet et messagerie strictement interdits sur les machines Manufacturing | Dérogation requise | Majeure | `src/bot_aiogram.py:27,42,68,103` (`api.telegram.org`, long polling) ; clé 4G de mise au point | En cible, l'exigence est atteinte par l'architecture (pas d'Internet). Résiduel : (a) fenêtre 4G de mise au point → dérogation bornée dans le temps + expression de besoin PIL ; (b) code Telegram présent et activable → retirer du boot en production ou le neutraliser en dur |
| CS-127-02 | §1.2.7 | Aucun logiciel non nécessaire au fonctionnement ou non décrit au cahier des charges | Non conforme | Mineure | `Dockerfile:59` + venv copié (`cython==3.2.8`, `setuptools`, `wheel`) ; `pyproject.toml:19` (`setuptools>=80.8.0` en dépendance d'exécution) ; client Telegram dans le code ; RustDesk/Tailscale (mise au point) | Retirer Cython/setuptools/wheel du venv de production ; désinstaller RustDesk/Tailscale et retirer le client Telegram du livrable RUN (xrdp/RDP jamais installé) |
| CS-128-01 | §1.2.8 | Aucun outil de développement sur la machine de production : seul le Runtime installé | Non conforme | Majeure | `Dockerfile:55-60` (Cython + setuptools + wheel installés dans le builder, jamais retirés) puis `Dockerfile:220,306` (`COPY --from=builder /app/.venv` copié tel quel) ; `Dockerfile:198,272` (`gstreamer1.0-tools`) | Le multi-étapes retire bien gcc/build-essential, mais le venv final embarque la chaîne Cython. Nettoyer le venv après compilation (`uv pip uninstall cython setuptools wheel` ou reconstruction sans ces paquets) ; retirer `gstreamer1.0-tools` du runtime |
| CS-R1-01 | §1.2.9 R1 | Données confidentielles C3 chiffrées (au repos, clés hors du code) | Dérogation requise | Majeure | `utils/utils.py:47` (`cv2.imwrite` captures en clair) ; `src/collect_dataset.py` (dataset en clair) ; `db/detections.db` (SQLite non chiffrée) | Confirmer la classification Stellantis des images de personnes avec le pilote/DPO. Si ≥ C3 : chiffrer `detections/`, `dataset/`, `db/` au repos avec gestion de clés hors du dépôt. **Non atténué par l'air-gap** (le vol du support est le scénario visé). Question ouverte n°5 |
| CS-R1-02 | §1.2.9 R1 | Aucune donnée C4 (secret) stockée localement sur le poste | Conforme | — | Les seuls secrets présents (token Telegram, identifiants RTSP, clé HMAC) relèvent de la gestion de credentials, pas d'une classification C4 Stellantis | Rien à signaler, sous réserve de confirmation qu'aucune donnée C4 n'est manipulée |
| CS-R1-03 | §1.2.9 R1 | Destruction des données prévue en fin de vie du poste | Non conforme | Mineure | `src/detection_db.py:38` + `utils/utils.py:22` (purge par âge = rétention, pas effacement de fin de vie) | Documenter une procédure d'effacement sécurisé (`nvme format` / `blkdiscard` / réécriture) des supports en fin de vie ou en retour SAV |
| CS-R2-01 | §1.2.9 R2 | Accès applicatif via identification et droits centralisés (PingFederate) | Non conforme | Majeure | `src/web/app_factory.py:23-25` (HTTP Basic locale) | Constat identique à `CS-113-01`. Intégrer PingFederate ou documenter le motif de dérogation |
| CS-R2-02 | §1.2.9 R2 | Droits limités au rôle et à la responsabilité de l'utilisateur | Non conforme | Majeure | `src/web/app_factory.py:51-65` (le garde autorise tout ou rien) | Constat identique à `CS-113-02`. Définir un modèle d'autorisation effectif |
| CS-R2-03 | §1.2.9 R2 | Traçabilité des accès assurée par génération de logs | Non conforme | Majeure | `src/web/app_factory.py:61-65` (401 renvoyé sans journalisation) ; aucun log d'action privilégiée avec identité/horodatage/IP ; `docs/security/analyse-risques-cyber.md` R09 le reconnaît | Ajouter un journal d'audit : succès et échecs d'authentification, écriture de zone/masque/seuil, toggle détection — avec identité, horodatage, IP source. D'autant plus nécessaire que l'accès RDP est mono-compte et non nominatif |
| CS-R2-04 | §1.2.9 R2 | Logs remontés vers un SIEM ; à défaut, générés localement a minima | Non conforme | Mineure | `docker-compose-*.yml` (`json-file`, 10 Mo × 5) ; `scripts/4isafecross.logrotate` ; aucun syslog / agent de collecte | Logs locaux présents mais non exploitables hors machine. Prévoir un export (support amovible ou syslog vers un collecteur lors des interventions de maintenance) |
| CS-R3-01 | §1.2.9 R3 | Protocoles non sécurisés proscrits | Non conforme | Majeure | Voir `CS-1143-01` (constat unique, non dupliqué) | Voir `CS-1143-01` |
| CS-R3-02 | §1.2.9 R3 | Protocoles constructeur pour la communication avec automates/robots | Non applicable | — | Pas d'automate. Relais Yoctopuce pilotés via la bibliothèque constructeur officielle `yoctopuce` (`src/relay_pilot.py:1-2`, `pyproject.toml:21`) | Sans objet ; la bibliothèque relais est bien celle du constructeur |
| CS-R4-01 | §1.2.9 R4 | Respect des guides de développement sécurisé Stellantis de la technologie (Python, HTML/JS) | Dérogation requise | Mineure | Fondamentaux OK : SQL paramétré (`src/detection_db.py:30-33`), pas d'`eval`/`exec`/`shell=True` (`utils/utils.py:49`, `src/core/gpu_metrics.py:117`), `ast.literal_eval` et non `eval` (`utils/constants.py:204`), `innerHTML` maîtrisé (`templates/index.html:632`). Manques : pas de protection CSRF sur les POST, pas d'en-têtes de sécurité HTTP (CSP, HSTS, X-Content-Type-Options) | Demander au pilote les guides Stellantis « Python » et « HTML/JS » (non joints à la note). Ajouter protection CSRF et en-têtes de sécurité sur l'IHM |
| CS-R5-01 | §1.2.9 R5 | Engagement de résultat cybersécurité en BUILD et RUN, pénalités en cas de cyberattaque imputable | Hors dépôt | — | Aucune trace contractuelle dans le dépôt | À confirmer avec le pilote (volet contractuel / `SECURITY.md`) |
| CS-R6-01 | §1.2.9 R6 | Maintien en condition de sécurité : pas de CVE critique ouverte, versions supportées | Non conforme | Majeure | `pip-audit` (2026-08-31) : `aiohttp 3.14.1` → PYSEC-2026-3545/3546/3547 (corrigées 3.14.2/3.14.3) ; `cryptography 49.0.0` → PYSEC-2026-3552 (corrigée 50.0.0). `pyproject.toml:8,10` en `>=` ; `.gitlab-ci.yml` (`allow_failure: true`) | Mettre à jour `aiohttp` (≥ 3.14.3) et `cryptography` (≥ 50.0.0), régénérer `uv.lock` ; passer `pip-audit`/`bandit` en `allow_failure: false`. L'air-gap réduit l'exploitabilité d'`aiohttp` (client réseau) mais pas de `cryptography` (chemin de vérification de licence, au démarrage) |
| CS-R7-01 | §1.2.9 R7 | Compatibilité avec les futures versions d'OS sans modifier les interfaces de communication ni les composants d'automatisme | Non conforme | Mineure | `pyproject.toml:6` (`requires-python <3.13`) ; `pyproject.toml:16` (`pygobject<3.51.0`) ; couplage fort à GStreamer/L4T d'une version de JetPack (`src/camera_manager.py:137-170`) | Documenter la matrice de compatibilité OS/runtime et le plan de montée de version ; lever les plafonds dès que possible |
| CS-R8-01 | §1.2.9 R8 | Livrable présentable en audit / QUALYS : pas de config par défaut, pas de bannière de version exposée | Non conforme | Majeure | `templates/index.html` (version applicative affichée) ; `src/web/routes_system.py:94-127` (`/debug_info` : IP, `docker ps`, statut systemd, chemins, charge — sans auth par défaut) ; `docker-compose-arm64.yml` (config par défaut : host, privileged, root) | Retirer la bannière de version des réponses publiques ; passer `/debug_info` derrière authentification et réduire son contenu ; durcir la configuration par défaut. Le boîtier doit rester présentable à un audit QUALYS malgré l'air-gap |
| CS-143-01 | §1.4.3 | Cartographie des flux fournie au modèle Stellantis (fichier IT/OT + fichier OT/OT) | Non conforme | Majeure | Aucun fichier de cartographie dans le dépôt | Produire les deux fichiers au format Stellantis. Les flux étant peu nombreux en cible autonome, le livrable est simple : la section « Cartographie des flux » ci-dessous en constitue la base |
| CS-143-02 | §1.4.3 | Seuls les flux sécurisés nécessaires ouverts ; filtrage applicatif dès que possible | Non conforme | Majeure | `run.py:32` (`host='0.0.0.0'`) ; `scripts/4isafecross.sh:10` ; `docker-compose-*.yml` (`network_mode: host`) ; auth optionnelle | Binder l'IHM sur l'interface de maintenance (`eth2`) ou `127.0.0.1` derrière un reverse-proxy TLS ; retirer `network_mode: host` ; activer le filtrage applicatif (auth obligatoire). Important pendant la fenêtre 4G, où `0.0.0.0` + `network_mode: host` rend l'IHM joignable depuis la clé cellulaire si le pare-feu hôte ne la bloque pas |
| CS-144-01 | §1.4.4 | Flux rejetés journalisés et analysés ; flux entrants/sortants journalisés | Non conforme | Majeure | `src/web/app_factory.py:61-65` (rejets 401 non journalisés) ; aucun journal de connexion applicatif | Journaliser les connexions et les rejets côté application, avec rotation ; croiser avec fail2ban |
| CS-145-01 | §1.4.5 | Interdiction de raccorder un équipement industriel aux réseaux bureautiques | Dérogation requise | Majeure | Modèle de déploiement confirmé : connexion Internet **provisoire** (clé 4G) pendant la mise au point ; `README.md` (historique `e169161`) | En cible, l'équipement est autonome → conforme à l'intention. La connexion provisoire de mise au point doit faire l'objet d'une dérogation bornée (durée, périmètre) et d'une expression de besoin auprès du Plant IT Leader avant l'intervention |
| CS-145-02 | §1.4.5 | En sans-fil : seuls GPSAKEY / GPSACERT ; Wi-Fi bureautique et **routeurs 3G/4G/5G interdits** | Dérogation requise | Majeure | Modèle de déploiement confirmé : **clé 4G utilisée pendant la mise au point** ; option Tailscale (`install_vnc_jetson.sh --tailscale`, doc = à retirer pour le RUN) | La norme interdit tout routeur/clé 3G/4G/5G, sans exemption « temporaire ». Demander une dérogation explicite au référent technique pour la fenêtre de mise au point : durée maximale, retrait physique de la clé attesté à la livraison, aucune donnée de production transmise, pare-feu hôte actif pendant la fenêtre |
| CS-145-03 | §1.4.5 | Raccordement : expression de besoin auprès du Plant IT Leader + cartographie approuvée par le Comité Cybersécurité | Hors dépôt | — | Non prouvable depuis le dépôt | Soumettre au Plant IT Leader l'expression de besoin pour la fenêtre 4G de mise au point et la cartographie de flux, pour approbation par le Comité Cybersécurité |
| CS-15-01 | §1.5 | Console fournisseur à jour des correctifs de sécurité de son OS | Hors dépôt | — | Console de télémaintenance / mise au point 4itec non décrite dans le dépôt | À attester par 4itec ; contrôlé par audit STLA-CS_FOR_502 |
| CS-15-02 | §1.5 | Console fournisseur équipée d'un antivirus **version professionnelle** (gratuit/essai refusés) | Hors dépôt | — | Non prouvable depuis le dépôt | Point de friction sous Linux : prévoir une solution commerciale sous licence, à faire valider par le pilote avant la première intervention |
| CS-15-03 | §1.5 | Définitions virales de moins de 7 jours | Hors dépôt | — | Non prouvable depuis le dépôt | Contrainte d'exploitation, à planifier avant chaque intervention |
| CS-15-04 | §1.5 | Scan antivirus complet de moins de 7 jours | Hors dépôt | — | Non prouvable depuis le dépôt | Idem — à planifier |
| CS-15-05 | §1.5 | Ces exigences valent aussi pour les machines fournisseur d'accès distant | Hors dépôt | — | Le PC 4itec qui ouvre les sessions VNC sur `eth2` (et RustDesk/Tailscale/SSH pendant la mise au point) est dans le périmètre | Inclure explicitement ce PC dans le périmètre STLA-CS_FOR_502 |

---

## Non-conformités bloquantes — détail

**Aucune non-conformité bloquante ne subsiste après la révision 4.** La révision 2 (modèle de déploiement autonome confirmé) a rétrogradé cinq constats d'exposition réseau ; la révision 3 a corrigé `CS-113-04` (secrets) ; la révision 4 rétrograde `CS-1143-01` en `Majeure` (RDP/xrdp remplacé par TigerVNC). Cette section conserve le détail des deux constats qui ont été bloquants.

### 1. `CS-113-04` — Secrets dans l'historique git et l'arbre courant — **CORRIGÉ (2026-08-31)**

> **Statut : résolu.** Rotation des secrets attestée par 4itec (token Telegram révoqué via BotFather ; mots de passe RTSP et `user-4itec` changés, uniques par boîtier, dans le coffre-fort Vaultwarden 4itec ; clé HMAC de licence régénérée). Identifiants retirés de l'arbre courant (commit `9a02cac`). Historique réécrit (`git filter-repo`) sur les 573 commits, force-push GitHub + GitLab. Refs internes porteuses des anciens commits éliminées (GitLab : suppression des MR + Repository cleanup ; GitHub : dépôt recréé). Contrôle final `git clone --mirror` + `git log --all -S` sur les deux remotes : **0 occurrence**. Prévention : job CI `security:gitleaks` bloquant, hook `.githooks/pre-commit`, `.gitleaks.toml`. Le constat ci-dessous est conservé pour mémoire de l'état avant correction.

**Constats (état avant correction)** :

- **Token du bot Telegram + `chat_id`**, en clair, non commentés dans `config/config.ini` aux commits `144ad43` et `6739ad0` (`TOKEN = 6741846240:AAG…`, `CHAT_ID = -4115…` — valeurs complètes dans l'historique). Deux tokens de bot de développement supplémentaires (`7161709928:AAG…` et `7161709928:AAE…`) figurent en commentaire dans l'historique (`57a13f4`).

- **Identifiants des caméras RTSP**, en clair dans `config/config.ini` au commit initial `6e2c019` (`LOGIN = admin`, `PASSWORD = <mot de passe partagé du site>`), également dans `7a68ac1` et `6739ad0`.

- **Mot de passe du compte de maintenance `user-4itec`**, en clair **dans l'arbre courant** : `README.md:719` (`user : user-4itec / mdp : <valeur en clair>`), répété dans `docs/security/rapport-cybersec.md:143`. Identique (à la casse près) au mot de passe des caméras RTSP : mot de passe de site partagé. **C'est aussi le mot de passe qui ouvre les sessions de maintenance (VNC/SSH) en exploitation.**

- **Clé HMAC de l'état de licence** : `licenses/license_state.key` (32 octets binaires) a été versionnée puis retirée en `f011f5b` ; elle reste extractible de tout clone. Cette clé signe `license_state.json` ; sa connaissance permet de forger un état de licence valide et de contourner la protection anti-retour d'horloge (`README.md:474-483`).

**Impact** : un token de bot Telegram permet à un tiers d'émettre de faux messages, de lire l'historique du canal (images annotées de piétons — données personnelles) et de recevoir les captures — depuis n'importe où, tant que le token n'est pas révoqué. Le mot de passe RTSP donne accès aux flux des caméras. Le mot de passe `user-4itec` ouvre la session de maintenance du boîtier (VNC, shell), donc l'IHM d'administration — et il était identique sur tout le parc. L'air-gap ne referme aucune de ces portes : un secret publié le reste.

**Correction** :

1. **Révoquer d'abord** : régénérer le token du bot via BotFather (`/revoke`) ; changer le mot de passe sur toutes les caméras RTSP ; changer le mot de passe `user-4itec` sur tous les boîtiers, avec un mot de passe **unique par boîtier** ; régénérer la clé HMAC de licence (suppression de `license_state.key`/`license_state.json` sur cible, recréation au démarrage).
2. Retirer `README.md:719` et `docs/security/rapport-cybersec.md:143` :
   ```diff
   - - **eth2** est réservé pour la connexion VNC de maintenance (port 5999) ... user : user-4itec / mdp : <valeur en clair>
   + - **eth2** est réservé pour la connexion de maintenance. Identifiants transmis hors dépôt, par canal sécurisé, uniques par boîtier.
   ```
   *(fait dans le commit `68ce83f` du 2026-08-31)*
3. Purger l'historique (`git filter-repo --replace-text`) ou reconstruire le dépôt ; forcer la rotation de tout secret ayant transité par la CI.
4. **Base de connaissance maintenance 4itec** : conserver dans le dépôt privé un runbook décrivant la procédure, le compte et la méthode d'accès, et **l'emplacement** du mot de passe (entrée `pass` `4isafecross/<site>/maintenance` ou coffre 4itec) — pas la valeur. Si la valeur doit être versionnée, la stocker en blob **chiffré GPG** (`pass`), déchiffrable seulement par les clés autorisées — même mécanisme que celui déjà prescrit au `README.md:374-395` pour le token GitLab.

**Statut de remédiation — CLÔTURÉ le 2026-08-31** : identifiants retirés de l'arbre courant (`README.md`, `docs/security/rapport-cybersec.md`, `docs/tools/prompt-cybersec-audit.md`, `docs/security/cybersec-implementation-plan.md`) et `licenses/license_state.json` dé-suivi (commit `9a02cac`) ; historique réécrit (`git filter-repo`) et force-pushé sur GitHub + GitLab ; refs internes (MR/PR, pipelines) porteuses des anciens commits éliminées ; token Telegram révoqué, mots de passe RTSP et `user-4itec` changés (uniques par boîtier, Vaultwarden), clé HMAC régénérée — **rotation attestée par 4itec**. Contrôle `--mirror` sur les deux remotes : 0 occurrence. Constat passé de `Bloquante` à `Conforme`.

**Position du fournisseur et réponse d'audit** : 4itec fait valoir que le dépôt est privé (accès limité aux employés 4itec, base de connaissance de maintenance) et que le déploiement par Nuitka ou Docker+Cython ne copie pas ces valeurs sur la machine cible. **Constaté exact sur l'artefact** : `config/config.ini` à HEAD ne contient aucun secret (`TOKEN=`, `CHAT_ID=`, `LOGIN=`, `PASSWORD=` vides) et le durcissement du build est réel (crédité en *Constats hors référentiel*). **Sans effet sur le verdict** : `CS-113-04` porte sur le dépôt et son historique, pas sur le binaire livré. Le secret reste lisible par quiconque obtient une copie du dépôt — clone, fork, sauvegarde, cache CI, départ d'un collaborateur, changement de visibilité, ou communication du dépôt à l'auditeur Stellantis pour étayer le dossier (`CS-R8-01`). La visibilité privée n'est pas un contrôle de secret ; la norme écrit « ni dans le code ni dans l'historique git », sans exception. De plus, un mot de passe unique documenté et partagé sur tout le parc contredit `CS-113-06` (unicité, changement à la recette, rotation) et `CS-R2-03` (traçabilité d'un compte partagé). Le token Telegram et le mot de passe RTSP présents dans l'historique sont par ailleurs des credentials externes vivants dont la révocation est requise indépendamment de cette discussion. Le mécanisme conforme (`pass`/GPG) est déjà en usage dans le dépôt — il ne s'agit donc pas d'une contrainte technique justifiant une `Dérogation requise`.

### 2. `CS-1143-01` / `CS-R3-01` — Protocoles non chiffrés (IHM, RTSP ; VNC corrigé côté dépôt) — **`Majeure` depuis la révision 4**

**Évolution** : RDP/xrdp — nommément interdit au §1.1.4.3 — a été **abandonné** ; l'accès de maintenance est **TigerVNC** (`scripts/install_vnc_jetson.sh:57` installe `tigervnc-standalone-server`). Le constat n'est plus une non-conformité d'architecture mais de **configuration**.

**VNC — corrigé côté dépôt (révision 5)** : `scripts/install_vnc_jetson.sh:120` lance désormais `vncserver ... -SecurityTypes X509Vnc,RA2ne` — les types `VncAuth`/`None` (session en clair) sont **refusés** ; la session est chiffrée en TLS (certificat auto-généré dans `~/.vnc/`, empreinte à vérifier au 1er accès) ou en RSA-AES. Le script rappelle le contrôle : `vncviewer -SecurityTypes VncAuth` doit échouer. **Reste `Hors dépôt`** : confirmer sur la cible que le TigerVNC installé (1.12) négocie bien X509Vnc/RA2ne. `-localhost no` est conservé (accès borné par UFW au sous-réseau `192.168.3.0/24` + fail2ban) — commenté dans le script.

**Constats résiduels (non corrigés)** :

- IHM de supervision servie en **HTTP non chiffré** (`run.py:32`, `scripts/4isafecross.sh:10`) : transporte les identifiants HTTP Basic et permet la reconfiguration des zones de sécurité.
- Transport RTSP en clair depuis les caméras (`src/camera_manager.py:152`) — flux OT/OT sur le sous-réseau caméra dédié.

**Impact** : sur le segment de maintenance, un tiers ayant un accès local peut lire les identifiants de l'IHM (HTTP clair). Le point-à-point RJ45 et l'air-gap réduisent fortement la vraisemblance ; la recette FOR_509 reste *zero-tolerance* sur le chiffrement.

**Correction restante** :

1. VNC : **vérifier sur la cible** que la session est chiffrée (`vncviewer -SecurityTypes X509Vnc,RA2ne <host>:5999` aboutit, `-SecurityTypes VncAuth` échoue) ; envisager un certificat serveur provisionné (`-X509Cert`/`-X509Key`) pour l'authentification forte à la recette.
2. Placer l'IHM derrière TLS (reverse-proxy local avec certificat interne, ou `ssl_context` Waitress) et la binder sur `eth2`.
3. *(Fait, révisions 5-7 : script renommé `install_xrdp_jetson.sh` → `install_vnc_jetson.sh` ; docs de déploiement fusionnées dans `scripts-deploiement.md` sur le modèle autonome ; RDP/xrdp acté abandonné ; RustDesk documenté comme accès distant provisoire de mise au point, avec sa procédure de retrait à la livraison.)*

---

## Cartographie des flux

État **cible (autonome)**, avec mention des flux limités à la **phase de mise au point (clé 4G)**.

| Sens | Source | Destination | Protocole | Port | Chiffré | Usage | Statut |
|---|---|---|---|---|---|---|---|
| OT→OT | Jetson 4iSafeCross | Caméras IP (`192.168.2.156`, `192.168.2.157`, `eth1`) | RTSP/RTP over TCP | 554 | Non | Réception des flux vidéo H.264 | Nécessaire ; transport non chiffré ; sous-réseau caméra dédié à isoler strictement |
| OT→OT (intra-hôte) | 4iSafeCross (client d'inférence) | Serveur YOLO `inf_jetson_yolo` | HTTP | 8004 (`127.0.0.1`) | Non | `POST` frame → détections | Boucle locale même Jetson (`network_mode: host`) ; ne traverse aucun réseau |
| OT→OT (intra-hôte) | 4iSafeCross | Serveur RF-DETR `inf_jetson_rf-detr` | HTTP | 8002 (`127.0.0.1`) | Non | `POST` frame → détections | Idem (numéros de port divergents entre `config/config.ini`, `README.md` et `docs/security/analyse-risques-cyber.md` — à fixer) |
| IT→OT | PC de maintenance (`192.168.3.x`, `eth2`) | IHM Flask du Jetson (`docker-compose-amd64.yml:6`, `docker-compose-arm64.yml:5`) | HTTP | 5050 | Non | Supervision, édition des zones/masques, toggle détection, réglage des seuils | **Non chiffré, non authentifié par défaut** — à corriger (`CS-1143-01`, `CS-1144-01`, `CS-143-02`) |
| IT→OT | PC de maintenance (`eth2`, `192.168.3.0/24`) | Jetson — accès graphique de maintenance | VNC (TigerVNC) | 5999 | Oui — `-SecurityTypes X509Vnc,RA2ne` forcé (`install_vnc_jetson.sh:120`), à confirmer sur cible | Bureau distant de maintenance — **seul accès d'exploitation** | `CS-1143-01` (`Majeure`) — VNC chiffré côté script ; UFW + fail2ban en place ; contrôle sur cible à faire |
| IT↔OT | Poste 4itec (via 4G/tailnet) | Jetson (RustDesk self-hosted) | RustDesk (propriétaire, chiffré) | serveur relais self-hosted | Oui | Réglage graphique à distance — **mise au point uniquement** | Désinstaller à la livraison + attester à la recette (`CS-1143-04`, `CS-1143-05`) ; procédure dans `scripts-deploiement.md` |
| IT→OT | Poste 4itec | Jetson SSH | SSH v2 | 22 | Oui | Administration, `scripts/deploy-jetson.sh` — mise au point / interventions | UFW restreint à l'IP SSH courante (`install_vnc_jetson.sh:173-177`) — acceptable si borné et local |
| OT→Internet | Jetson | `api.telegram.org` | HTTPS | 443 | Oui | Bot Telegram : alertes + commandes `/take`, `/status` — **mise au point uniquement** | Inerte en cible (pas d'Internet) ; code à **retirer du boot** en RUN (`CS-127-01`) |
| OT→Internet | Jetson (clé 4G) | Registry `registry.gitlab.4itec.ddns.net`, `repo.download.nvidia.com`, `ghcr.io` | HTTPS | 443 | Oui | `docker pull` de l'image, paquets L4T — **mise au point uniquement** | **Fenêtre 4G à déclarer au PIL** (`CS-145-01/02/03`) ; en RUN, déploiement d'image par support local |
| OT→Internet | Jetson (option, clé 4G) | Coordination Tailscale / DERP | WireGuard / HTTPS | 41641/UDP, 443 | Oui | Accès distant optionnel (`install_vnc_jetson.sh --tailscale`) | À **retirer** du livrable RUN |
| — | `eth0` (DHCP) | — | — | — | — | « Réseau principal / accès internet / supervision distante » (`README.md:687`) | **Résolu** : non raccordé en cible ; la doc README doit être mise à jour pour refléter le modèle autonome |
| OT (local) | Jetson | Module relais Yoctopuce Yocto-MaxRelay | USB (lib `yoctopuce`) | — | s.o. | Pilotage des avertisseurs lumineux/sonores | Bibliothèque constructeur officielle |

---

## Constats hors référentiel

- **CI — analyses de sécurité non bloquantes** : `.gitlab-ci.yml` — le job `security:sast` porte `allow_failure: true` et le passage JSON de `bandit`/`pip-audit` est suffixé `|| true`. Les vulnérabilités sont visibles mais ne cassent jamais le pipeline (cohérent avec `TECH_DEBT_AUDIT.md` F043). *(2026-08-31 : ajout d'un job `security:gitleaks` **bloquant** — détection de secrets sur tout l'historique — et d'un hook `.githooks/pre-commit` ; historique purgé le même jour, le job passe au vert. `security:sast` reste à basculer en `allow_failure: false`, cf. `CS-R6-01`.)*
- **CI — runner privilégié** : `.gitlab-ci.yml:77` `docker run --rm --privileged tonistiigi/binfmt:...` ; le runner partage le daemon Docker de l'hôte (`resource_group: docker-host`).
- **CI — token dans une ligne de commande** : `uv pip compile --extra-index-url "https://${GITLAB_DEPLOY_USERNAME_38}:${GITLAB_DEPLOY_TOKEN_38}@..."` expose le token dans l'`argv` du process. Préférer `UV_INDEX_..._PASSWORD` en variable d'environnement.
- **Conteneur root + privilèges maximaux** : aucun `USER` dans le `Dockerfile` ; `privileged: true`, `network_mode: host`, `ipc: host`, `-v /dev:/dev`. Un exploit applicatif s'exécute avec les droits root sur l'hôte Jetson. Ajouter `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `read_only: true` + `tmpfs`, et un utilisateur dédié.
- **Artefacts runtime versionnés** : `db/detections.db` (binaire, actuellement vide) et `licenses/license_state.json` (état lié au `machine_id` `67fbd03f...`, contient un HMAC) sont suivis par git alors que le `README.md:555` demande de ne pas les versionner.
- **Divulgation d'informations** : `/debug_info` (IP, `docker ps`, statut systemd, chemins) et `/status` Telegram exposent l'infrastructure ; plusieurs routes renvoient `str(e)` au client (`src/web/routes_zones_api.py:107`, `src/web/routes_system.py:149`).
- **Absence d'en-têtes de sécurité HTTP** et **pas de protection CSRF** sur les `POST` JSON de l'IHM.
- **`xhost +local:root`** (`autostart/rustdesk-xhost.desktop`) abaisse le contrôle d'accès du serveur X pour root local. Lié à RustDesk → **phase de mise au point uniquement** ; à retirer avec RustDesk à la livraison (procédure documentée dans `docs/deployment/scripts-deploiement.md`).
- **Documentation de déploiement** : les deux docs `script-deploiement.md` / `scripts-deploiement.md` ont été fusionnées (révisions 6-7) dans `docs/deployment/scripts-deploiement.md` — modèle autonome, VNC chiffré, RDP/xrdp abandonné, RustDesk/Tailscale/4G repositionnés comme outils de mise au point avec procédures de retrait. **Reste à corriger** : `README.md` (tableau des ports réseau décrivant `eth0` internet / supervision distante, section Telegram) — à réaligner avant présentation à l'auditeur Stellantis.
- **Points positifs relevés** (à conserver) : rédaction des identifiants RTSP avant journalisation (`src/camera_manager.py:19-27`, commit `27c3349`) ; secrets lus depuis l'environnement avec `.env` gitignoré ; build Docker multi-étapes avec secret BuildKit (pas de token dans les couches d'image) ; UFW `default deny` + fail2ban dans `install_vnc_jetson.sh` ; sonde `/health` distincte du mode fail-safe ; SQL entièrement paramétré.

---

## Points à confirmer hors dépôt

| Chapitre | Objet à vérifier | Interlocuteur |
|---|---|---|
| §1.1.1 / §1.2.1 | Référence Jetson Orin NX / reServer J4012 au catalogue STLA-CS_STD_605.G ; RAM ≥ 8 Go, stockage ≥ 240 Go SSD, CPU/mémoire < 50 % en charge | Référent technique Stellantis |
| §1.1.2 | Bloqueurs de ports mécaniques USB/RJ45/M12, désactivation logicielle des interfaces `eth0`/`eth3`/`eth4` inutilisées en cible | Maintenance Stellantis |
| §1.1.4.1 / §1.2.3 | Version de firmware JetPack/L4T homologuée et **identique sur tout le parc** de boîtiers de même référence (incohérence README 6.2 vs Dockerfile 7.2 à lever) | Référent technique Stellantis |
| §1.1.4.3 / STLA-CS_STD_129 | **Vérifier sur la cible** que la session TigerVNC est effectivement chiffrée (le script force `X509Vnc,RA2ne` ; `vncviewer -SecurityTypes VncAuth <host>:5999` doit échouer) | À contrôler sur cible / 4itec |
| §1.2.2 / §1.4.1 | Hébergement en armoire fermée, local sous contrôle d'accès | Maintenance Stellantis |
| §1.2.4 | Sauvegarde image système **ACRONIS Cyber Protect – Backup**, licence, média bootable, sauvegarde KM0 avant réception | Pilote Stellantis (licence à transmettre à Yassine SALMI) |
| §1.2.5 | Agent **CrowdStrike Falcon** — a priori sans objet (machine autonome non connectée) ; à confirmer | Pilote Stellantis |
| §1.2.6 | **StellarProtect** — Real-time Protection (machine autonome), Application Lockdown, USB Device Control ; le fournisseur ne doit pas disposer des droits de whitelisting USB | Pilote Stellantis |
| §1.2.7 / §1.4.5 | **Fenêtre de connexion 4G de mise au point** : durée maximale, périmètre des flux, retrait physique attesté de la clé à la livraison, aucune donnée de production transmise | Plant IT Leader |
| §1.1.4.1 / §1.2.3 | Canal de mise à jour de sécurité de l'OS Linux dérogé et **procédure hors ligne** pour un boîtier autonome | Référent technique Stellantis |
| §1.2.9 R1 | Classification Stellantis des images de personnes traitées (C2 / C3) | Pilote Stellantis / DPO |
| §1.2.9 R4 | Guides de développement sécurisé Stellantis « Python » et « HTML/JS » (non joints à la note) | Pilote Stellantis |
| §1.2.9 R5 / R8 | Engagement de résultat cybersécurité BUILD/RUN, acceptation des audits QUALYS / tests d'intrusion, certifications (ISO 27001) | Pilote Stellantis (volet contractuel) |
| §1.3 | Consoles de programmation Stellantis : dédiées, non connectées à Internet ni aux réseaux IT, éteintes hors usage, fonction unique | Maintenance Stellantis |
| §1.5 | PC 4itec de mise au point et de maintenance (ouvre les sessions 4G, SSH, VNC, RustDesk) : OS à jour, antivirus **professionnel**, définitions < 7 j, scan complet < 7 j — audit STLA-CS_FOR_502, intervention stoppée si non conforme | 4itec (fournisseur) |
| §2.1 | Checklist de recette : **STLA-CS_FOR_509** (équipement hors PC) — ou **STLA-CS_FOR_317** si le référent requalifie le boîtier en IPC ; auto-contrôle fournisseur puis double contrôle pilote en *zero-tolerance* | Pilote Stellantis |

---

## Ce qui a été écarté

- **`scripts/security_audit.sh` (Telnet, RDP, Avahi, ports `0.0.0.0`)** — script d'audit défensif qui **détecte et propose de désactiver** ces services ; pas un usage. Non retenu, mais confirme que l'équipe connaît ces points.
- **`scripts/latency_report.py:157-158` (`http://{host}:{port}`)** — outil de mesure de latence, ciblant `localhost`/le Jetson ; dossier `scripts/` exclu de l'image (`.dockerignore`). Non embarqué en production.
- **`.gitlab-ci.yml:68,119` `image: docker:25-cli`** — capté par le motif « SMTP en clair » (`:25`) ; tag d'image Docker. Faux positif.
- **`static/css/*.css` `border-radius: …`**, **namespaces**, **`README.md` liens `https://…`** — captés par les motifs « authentification centralisée » / « cryptographie faible » / « appels Internet » ; documentation et CSS. Faux positifs.
- **`utils/utils.py:33-38` — `socket.connect(("8.8.8.8", 80))`** en `SOCK_DGRAM` : `connect()` sur un socket UDP ne fait que fixer le pair par défaut pour lire l'adresse locale via `getsockname()` ; aucun paquet n'est émis vers Google. Signalé pour transparence, non retenu comme appel sortant. À remplacer néanmoins par une lecture d'interface locale.
- **`utils/utils.py:49`, `src/core/gpu_metrics.py:117` — `subprocess`** : arguments en liste, commandes fixes (`docker`, `systemctl`, `tegrastats`), pas de `shell=True`, aucune donnée utilisateur interpolée. Pas d'injection.
- **`templates/index.html` — `innerHTML`** : le code distingue explicitement les chaînes externes (systemctl/docker/IP → `textContent`) des valeurs numériques contrôlées (→ `innerHTML`), avec commentaires à l'appui (`:558`, `:632`). Pas de vecteur XSS retenu.
- **`tools/zone_editor_sandbox.py` — `debug=True`** (console Werkzeug) : bind `127.0.0.1:5051`, et le fichier n'est **pas copié dans l'image** (le `Dockerfile` ne copie que `src/`, `utils/`, `run.py`, `config/`, `templates/`, `static/`, `db/`). Outil de développement uniquement.
- **`licenses/4isafecross.lic`** dans l'historique — blob signé RSA, vérifiable par clé publique et lié au `machine_id` ; pas un secret. Retiré de l'arbre courant et gitignoré. Mentionné mais non retenu comme `CS-113-04`.
- **`db/detections.db`** — inspecté : 0 ligne dans toutes les tables, aucune donnée personnelle. Retenu seulement comme constat hors référentiel.
- **`5d6daad` / `e11c253` (« update with secret », « change username and password for license-validator »)** — inspectés : ils introduisent des **références** à des variables CI (`${GITLAB_DEPLOY_TOKEN_38}`), pas des valeurs. Pas de secret en dur.
- **`cryptography` / `aiohttp`** — retenus sous `CS-R6-01` (avis publics), pas sous `CS-113`.
- **`license-validator 0.2.2`** — code absent du dépôt (registry GitLab privé) ; non auditable ici, signalé comme dépendance à auditer séparément.
- **Constats réseau « distants »** (accès non authentifié depuis un réseau d'usine, exfiltration par balayage) — écartés au titre du modèle de déploiement autonome confirmé ; les constats correspondants sont conservés en `Majeure` pour la fenêtre de mise au point et par principe de défense en profondeur, non en `Bloquante`.

---

## Questions ouvertes

1. **Nature du livrable** : équipement embarqué autonome (recette FOR_509) ou boîtier fonctionnellement IPC (recette FOR_317) ? À arbitrer par le référent technique Stellantis en phase d'étude — un arbitrage rendu à la réception se paie en reprise de conception.
2. ~~Architecture réseau~~ — **résolu (révision 2)** : autonome sans Internet en exploitation ; clé 4G provisoire en mise au point ; accès résiduel RJ45 + RDP.
3. ~~Clé 4G~~ — **résolu (révision 2)** : confirmée, usage limité à la mise au point. Reste à formaliser la dérogation `CS-145-02` et la fenêtre auprès du PIL.
4. **Version de JetPack cible** : 6.2 / L4T 36.4.3 (README) ou 7.2 / L4T r39.2 (Dockerfile ARM64) ? Et quelle version le référent technique homologue-t-il ?
5. **Classification des données** : les images de piétons/opérateurs sont-elles C2 ou C3 au sens Stellantis ? Conditionne l'obligation de chiffrement au repos (`CS-R1-01`).
6. **Chiffrement de la session TigerVNC sur la cible** : le script force `-SecurityTypes X509Vnc,RA2ne` (rév. 5) — reste à confirmer sur le boîtier que le TigerVNC 1.12 installé négocie bien ces types et refuse `VncAuth`.
7. **Nettoyage du livrable RUN** : le client Telegram, RustDesk et l'option Tailscale sont-ils retirés de l'image et de la configuration livrées, ou seulement désactivés ?

---

## Plan de remédiation

### Avant réception sur site (non-conformités bloquantes) — toutes traitées

- [x] Révoquer le token du bot Telegram, changer les mots de passe RTSP et `user-4itec` (un mot de passe **unique par boîtier**), régénérer la clé HMAC de licence *(fait 2026-08-31 — rotation attestée par 4itec)* — `CS-113-04`
- [x] Retirer les identifiants en clair de `README.md:719` et `docs/security/rapport-cybersec.md:143` *(fait — commit `9a02cac`)* — `CS-113-04`
- [x] Purger l'historique git des secrets (`git filter-repo`) ou reconstruire le dépôt *(fait 2026-08-31 — réécriture + force-push GitHub/GitLab, refs internes purgées, vérif 0 occurrence)* — `CS-113-04`
- [x] Remplacer RDP/xrdp par VNC *(fait par le fournisseur — TigerVNC ; reste à forcer le chiffrement de session, désormais `Majeure`, voir ci-dessous)* — `CS-1143-01`

### Avant réception définitive (non-conformités majeures)

- [x] **TigerVNC** : forcer `-SecurityTypes X509Vnc,RA2ne` dans le service ; renommer `install_xrdp_jetson.sh` → `install_vnc_jetson.sh` *(fait 2026-08-31, rév. 5)* — `CS-1143-01`
- [ ] **TigerVNC** : vérifier sur cible que la session est chiffrée (`vncviewer -SecurityTypes VncAuth 127.0.0.1:5999` doit échouer) *(coût : faible)* — `CS-1143-01`
- [ ] Basculer l'IHM en HTTPS/TLS et binder sur `eth2` (`run.py:32`, `scripts/4isafecross.sh:10`) *(coût : moyen)* — `CS-1143-01`, `CS-143-02`
- [ ] Formaliser la dérogation **fenêtre 4G de mise au point** auprès du référent technique et l'expression de besoin auprès du PIL (durée, flux, retrait attesté de la clé, pare-feu hôte actif) *(coût : faible)* — `CS-145-01`, `CS-145-02`, `CS-145-03`, `CS-127-01`, `CS-1143-05`
- [ ] Retirer du livrable RUN : client Telegram (boot), RustDesk, option Tailscale *(coût : faible)* — `CS-127-01`, `CS-127-02`, `CS-1143-04`
- [ ] Rendre l'authentification **obligatoire** (refus de démarrage si `SAFECROSS_AUTH_*` absents) sur toutes les routes d'écriture *(coût : faible)* — `CS-1144-01`
- [ ] Mettre à jour `aiohttp` (≥ 3.14.3) et `cryptography` (≥ 50.0.0), régénérer `uv.lock` ; passer `pip-audit`/`bandit` en `allow_failure: false` *(coût : faible)* — `CS-R6-01`
- [ ] Ajouter un journal d'audit (identité, horodatage, IP, action) sur les écritures et les rejets 401, avec rotation *(coût : moyen)* — `CS-R2-03`, `CS-144-01`
- [ ] Séparer les rôles Administrateur / Opérateur et les appliquer dans le garde d'accès *(coût : moyen)* — `CS-113-02`, `CS-R2-02`
- [ ] Formaliser le motif de l'authentification locale et adresser la dérogation au référent technique, ou intégrer PingFederate *(coût : moyen à élevé)* — `CS-113-01`, `CS-R2-01`
- [ ] Nettoyer le venv de production (`cython`, `setuptools`, `wheel`) et retirer `gstreamer1.0-tools` du stage final *(coût : faible)* — `CS-128-01`
- [ ] Retirer `network_mode: host` / `privileged: true` / `-v /dev:/dev` ; `cap_drop: [ALL]` + capacité minimale ; `no-new-privileges` ; `USER` non-root *(coût : moyen)* — `CS-1143-03`
- [ ] Supprimer l'autologon GDM3, ou le conformer aux trois conditions de la norme *(coût : faible)* — `CS-113-05`
- [ ] Lever l'incohérence de version JetPack (README vs Dockerfile), faire homologuer la version par le référent, documenter le canal de mise à jour L4T **hors ligne** + rollback *(coût : moyen)* — `CS-1141-01`, `CS-1141-02`, `CS-123-03`
- [ ] Confirmer la classification des images avec le pilote ; si ≥ C3, chiffrer `detections/`, `dataset/`, `db/` au repos *(coût : moyen à élevé)* — `CS-R1-01`
- [ ] Produire la cartographie des flux au format Stellantis (base : section ci-dessus) *(coût : faible)* — `CS-143-01`
- [ ] Réaligner `README.md` sur le modèle de déploiement autonome (tableau des ports `eth0`, section Telegram) — `docs/deployment/` fait en rév. 6 *(coût : faible)* — hygiène / `CS-R8-01`
- [ ] Retirer la bannière de version des réponses publiques ; passer `/debug_info` derrière authentification *(coût : faible)* — `CS-R8-01`
- [x] Retirer `licenses/license_state.json` du suivi git ; retirer `licenses/license_state.key` de l'historique *(fait 2026-08-31 — dé-suivi + supprimé de tout l'historique par `git filter-repo --invert-paths`)* — hygiène / `CS-113-04`
- [ ] Ajouter protection CSRF et en-têtes de sécurité HTTP ; demander les guides Stellantis Python et HTML/JS *(coût : faible)* — `CS-R4-01`

### Phase RUN (non-conformités mineures et volet contractuel)

- [x] Détection de secrets : job CI `security:gitleaks` bloquant (scan plein historique) + hook `.githooks/pre-commit` + `.gitleaks.toml` *(fait 2026-08-31 ; historique purgé ; scan CI vert — seul faux positif `admin:mon_mdp` allowlisté ; installer `gitleaks` en local pour activer le hook)* — `CS-113-04`
- [ ] Ajouter `SECURITY.md` + canal de signalement de vulnérabilité *(coût : faible)* — `CS-1141-03`
- [ ] Documenter la procédure d'effacement sécurisé des supports en fin de vie / retour SAV *(coût : faible)* — `CS-R1-03`
- [ ] Mettre en place un export des logs (support amovible ou syslog lors des interventions) *(coût : moyen)* — `CS-R2-04`
- [ ] Sortir `db/detections.db` du suivi git *(coût : faible)* — hygiène
- [ ] Remplacer le `connect(8.8.8.8)` de `get_non_local_ips` par une lecture d'interface locale *(coût : faible)* — hygiène
- [ ] Documenter la matrice de compatibilité OS/runtime et le plan de montée de version *(coût : faible)* — `CS-R7-01`
- [ ] Formaliser l'engagement de résultat cybersécurité et l'acceptation des audits QUALYS *(coût : contractuel)* — `CS-R5-01`, `CS-R8-01`
- [ ] Attester la conformité du PC de mise au point / maintenance 4itec (STLA-CS_FOR_502) *(coût : organisationnel)* — `CS-15-01` à `CS-15-05`
