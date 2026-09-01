# Politique de sécurité — 4iSafeCross

4iSafeCross est un système de sécurité industrielle (détection de piétons en zone
de circulation de chariots élévateurs). Toute vulnérabilité pouvant conduire à
une **non-détection** ou à une **désactivation non autorisée** de la fonction de
sécurité est traitée en priorité.

## Signaler une vulnérabilité

- **Contact** : `security@4itec.fr`
- **Chiffrement** : sur demande, une clé PGP est fournie pour l'échange de
  détails sensibles.
- **Ne pas** ouvrir d'issue publique pour une vulnérabilité non corrigée.

Merci d'inclure : version / commit concerné, description, impact estimé, étapes
de reproduction, et toute configuration nécessaire.

## Délais indicatifs

| Étape | Délai visé |
|---|---|
| Accusé de réception | 5 jours ouvrés |
| Évaluation initiale + sévérité | 15 jours ouvrés |
| Correctif ou plan d'atténuation | selon sévérité — critique : au plus vite, avec correctif hors ligne poussé aux boîtiers du parc lors de la prochaine intervention |

## Périmètre

Sont dans le périmètre :

- le code applicatif (`src/`, `utils/`, `run.py`) et sa configuration ;
- l'image Docker de production et le `Dockerfile` ;
- les scripts de déploiement et de durcissement (`scripts/`) ;
- la chaîne CI/CD (`.gitlab-ci.yml`).

Sont **hors périmètre** de ce dépôt (traités par 4itec / le référent Stellantis) :

- le firmware JetPack / L4T du boîtier (voir
  [`docs/deployment/maj-l4t-hors-ligne.md`](docs/deployment/maj-l4t-hors-ligne.md)) ;
- les serveurs d'inférence externes (`inf_jetson_yolo`, `inf_jetson_rf-detr`) ;
- le PC de maintenance 4itec (audit `STLA-CS_FOR_502`).

## Maintien en condition de sécurité (RUN)

- Dépendances Python : `pip-audit` + `bandit` **bloquants** en CI
  (`.gitlab-ci.yml`, job `security:sast`) ; détection de secrets `gitleaks`
  bloquante sur tout l'historique.
- OS / BSP : veille trimestrielle des bulletins NVIDIA Jetson et Ubuntu USN,
  application hors ligne — voir
  [`docs/deployment/maj-l4t-hors-ligne.md`](docs/deployment/maj-l4t-hors-ligne.md).
- Revue de sécurité de référence : [`CYBER_AUDIT.md`](CYBER_AUDIT.md)
  (référentiel fournisseur Stellantis STLA-CS_STD_004).

## Conformité

Ce dépôt fait l'objet d'un audit continu contre le référentiel
**STLA-CS_STD_004** — voir [`CYBER_AUDIT.md`](CYBER_AUDIT.md) pour l'état par
exigence, et le plan de remédiation.
