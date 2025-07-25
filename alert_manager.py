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
        # ...existing code...
        self.relays = relays
        self.last_detection_time = 0
        # self.relay_on devient un dict par relais
        self.relay_on = {}  # {relay_num: False}
        self.relay_on_time = {}  # {relay_num: datetime}
        self.timer_task = {}  # {zone_name: asyncio.Task}
        self.last_detection_time_by_zone = {}  # {zone_name: timestamp}
        # Pour chaque relais, garder la liste des zones actives qui l'utilisent
        self.relay_active_zones = {}  # {relay_num: set(zone_names_actives)}
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
        relay_nums = set()
        for zone in self.zones:
            for relay_num in self._get_relay_nums_from_zone(zone["name"]):
                relay_nums.add(relay_num)
        for relay_num in relay_nums:
            self.relay_on[relay_num] = False
            self.relay_on_time[relay_num] = None
            self.relay_active_zones[relay_num] = set()
        for zone in self.zones:
            name = zone["name"]
            self.timer_task[name] = None
            self.last_detection_time_by_zone[name] = 0
        init_db()  # Initialise la base de données à la création du manager

    def set_telegram_alert_enabled(self, enabled: bool):
        self.telegram_alert_enabled = enabled

    def _get_relay_nums_from_zone(self, zone_name):
        # Retourne une liste de relais à activer/éteindre selon la zone
        if "zone1" in zone_name or "zone3" in zone_name:
            return [0, 1, 2]
        elif "zone2" in zone_name:
            return [1]
        elif "zone4" in zone_name:
            return [3]
        elif "zone5" in zone_name:
            return [4]
        self.logger.warning(f"Zone {zone_name} non reconnue pour le relais")
        return []  # Si la zone n'est pas reconnue, on ne fait rien

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
            relay_nums = self._get_relay_nums_from_zone(zone_name)
            for relay_num in relay_nums:
                # Ajouter la zone comme active pour ce relais
                self.relay_active_zones.setdefault(relay_num, set()).add(zone_name)
                self.logger.debug(f"self.relay_on : {self.relay_on.get(relay_num)}")
                if not self.relay_on.get(relay_num, False):
                    now = datetime.now()
                    self.relays.action_on(relay_num)
                    self.logger.info(f"Activation du relais pour la zone {zone_name} (relais numéro {relay_num})")
                    self.relay_on[relay_num] = True
                    self.relay_on_time[relay_num] = now  # Enregistre le temps d'allumage
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
            zone_names = list(self.last_detection_time_by_zone.keys())

        # Lance une tâche asyncio pour éteindre le(s) relais après 11s
        async def delayed_off(zone_name):
            try:
                relay_nums = self._get_relay_nums_from_zone(zone_name)
                for relay_num in relay_nums:
                    # Retirer la zone de la liste des zones actives pour ce relais
                    self.relay_active_zones.setdefault(relay_num, set()).discard(zone_name)
                    # Si plus aucune zone n'est active pour ce relais, on lance/extinction après 11s
                    if not self.relay_active_zones[relay_num]:
                        time_on = self.relay_on_time.get(relay_num)
                        if time_on is not None:
                            await asyncio.sleep(11)
                            # Log de diagnostic : afficher les zones actives restantes avant extinction
                            self.logger.info(f"[DIAG] Avant extinction, zones actives pour relais {relay_num} : {self.relay_active_zones[relay_num]}")
                            # Vérifier à nouveau qu'aucune zone n'est active pour ce relais
                            if not self.relay_active_zones[relay_num] and self.relay_on.get(relay_num, False):
                                self.logger.info(f"Extinction du relais {relay_num} après 11s sans détection (zone {zone_name})")
                                self.relays.action_off(relay_num)
                                self.relay_on[relay_num] = False
                                time_off = datetime.now()
                                duration = (time_off - time_on).total_seconds()
                                insert_relay_event(f"relay_{relay_num}", duration, time_on, time_off)
                                self.relay_on_time[relay_num] = None
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
        # Réinitialiser relay_on, relay_on_time, relay_active_zones pour chaque relay_num
        relay_nums = set()
        for zone in self.zones:
            for relay_num in self._get_relay_nums_from_zone(zone["name"]):
                relay_nums.add(relay_num)
        self.relay_on = {relay_num: False for relay_num in relay_nums}
        self.relay_on_time = {relay_num: None for relay_num in relay_nums}
        self.relay_active_zones = {relay_num: set() for relay_num in relay_nums}
        self.timer_task = {}
        self.last_detection_time_by_zone = {}
        for zone in self.zones:
            name = zone["name"]
            self.timer_task[name] = None
            self.last_detection_time_by_zone[name] = 0
