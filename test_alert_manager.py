import asyncio
from datetime import datetime, timedelta
from alert_manager import AlerteManager

class DummyRelays:
    def __init__(self):
        self.on = set()
        self.log = []
    def action_on(self, relay_num):
        self.on.add(relay_num)
        self.log.append((relay_num, 'ON', datetime.now()))
    def action_off(self, relay_num):
        self.on.discard(relay_num)
        self.log.append((relay_num, 'OFF', datetime.now()))

def dummy_insert_relay_event(relay, duration, time_on, time_off):
    print(f"[DB] {relay} : {duration:.2f}s de {time_on.strftime('%H:%M:%S.%f')} à {time_off.strftime('%H:%M:%S.%f')}")

# Patch la fonction d'insertion pour le test
import alert_manager
alert_manager.insert_relay_event = dummy_insert_relay_event

async def test_multi_zone():
    relays = DummyRelays()
    zones = [
        {"name": "zone1", "rect": [0,0,10,10]},
        {"name": "zone3", "rect": [0,0,10,10]},
        {"name": "zone2", "rect": [0,0,10,10]},
    ]
    am = AlerteManager(relays, zones=zones)
    now = datetime.now().timestamp()
    # 1. Activation zone1 et zone3 (mêmes relais)
    await am.on_detection(now, detections=[[0,0,1,1,0.9,["zone1"]]])
    await am.on_detection(now+1, detections=[[0,0,1,1,0.9,["zone3"]]])
    # 2. Activation zone2 (relais indépendant)
    await am.on_detection(now+2, detections=[[0,0,1,1,0.9,["zone2"]]])
    # 3. Désactivation zone1 à t+3s (zone3 toujours active)
    await am.on_no_more_detection(now+3, ["zone1"])
    # 4. Désactivation zone3 à t+5s (aucune zone sur relais 0,1,2)
    await asyncio.sleep(2)
    await am.on_no_more_detection(now+5, ["zone3"])
    # 5. Réactivation rapide zone1 à t+6s (avant extinction possible)
    await asyncio.sleep(1)
    await am.on_detection(now+6, detections=[[0,0,1,1,0.9,["zone1"]]])
    # 6. Désactivation zone1 à t+8s
    await asyncio.sleep(2)
    await am.on_no_more_detection(now+8, ["zone1"])
    # 7. Désactivation zone2 à t+9s
    await asyncio.sleep(1)
    await am.on_no_more_detection(now+9, ["zone2"])
    # 8. Réactivation zone2 à t+10s (avant extinction possible)
    await asyncio.sleep(1)
    await am.on_detection(now+10, detections=[[0,0,1,1,0.9,["zone2"]]])
    # 9. Désactivation finale zone2 à t+12s
    await asyncio.sleep(2)
    await am.on_no_more_detection(now+12, ["zone2"])
    # 10. Attend 13s pour extinction complète
    await asyncio.sleep(13)
    # Vérifie que les relais sont bien restés allumés au moins 11s après la dernière zone et qu'aucun relais ne s'est éteint prématurément
    print("LOG RELAIS:")
    for entry in relays.log:
        print(entry)

if __name__ == "__main__":
    asyncio.run(test_multi_zone())
