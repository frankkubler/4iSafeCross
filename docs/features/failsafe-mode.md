# 🔒 Mode Fail-Safe - Système d'Alertes 4iSafeCross

## Vue d'ensemble

Le système **fail-safe** garantit que les alertes visuelles restent **ALLUMÉES par défaut** en cas de dysfonctionnement de l'application. Cette approche inverse la logique traditionnelle pour maximiser la sécurité des piétons.

## 🎯 Principe de Fonctionnement

### Logique Inversée

**AVANT (risqué):**
- ❌ Relais OFF par défaut
- ❌ Application allume les alertes lors de détection
- ❌ **En cas de crash → Alertes ÉTEINTES = DANGER**

**MAINTENANT (sécurisé):**
- ✅ Relais ON par défaut au démarrage
- ✅ Application éteint activement les alertes en l'absence de piéton
- ✅ **En cas de crash → Alertes RESTENT ALLUMÉES = SÉCURITÉ**

## 🔧 Composants du Système

### 1. Initialisation des Relais
**Fichier:** `app.py` (lignes 70-76)

Au démarrage de l'application, tous les relais sont **activés** :
```python
for i in range(len(relays.relays)):
    relays.action_on(i)  # MODE FAIL-SAFE : Alertes ON par défaut
```

### 2. AlertManager - État Initial
**Fichier:** `src/alert_manager.py` (lignes 50-57)

Les relais sont initialisés comme déjà allumés :
```python
self.relay_on[relay_num] = True  # Relais ON par défaut
self.relay_on_time[relay_num] = datetime.now()
```

### 3. Système de Heartbeat
**Fichier:** `app.py` (lignes 85-120)

#### Variables de Surveillance
- `last_heartbeat` : Timestamp du dernier heartbeat reçu
- `application_healthy` : État de santé de l'application
- `HEARTBEAT_TIMEOUT` : 30 secondes (délai avant activation fail-safe)

#### Thread Watchdog
Un thread dédié surveille en permanence la santé de l'application :
```python
def failsafe_watchdog():
    while True:
        time.sleep(5)  # Vérification toutes les 5 secondes
        
        if time_since_heartbeat > HEARTBEAT_TIMEOUT:
            # Maintenir les relais ON en mode fail-safe
            for i in range(len(relays.relays)):
                if not relays.get_relay_state(i):
                    relays.action_on(i)
```

#### Mise à Jour du Heartbeat
Appelé à chaque cycle de détection pour indiquer que l'application fonctionne :
```python
update_heartbeat()  # Appelé dans detection_callback
```

## 📊 API de Monitoring

### Endpoint `/failsafe_status`

Permet de surveiller l'état du système fail-safe en temps réel.

**Exemple de réponse :**
```json
{
  "application_healthy": true,
  "last_heartbeat_seconds_ago": 2.5,
  "heartbeat_timeout": 30,
  "failsafe_mode": "STANDBY",
  "relay_states": {
    "relay_0": "YRelay.STATE_B",
    "relay_1": "YRelay.STATE_B",
    "relay_2": "YRelay.STATE_B"
  },
  "relays_initialized": true,
  "message": "Système opérationnel"
}
```

**En cas de dysfonctionnement :**
```json
{
  "application_healthy": false,
  "last_heartbeat_seconds_ago": 35.2,
  "heartbeat_timeout": 30,
  "failsafe_mode": "ACTIVE",
  "relay_states": {
    "relay_0": "YRelay.STATE_B",
    "relay_1": "YRelay.STATE_B",
    "relay_2": "YRelay.STATE_B"
  },
  "relays_initialized": true,
  "message": "⚠️  MODE FAIL-SAFE ACTIF - Alertes maintenues ON"
}
```

## 🚨 Scénarios de Sécurité

### Scénario 1 : Fonctionnement Normal
1. Application démarre → Relais ON
2. Détection active → Heartbeat régulier
3. Aucun piéton détecté → Application éteint les relais
4. Piéton détecté → Application rallume les relais

### Scénario 2 : Crash de l'Application
1. Application crash → Heartbeat s'arrête
2. Watchdog détecte l'absence de heartbeat après 30s
3. **Relais restent ON** (fail-safe activé)
4. Alertes visuelles continuent de fonctionner

### Scénario 3 : Perte de Connexion Caméra (toutes les caméras)
1. Connexion caméra perdue → `CameraManager._mark_offline()` invalide la dernière image (`frames[cid] = None`)
2. Le thread d'inférence n'a plus d'image → le callback de détection n'est plus appelé → Heartbeat s'arrête
3. Après 30s → Mode fail-safe activé
4. **Relais forcés ON** par sécurité

> ⚠️ **Avant v3.0.2, ce scénario ne fonctionnait pas.** La dernière image reçue restait en
> mémoire ; le thread d'inférence continuait de la traiter (aucun mouvement → callback avec
> détections vides → heartbeat émis). Une perte totale des caméras laissait l'application
> « saine » et les relais **éteints**. L'invalidation de l'image à la perte corrige ce point.

### Scénario 5 : Perte d'une caméra parmi plusieurs (fail-safe par caméra, v3.0.2)
Le heartbeat est émis **par caméra** (`update_heartbeat(cid)`, `state.last_heartbeat_by_cam`).
Le watchdog évalue chaque caméra indépendamment du niveau global :
1. La caméra `k` ne fournit plus d'image → son callback n'est plus appelé → son heartbeat cesse
2. Après 30s → `camera_failsafe[k] = True` ; **seuls les relais des zones de la caméra `k`**
   sont forcés ON (`AlerteManager.force_relays_on`), les autres caméras continuent normalement
3. Un relais partagé entre une zone de `k` et une zone d'une autre caméra est forcé ON (choix
   prudent)
4. Retour du flux → heartbeat de `k` repris → `release_forced_relays` : extinction différée
   normale (11 s minimum, annulée si une personne est détectée)

`/failsafe_status` expose `cameras.camera_<k>.{failsafe, last_heartbeat_seconds_ago, relays}` ;
`/health` passe `failsafe_active` à `true` dès qu'une caméra est en fail-safe.

> Avant v3.0.2, seul un heartbeat global existait : tant qu'une caméra fournissait des images,
> la perte d'une autre n'activait rien — ses relais restaient éteints et ses zones sans
> surveillance.

### Démarrage sans caméra : extinction initiale conditionnée (v3.0.2)
`startup_relay_off()` n'éteint les relais qu'après **au moins un heartbeat depuis le boot**
(`state.heartbeat_received`). Sans image caméra, les relais restent ON ; au premier heartbeat,
une nouvelle période de grâce `STARTUP_GRACE_PERIOD` s'écoule avant l'extinction initiale.

> Avant v3.0.2, un démarrage sans caméra éteignait les relais à t≈15 s et le watchdog ne les
> rallumait qu'à t≈30–35 s : 15 à 20 s d'alertes éteintes.

### Cohérence état interne / état physique
Tout forçage fail-safe passe par `AlerteManager.force_relays_on`, qui met à jour `relay_on` et
`relay_on_time`. L'ancien watchdog appelait `relays.action_on()` directement : après retour à
la normale, `_delayed_off_relay` voyait `relay_on = False` et n'éteignait jamais ces relais.

### Scénario 4 : Thread d'Inférence Bloqué
1. Thread d'inférence se bloque
2. Pas de nouvelles détections → Heartbeat s'arrête
3. Watchdog active le fail-safe après 30s
4. **Relais forcés à ON**

## 🔍 Logs et Diagnostic

### Au Démarrage
```
⚠️  MODE FAIL-SAFE ACTIVÉ : 3 relais allumés par défaut
🔒 Watchdog fail-safe démarré - Surveillance active
```

### Caméra absente au démarrage
```
Ping RTSP échoué pour rtsp://***@192.168.0.60:554/stream1 (tentative 1)
Ping RTSP OK pour rtsp://***@192.168.0.61:554/stream1 (tentative 1)
Caméra 0 (192.168.0.60) absente au démarrage : conservée à l'index 0 (zones _cam0), reconnexion en boucle, relais de ses zones sous fail-safe.
Caméras (index = position dans config.ini) : 0=192.168.0.60, 1=192.168.0.61
⚠️  FAIL-SAFE caméra 0 : aucune image depuis 30s - relais [0, 1] forcés ON (zones de cette caméra)
```

**L'index d'une caméra est sa position dans `[RTSP] HOST` de `config.ini`**, et rien
d'autre. C'est lui que portent les zones (`zone*_cam<i>`), les masques, les relais, la
vue « Camera i+1 » de l'IHM, l'éditeur de zones et le fail-safe par caméra. Une caméra
absente au démarrage **garde sa place** : son pipeline est relancé en boucle jusqu'au
retour du flux, et d'ici là le watchdog force les relais de ses zones — elle n'est
jamais hors surveillance. L'IHM affiche l'hôte à côté de « Camera N » pour que
l'opérateur voie quelle caméra il regarde.

> Avant ce correctif (v3.0.2 et antérieures), le démarrage ne conservait que les caméras
> ayant répondu, **dans l'ordre où elles répondaient** : la première devenait l'index 0
> et héritait des zones, relais et vue de la caméra configurée en premier — un démarrage
> sur deux avec deux caméras de latence voisine, et systématiquement si la première était
> éteinte. Une zone dessinée dans l'éditeur pendant un tel démarrage était enregistrée
> sous le mauvais `_cam`. Tests : `test_camera_order.py`.

### Fonctionnement Normal
```
[DEBUG] Heartbeat mis à jour - Application opérationnelle
```

### Activation du Fail-Safe
```
⚠️  ALERTE FAIL-SAFE : Aucun heartbeat depuis 32.5s - Maintien des relais ON
🔧 Réactivation du relais 0 en mode fail-safe
🔧 Réactivation du relais 1 en mode fail-safe
🔧 Réactivation du relais 2 en mode fail-safe
```

### Retour à la Normale
```
✅ Application de nouveau opérationnelle (heartbeat reçu)
```

## 🛠️ Configuration

### Modifier le Timeout
Dans `app.py`, ajuster la constante :
```python
HEARTBEAT_TIMEOUT = 30  # Secondes avant activation fail-safe
```

**Recommandations :**
- **30s** (défaut) : Équilibre entre réactivité et faux positifs
- **15s** : Plus réactif, risque de faux positifs
- **60s** : Plus tolérant, moins réactif

### Désactiver le Fail-Safe (NON RECOMMANDÉ)
Pour désactiver le mode fail-safe (⚠️ réduit la sécurité) :
```python
# Commenter le démarrage du watchdog dans app.py
# failsafe_thread = threading.Thread(target=failsafe_watchdog, daemon=True)
# failsafe_thread.start()
```

## 📈 Monitoring Recommandé

### Supervision avec cURL
```bash
# Vérifier l'état du fail-safe toutes les 10 secondes
watch -n 10 'curl -s http://localhost:5050/failsafe_status | jq'
```

### Intégration avec Prometheus
```python
# Exporter les métriques fail-safe
application_healthy_gauge = Gauge('failsafe_application_healthy', 'Application health status')
heartbeat_age_gauge = Gauge('failsafe_heartbeat_age_seconds', 'Time since last heartbeat')
```

### Alertes Telegram
Le système peut être configuré pour envoyer des alertes Telegram lors de l'activation du mode fail-safe.

## ⚙️ Tests

### Test Manuel du Fail-Safe
1. Démarrer l'application normalement
2. Vérifier que les relais sont ON : `curl http://localhost:5050/failsafe_status`
3. Simuler un blocage en ajoutant un `time.sleep(60)` dans la boucle de détection
4. Observer l'activation du fail-safe dans les logs après 30s

### Test de Crash
1. Démarrer l'application
2. Simuler un crash avec `kill -9 <PID>`
3. Vérifier que les relais restent physiquement allumés

## 🔐 Sécurité et Conformité

Le mode fail-safe garantit la conformité avec les normes de sécurité industrielles qui exigent un comportement sûr par défaut en cas de défaillance système.

### Normes Applicables
- **ISO 13849** : Sécurité des machines
- **IEC 61508** : Sécurité fonctionnelle
- **Principe du fail-safe** : L'état de défaillance doit être l'état le plus sûr

## 📝 Maintenance

### Vérifications Régulières
- [ ] Tester le fail-safe manuellement une fois par mois
- [ ] Vérifier les logs pour détecter des activations anormales
- [ ] Monitorer l'endpoint `/failsafe_status`
- [ ] Valider le bon fonctionnement des relais physiques

### En cas de Problème
1. Consulter les logs : `journalctl -u 4isafecross.service -f`
2. Vérifier l'état : `curl http://localhost:5050/failsafe_status`
3. Redémarrer si nécessaire : `sudo systemctl restart 4isafecross.service`
4. Les relais resteront ON pendant le redémarrage (sécurité garantie)

## 📞 Support

Pour toute question ou problème concernant le mode fail-safe, consultez la documentation technique ou contactez l'équipe de développement.

---

**Version:** 1.1.0  
**Date:** 7 janvier 2026  
**Auteur:** 4iTec - Système de Sécurité Piéton
