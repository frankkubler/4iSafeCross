# Rapport synthétique sur app.py (4iSafeCross)

## 1. Rôle principal
`app.py` est le point d’entrée de l’application Flask qui orchestre la gestion des caméras, l’inférence, la détection, le pilotage des relais, l’intégration Telegram, et l’interface web.

---

## 2. Initialisation
- **Log & Relais** : Configuration du logging, extinction de tous les relais au démarrage pour garantir la sécurité.
- **Bot Telegram** : Démarrage du bot dans un thread dédié.
- **Zones** : Chargement des zones de détection par caméra.
- **Alerte** : Instanciation de `AlerteManager` pour la gestion des alertes et relais.

---

## 3. Gestion des caméras et détection
- **RTSP** : Vérification des flux RTSP, filtrage des caméras disponibles.
- **CameraManager** : Instancie la gestion des caméras.
- **Threads d’inférence** : Un thread par caméra pour l’analyse en continu.
- **Détection** : Callback par caméra, gestion des zones, stockage des détections, déclenchement des alertes.

---

## 4. Interface Web (Flask)
- **Vidéo** : Affichage du flux vidéo avec overlays (zones, détections, état mouvement).
- **Contrôles** : API pour modifier les paramètres caméra (exposition, luminosité, etc.).
- **Activation/désactivation** : Endpoints pour activer/désactiver la détection et le stream.
- **Alertes Telegram** : Activation/désactivation via API.
- **Diagnostics** : Endpoint pour infos système (RAM, CPU, disque, IP, Docker, service).
- **Images de détection** : Liste et accès aux dernières images détectées.
- **Zones** : API pour modifier dynamiquement les zones de détection.

---

## 5. Sécurité et robustesse
- **Extinction des relais au démarrage** pour éviter tout état indésirable.
- **Gestion multi-thread** pour l’inférence et le bot Telegram.
- **Verrouillage** (`threading.Lock`) pour l’accès concurrent aux détections.

---

## 6. Points d’intégration
- **AlerteManager** : Centralise la logique d’alerte et de pilotage des relais.
- **Bot Telegram** : Notifications et interaction utilisateur.
- **CameraManager** : Abstraction des flux vidéo.

---

## 7. Conclusion
Le fichier `app.py` structure l’application autour de la sécurité, la modularité et la réactivité : chaque composant (caméra, relais, bot, zones) est isolé et piloté via des threads ou des callbacks, avec une interface web complète pour le contrôle et le diagnostic.

---
