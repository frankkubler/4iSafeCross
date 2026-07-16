# AGENTS.md — 4iSafeCross

Guide minimal pour agents IA travaillant sur ce repository.

## Contexte Projet

Application Flask de securite industrielle (vision + alertes) pour Jetson, avec:
- supervision multi-cameras RTSP,
- inference distante (serveurs YOLO / pose / RF-DETR),
- pilotage relais Yoctopuce,
- interface web de supervision et d'edition de zones.

Points d'entree principaux:
- [run.py](run.py) (point d'entree unique)
- [src/core/bootstrap.py](src/core/bootstrap.py) (sequence de boot, ordre critique fail-safe)
- [src/web/app_factory.py](src/web/app_factory.py) (blueprints Flask, URLs sans prefixe)
- [src/core/state.py](src/core/state.py) (etat partage singleton)
- [src/inference.py](src/inference.py)
- [src/alert_manager.py](src/alert_manager.py)
- [src/relay_pilot.py](src/relay_pilot.py)
- [config/config.ini](config/config.ini)

## Couplage Inter-Projets

- 4iSafeCross consomme des APIs d'inference externes via `URL_YOLO`/`FONCTION_YOLO` et `URL_RFDETR`/`FONCTION_RFDETR` (voir [utils/constants.py](utils/constants.py)).
- Les changements de contrat de reponse cote serveurs d'inference doivent etre coordonnes avec [src/inference.py](src/inference.py).
- Repositories lies: `inf_jetson_yolo` et `inf_server` (ou equivalent RF-DETR selon deploiement).

## Commandes Essentielles

- Run (production et dev) Flask/Waitress: `python run.py`
- Tests rapides:
  - `python test_detections_format.py`
  - `python test_zone_editor.py`

## Endpoints Critiques

- `GET /`
- `GET /video_feed/<cid>`
- `GET /failsafe_status`
- `GET /cache_stats`
- `GET /api/inference/stats`
- `GET /api/zones/<cid>`
- `POST /api/zones/<cid>`
- `GET /api/masks/<cid>`
- `POST /api/masks/<cid>`
- `GET /api/relay_positions/<cid>`
- `POST /api/relay_positions/<cid>`

## Conventions de Modification

- Preserver les contrats JSON utilises par le frontend et les integrations locales.
- Ne pas degrader la logique fail-safe (heartbeat, relais ON au demarrage, watchdog).
- Eviter les regressions de latence dans le pipeline frame/inference.
- Preferer `logging` aux nouveaux `print()`.
- Si les endpoints changent, synchroniser [README.md](README.md), les docs impactees et les fichiers de customisation.
- Si le format des detections entrantes change (cles/types), synchroniser aussi les repos serveurs d'inference et les tests associes.

## Zones Sensibles

- `config/` : parametres runtime critiques (zones, masques, relais, RTSP).
- `.env` et `.env.example` : secrets et variables d'environnement.
- `db/` : donnees SQLite de detections.
- `dataset/` : donnees collectees.
- `scripts/` : services/deploiement systeme.

## Checklist Avant PR

- L'application demarre sans erreur sur la cible nominale.
- Les routes modifiees repondent sans erreur 500 sur cas nominal.
- Les tests de base passent (`test_detections_format.py`, `test_zone_editor.py` selon impact).
- Aucun changement accidentel dans `config/`, `db/`, `dataset/`, `scripts/`.
- Le couplage API vers les serveurs d'inference est verifie (URLs/fonctions valides et contrat de payload compatible).

## Policy Commune (Harmonisee)

- Securite: toute commande destructive ou suppression ciblee d'actifs sensibles requiert confirmation explicite utilisateur (mode ask via hooks).
- Stabilite API: conserver les schemas de reponse JSON des endpoints publics, sauf demande explicite de breaking change.
- Validation minimale: executer un smoke test API avant PR et consigner les routes en echec si present.
- Observabilite: utiliser `logging` et conserver des logs exploitables pour diagnostic.
- Documentation: toute modification d'endpoint doit etre refletee dans README/docs et customisations associees.
