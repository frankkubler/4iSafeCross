import threading
import time
from concurrent.futures import ThreadPoolExecutor
from utils import save_frame_to_file
from datetime import datetime
import logging
import cv2
import asyncio
from detection_db import init_db, insert_relay_event  # , insert_detection


class AlerteManager:
    def __init__(self, relays, telegram_bot=None, zones=None):
        # Mapping zone -> liste de relais à activer
        self.zone_to_relays = {
            "zone1": [0],
            "zone2": [0, 1, 2],
            "zone3": [0, 1, 2],
            "zone4": [3],
            "zone5": [4],
        }
        self.relays = relays
        self.last_detection_time = 0
        # self.relay_on devient un dict par zone
        self.relay_on = {}  # {zone_name: False}
        self.timer_task = {}  # {zone_name: asyncio.Task}
        self.relay_on_time = {}  # {zone_name: datetime}
        self.last_detection_time_by_zone = {}  # {zone_name: timestamp}
        self.logger = logging.getLogger(__name__).getChild(__class__.__name__)
        # Dictionnaire pour suivre le dernier temps de détection par caméra
        self.camera_last_detection = {}
        # ExecutorService pour gérer les enregistrements en arrière-plan
        self.recording_executor = ThreadPoolExecutor(max_workers=4)
        self.telegram_bot = telegram_bot  # Injecté depuis app.py
        self.last_telegram_sent = {}  # par caméra
        self.telegram_alert_enabled = True
        # Définition des zones (exemple : deux zones rectangulaires)
        # Format : (x1, y1, x2, y2) en pixels sur l'image
        self.zones = zones if zones is not None else []
        # Initialiser relay_on et timer_task pour chaque zone
        for zone in self.zones:
            name = zone["name"]
            self.relay_on[name] = False
            self.timer_task[name] = None
            self.relay_on_time[name] = None
            self.last_detection_time_by_zone[name] = 0
        init_db()  # Initialise la base de données à la création du manager

    def set_telegram_alert_enabled(self, enabled: bool):
        self.telegram_alert_enabled = enabled

    def _get_relays_from_zone(self, zone_name):
        for key, relays in self.zone_to_relays.items():
            if key in zone_name:
                return relays
        self.logger.warning(f"Zone {zone_name} non reconnue pour le relais")
        return []

    async def on_detection(self, timestamp, frame=None, detections=None, cid=None):
        # Gestion du relais
        self.last_detection_time = timestamp
        zone_names_detected = set()
        # Récupérer les zones détectées dans cette frame
        if detections:
            for det in detections:
                if len(det) > 5 and isinstance(det[-1], list):
                    for zn in det[-1]:
                        zone_names_detected.add(zn)
        # self.logger.info(f"Détection reçue à {timestamp} pour la caméra {cid} avec {len(zone_names_detected)} zones détectées : {zone_names_detected}")
        # Activer le relais pour chaque zone détectée
        for zone_name in zone_names_detected:
            relays = self._get_relays_from_zone(zone_name)
            self.logger.debug(f"self.relay_on : {self.relay_on.get(zone_name)}")
            if not self.relay_on.get(zone_name, False):
                now = datetime.now()
                if relays:
                    for relay_num in relays:
                        self.relays.action_on(relay_num)
                        self.logger.info(f"Activation du relais {relay_num} pour la zone {zone_name}")
                else:
                    self.relays.action_on()  # fallback si zone inconnue
                    self.logger.warning(f"Activation du relais pour la zone {zone_name} relais fallback 0")
                self.relay_on[zone_name] = True
                self.relay_on_time[zone_name] = now  # Enregistre le temps d'allumage
            # Mise à jour du timestamp de détection par zone
            self.last_detection_time_by_zone[zone_name] = timestamp
            # Annuler le timer d'extinction pour cette zone
            if self.timer_task.get(zone_name) and not self.timer_task[zone_name].done():
                self.timer_task[zone_name].cancel()
        # Gestion de l'enregistrement des frames
        if frame is not None and cid is not None:
            last_time = self.camera_last_detection.get(cid)
            current_frame = frame.copy()  # Copie de la frame pour éviter les problèmes de référence
            h, w = current_frame.shape[:2]
            self.logger.debug(f"Détection reçue pour la caméra {cid} détections : {detections} à {now.strftime('%Y-%m-%d %H:%M:%S')}")
            # Dessiner les rectangles de détection sur la frame
            for det in detections:
                x1 = max(0, min(w-1, int(det[0])))
                y1 = max(0, min(h-1, int(det[1])))
                x2 = max(0, min(w-1, int(det[2])))
                y2 = max(0, min(h-1, int(det[3])))
                # # Calcul du centre et des dimensions
                # center_x = (x1 + x2) / 2
                # center_y = (y1 + y2) / 2
                # width = abs(x2 - x1)
                # height = abs(y2 - y1)
                # Enregistrement dans la base de données
                # insert_detection(now, str(cid), str(det[5]) if len(det) > 5 else "unknown", center_x, center_y, width, height)
                cv2.rectangle(current_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                # Optionnel : afficher la confiance
                if len(det) > 4:
                    label = f"{det[4]:.2f}"
                    cv2.putText(current_frame, label, (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                # Afficher le(s) nom(s) de zone si présent à la fin de la détection
                if len(det) > 5 and isinstance(det[-1], list):
                    zone_names = det[-1]
                    for i, zone_name in enumerate(zone_names):
                        # Chercher la couleur de la zone si disponible
                        color = (255, 0, 0)
                        for z in self.zones:
                            if z["name"] == zone_name:
                                color = z.get("color", (255, 0, 0))
                                break
                        cv2.putText(current_frame, zone_name, (x1, y2 + 20 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            # Ajout du point vert si mouvement détecté
            # Vérifier si la détection est active depuis au moins 120 secondes
            if last_time is None or (now - last_time).total_seconds() >= 120:
                self.camera_last_detection[cid] = now
                # Enregistrer la frame dans un thread séparé
                self.recording_executor.submit(save_frame_to_file, current_frame, cid, now)
            # Envoi Telegram (décorrélé de l'enregistrement)
            if self.telegram_alert_enabled:
                last_telegram = self.last_telegram_sent.get(cid)
                if last_telegram is None or (now - last_telegram).total_seconds() >= 120:
                    # Chercher la dernière image enregistrée
                    caption = f"Détection caméra {cid} le {now.strftime('%Y-%m-%d %H:%M:%S')} {zone_names if 'zone_names' in locals() else ''}"
                    await self.telegram_bot.send_detection_frame(current_frame, caption)
                    self.last_telegram_sent[cid] = now

    async def on_no_more_detection(self, timestamp, zone_names=None):
        # zone_names : liste des zones pour lesquelles il n'y a plus de détection
        if not zone_names:
            zone_names = list(self.relay_on.keys())

        # Lance une tâche asyncio pour éteindre le relais après 10s
        async def delayed_off(zone_name):
            try:
                # Attendre exactement 11 secondes après la dernière détection pour cette zone
                delay = 11 - (time.time() - self.last_detection_time_by_zone.get(zone_name, 0))
                if delay > 0:
                    await asyncio.sleep(delay)
                if time.time() - self.last_detection_time_by_zone.get(zone_name, 0) >= 11:
                    self.logger.info(f"Aucune détection récente pour la zone {zone_name} :{time.time() - self.last_detection_time_by_zone.get(zone_name, 0)}")
                    relays = self._get_relays_from_zone(zone_name)
                    if relays:
                        for relay_num in relays:
                            self.relays.action_off(relay_num)
                    else:
                        self.relays.action_off()  # fallback si zone inconnue
                    self.relay_on[zone_name] = False
                    # Calcul de la durée d'allumage
                    time_on = self.relay_on_time.get(zone_name)
                    if time_on:
                        time_off = datetime.now()
                        duration = (time_off - time_on).total_seconds()
                        insert_relay_event(str(zone_name), duration, time_on, time_off)
                        self.relay_on_time[zone_name] = None
            except asyncio.CancelledError:
                self.logger.info(f"delayed_off annulé (détection relancée) pour {zone_name}")
                pass

        for zone_name in zone_names:
            if self.timer_task.get(zone_name) and not self.timer_task[zone_name].done():
                self.timer_task[zone_name].cancel()
                try:
                    await self.timer_task[zone_name]
                except asyncio.CancelledError:
                    pass
            self.timer_task[zone_name] = asyncio.create_task(delayed_off(zone_name))

    def set_zones(self, zones):
        # zones : liste de dicts {"name": ..., "rect": [x1, y1, x2, y2]}
        self.zones = zones
        self.logger.info(f"Zones mises à jour : {self.zones}")
        # Réinitialiser relay_on et timer_task pour chaque zone
        self.relay_on = {}
        self.timer_task = {}
        self.last_detection_time_by_zone = {}
        for zone in self.zones:
            name = zone["name"]
            self.relay_on[name] = False
            self.timer_task[name] = None
            self.relay_on_time[name] = None
            self.last_detection_time_by_zone[name] = 0
