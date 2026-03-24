# Registre des activités de traitement — Art. 30 RGPD
## Système 4iSafeCross — Détection de présence en zone de circulation industrielle

> Document conforme au Règlement (UE) 2016/679 (RGPD) et à la Loi Informatique et Libertés modifiée.
> À conserver par le responsable de traitement et à présenter sur demande à la CNIL.

---

## 1. Identification du responsable de traitement

| Champ | Valeur |
|---|---|
| **Dénomination** | *(Nom de l'entreprise utilisatrice à compléter)* |
| **Adresse** | *(Adresse du site industriel à compléter)* |
| **Représentant légal** | *(Nom, Prénom, Fonction à compléter)* |
| **Contact DPO / référent RGPD** | *(Email / téléphone à compléter — ou mention "non obligatoire, effectif < 250")* |
| **Sous-traitant technique** | 4iTec (fournisseur du système 4iSafeCross) |

---

## 2. Description du traitement

### 2.1 Dénomination du traitement

**Vidéosurveillance par intelligence artificielle pour la prévention des accidents en zone de circulation d'engins de manutention**

### 2.2 Finalité(s) du traitement

| Finalité | Description |
|---|---|
| **Principale — Sécurité physique** | Détection automatique de la présence de piétons dans des zones de croisement avec des chariots élévateurs, afin de déclencher une alerte lumineuse (projecteur/relais) avertissant les conducteurs d'engins |
| **Secondaire — Classification comportementale** | Analyse de la posture de la personne détectée (debout statique, en marche, assis dans un chariot à fourche) afin de discriminer les faux positifs et d'affiner le niveau d'alerte |
| **Tertiaire — Maintenance / debug** | Conservation temporaire d'images annotées pour le diagnostic technique du système par les techniciens de maintenance |

### 2.3 Base légale (Art. 6 RGPD)

**Base retenue : Intérêt légitime — Art. 6-1-f RGPD**

> « Le traitement est nécessaire aux fins des intérêts légitimes poursuivis par le responsable du traitement ou par un tiers, à moins que ne prévalent les intérêts ou les libertés et droits fondamentaux de la personne concernée. »

**Justification de l'intérêt légitime :**

- Le site industriel met en présence des piétons (opérateurs, visiteurs) et des engins de manutention lourds (chariots élévateurs) dans des zones à visibilité réduite.
- Le risque d'accident mortel est documenté (statistiques AT-MP, INRS) et constitue une obligation légale de sécurité pour l'employeur (Art. L4121-1 Code du travail).
- La finalité poursuivie — prévenir les collisions — est proportionnée et ne peut pas être atteinte par un moyen moins intrusif de façon équivalente (capteurs de présence inadaptés à la géométrie des lieux, marquage au sol insuffisant, etc.).
- Le traitement ne vise pas à identifier nominativement les personnes, à les surveiller dans le temps ou à établir un profil comportemental individuel.

**Test de mise en balance :**

| Critère | Appréciation |
|---|---|
| Intérêt légitime réel et présent | ✅ Obligation sécurité employeur — risque d'accident grave avéré |
| Nécessité du traitement | ✅ Pas d'alternative technique équivalente identifiée |
| Proportionnalité | ✅ Limitation aux zones de croisement uniquement — pas de surveillance générale |
| Attentes raisonnables des personnes | ✅ Panneau d'information en place — déclaration au CSE effectuée |
| Risque résiduel pour les personnes | ✅ Faible — pas d'identification individuelle, pas de profilage, pas de transmission externe |

### 2.4 Données traitées

| Catégorie | Données | Caractère |
|---|---|---|
| **Flux vidéo temps réel** | Image vidéo brute issue des caméras RTSP | Transitoire — traitée en mémoire vive uniquement, non persistée |
| **Détection de présence** | Coordonnées de zone de détection (numéro de zone, caméra) | Opérationnel — utilisé pour activer le relais |
| **Analyse de posture** | Classification comportementale : debout statique / en marche / assis dans un engin | Accessoire — traité en mémoire vive, non stocké en base |
| **Événements relais** | Horodatage d'allumage et d'extinction du projecteur d'alerte, durée, zone déclenchante | Persisté en base SQLite (`relay_events`) |
| **Images de détection (debug)** | Capture JPEG annotée lors d'une détection confirmée (max 30 fichiers, 1 par caméra toutes les 120 s) | Temporaire — suppression automatique au-delà de `DETECTION_FILES_KEEP_DAYS` jours ou `DETECTION_FILES_MAX` fichiers |

**Données NON collectées :**
- Aucune reconnaissance faciale
- Aucune identification nominative des personnes
- Aucune base de données de personnes (ni empreints, ni biométrie identifiante)
- Aucune transmission vers un cloud ou serveur distant

### 2.5 Personnes concernées

- Salariés de l'entreprise utilisatrice évoluant dans les zones de circulation couvertes
- Prestataires et visiteurs accédant à ces zones

### 2.6 Destinataires des données

| Destinataire | Données | Modalité |
|---|---|---|
| Système interne (traitement IA local) | Flux vidéo temps réel | Traitement en mémoire vive, réseau local isolé |
| Technicien de maintenance | Images debug, logs applicatifs | Accès physique local (connexion RJ45) uniquement |
| *(Option)* Groupe Telegram de supervision | Image JPEG annotée lors d'une alerte | Uniquement si `TELEGRAM_ENABLED = true` en config — HTTPS |

> ⚠️ En configuration de production standard (`TELEGRAM_ENABLED = false`), aucune donnée ne quitte le réseau local du site, pas de clé 4G branchée au PC IA.

---

## 3. Durées de conservation

| Catégorie de données | Durée | Mécanisme de suppression |
|---|---|---|
| Flux vidéo temps réel | **Aucune persistance** — traitement en RAM uniquement | Volatil — effacé en continu |
| Analyse de posture | **Aucune persistance** — résultat calculé en mémoire | Volatil |
| Événements relais (BD SQLite) | **Durée à définir par le responsable de traitement** *(recommandation : 12 mois pour suivi sécurité)* | Suppression manuelle ou purge périodique à implémenter |
| Images debug (`detections/`) | **`DETECTION_FILES_KEEP_DAYS` jours** (défaut : 30 jours) ET maximum **`DETECTION_FILES_MAX` fichiers** (défaut : 30) | Suppression automatique par le système |
| Logs applicatifs | **`LOGS_KEEP_DAYS` jours** (configurable) | Rotation automatique |

---

## 4. Mesures de sécurité

| Mesure | Mise en œuvre |
|---|---|
| **Isolation réseau** | Système non connecté à internet en production — accès uniquement par câble RJ45 local |
| **Traitement IA local** | Aucun envoi de données vidéo vers l'extérieur |
| **Limitation de la collecte** | Pas de stockage du flux vidéo continu — seules les images d'alerte sont conservées temporairement |
| **Rétention automatique** | Suppression automatique des images au-delà du seuil configuré |
| **Masques de zone** | Zones sensibles (vestiaires, bureaux, etc.) peuvent être masquées en configuration |
| **Déclaration CSE** | Consultation préalable du Comité Social et Économique effectuée |
| **Information des personnes** | Panneau de signalisation physique en place sur le site |

---

## 5. Transferts hors UE

**Aucun transfert hors Union Européenne.**

Le traitement est intégralement réalisé sur un équipement local installé sur le site. En configuration standard de production, aucune donnée n'est transmise à des tiers. En cas d'activation de l'alerte Telegram, les données transitent via les serveurs Telegram (politique de confidentialité Telegram applicable — siège social aux Émirats Arabes Unis / infrastructure UE).

---

## 6. Droits des personnes concernées

Conformément aux Articles 15 à 22 du RGPD, toute personne concernée peut exercer ses droits (accès, rectification, effacement, opposition, limitation) auprès du responsable de traitement :

**Contact : *(adresse email ou postale du responsable à compléter)***

> Note : compte tenu de la nature du traitement (aucune identification individuelle, pas de base de données nominative), l'exercice du droit d'accès ou d'effacement est de facto sans objet pour la grande majorité des données traitées, qui sont soit volatiles soit agrégées (événements relais sans identifiant de personne).

---

---

# Analyse d'Impact relative à la Protection des Données (AIPD) — Art. 35 RGPD
## Système 4iSafeCross — Analyse de posture en zone industrielle

> L'AIPD est **recommandée** pour tout traitement de vidéosurveillance systématique d'un lieu accessible, et **obligatoire** dès lors que le traitement est susceptible d'engendrer un risque élevé pour les droits et libertés des personnes (Art. 35-1 RGPD, liste CNIL du 11 octobre 2018).
>
> **Conclusion préliminaire** : le présent traitement n'entre pas dans les cas d'AIPD obligatoire au sens strict (pas de reconnaissance faciale, pas d'identification biométrique, pas de surveillance à grande échelle). L'AIPD ci-dessous est réalisée à titre préventif en raison de l'utilisation de l'analyse de posture.

---

## A. Description du traitement et nécessité de l'AIPD

### A.1 Nature du traitement

Le système analyse en temps réel les flux vidéo de caméras positionnées en zones de croisement piétons/engins. Pour chaque détection de personne confirmée, un modèle d'estimation de pose (keypoints squelettaux COCO-17) classifie la posture :

- **Debout statique** → personne immobile dans la zone de danger → alerte maintenue
- **En marche** → personne en déplacement → alerte déclenchée
- **Assis dans un engin** → conducteur de chariot à fourche → alerte non déclenchée (le conducteur n'est pas un piéton en danger)

Cette classification sert exclusivement à **discriminer les faux positifs** (conducteur assis dans son chariot détecté comme "personne") et à éviter des alertes inutiles perturbant l'activité.

### A.2 Nécessité et proportionnalité

| Critère | Appréciation |
|---|---|
| Finalité déterminée et explicite | ✅ Sécurité physique — prévention collision |
| Minimisation des données | ✅ Keypoints calculés en mémoire, non stockés — seule la classe comportementale est utilisée |
| Exactitude | ✅ Seuil de confiance configurable (défaut 0.7) |
| Limitation de la conservation | ✅ Résultat volatil (non persisté) |
| Sécurité | ✅ Traitement 100% local |

---

## B. Évaluation des risques

### B.1 Risque 1 — Accès non autorisé aux images de debug

| | |
|---|---|
| **Description** | Un tiers accédant physiquement au boîtier ou à la connexion RJ45 pourrait consulter les images JPEG stockées dans `detections/` |
| **Vraisemblance** | Faible — accès physique requis, réseau isolé |
| **Impact** | Modéré — images annotées de personnes dans leur environnement de travail |
| **Mesure existante** | Rétention limitée (30 jours / 30 fichiers), accès physique restreint au boîtier |
| **Mesure complémentaire recommandée** | Chiffrement du répertoire `detections/` au niveau OS (LUKS) optionnel |
| **Risque résiduel** | **Faible** |

### B.2 Risque 2 — Détournement de finalité de l'analyse de posture

| | |
|---|---|
| **Description** | L'analyse de posture pourrait être réutilisée pour surveiller les comportements des salariés (respect des consignes, temps d'inactivité, etc.) |
| **Vraisemblance** | Faible — le résultat de classification n'est pas stocké et n'est pas accessible via l'interface |
| **Impact** | Élevé — surveillance comportementale des salariés contraire au droit du travail |
| **Mesure existante** | Résultat de pose non persisté, non affiché dans l'interface hormis en flux vidéo temps réel |
| **Mesure complémentaire recommandée** | Documenter contractuellement l'interdiction d'usage à des fins de contrôle de l'activité des salariés |
| **Risque résiduel** | **Faible sous réserve de l'engagement contractuel** |

### B.3 Risque 3 — Transmission d'images via Telegram

| | |
|---|---|
| **Description** | Si Telegram est activé (`TELEGRAM_ENABLED = true`), des images de personnes sont transmises vers des serveurs Telegram potentiellement hors UE |
| **Vraisemblance** | Conditionnelle — désactivé par défaut en production |
| **Impact** | Modéré — images de personnes transmises à un tiers |
| **Mesure existante** | Désactivé par défaut, contrôlé par config, transmission HTTPS |
| **Mesure complémentaire recommandée** | En cas d'activation, informer les personnes concernées et documenter la base légale spécifique |
| **Risque résiduel** | **Négligeable en configuration standard (désactivé)** |

### B.4 Risque 4 — Utilisation des keypoints comme données biométriques

| | |
|---|---|
| **Description** | Les keypoints COCO-17 (17 points squelettaux) pourraient théoriquement être utilisés pour ré-identifier des individus par leur démarche (gait recognition) |
| **Vraisemblance** | Très faible — non implémenté, pas de stockage des keypoints bruts, pas de base de référence |
| **Impact** | Élevé si mis en œuvre — données biométriques Art. 9 RGPD |
| **Mesure existante** | Keypoints calculés et utilisés uniquement pour la classification posture — non stockés, non transmis |
| **Mesure complémentaire recommandée** | Vérifier régulièrement que `insert_detection()` reste commenté en revue de code |
| **Risque résiduel** | **Très faible** |

---

## C. Conclusion de l'AIPD

| Risque | Niveau résiduel |
|---|---|
| Accès non autorisé aux images debug | Faible |
| Détournement vers surveillance comportementale | Faible (sous engagement contractuel) |
| Transmission Telegram | Négligeable (désactivé en production) |
| Ré-identification biométrique par keypoints | Très faible |

**→ Le traitement peut être mis en œuvre.** Les risques résiduels identifiés sont de niveau faible à négligeable compte tenu des mesures en place. Une consultation préalable de la CNIL (Art. 36 RGPD) n'est pas requise.

---

## D. Engagements et révision

| Point | Engagement |
|---|---|
| **Usage de l'analyse de posture** | Exclusivement pour la discrimination piéton/conducteur d'engin — aucun usage de contrôle de l'activité des salariés |
| **Révision du document** | À revoir en cas d'évolution du système (nouvelles caméras, activation Telegram en production, ajout de fonctionnalités de stockage) |
| **Date de réalisation** | Mars 2026 |
| **Prochain réexamen** | Mars 2027 (ou avant si évolution significative du traitement) |
| **Signataire responsable de traitement** | *(Nom, Prénom, Fonction — signature à apposer)* |

---

*Document établi conformément aux lignes directrices du Groupe de travail Article 29 (WP248 rev.01) et à la doctrine CNIL sur la vidéosurveillance en milieu de travail.*
