import threading
import time
from concurrent.futures import ThreadPoolExecutor
from utils.utils import save_frame_to_file
from datetime import datetime
import logging
import cv2
import asyncio
from src.detection_db import init_db, insert_relay_event  # , insert_detection
from utils.coco_classes import COCO_CLASSES

class AlerteManager:
    def __init__(self, relays, telegram_bot=None, zones=None, telegram_alert_enabled=False):
        # ...existing code...
        self.relays = relays
        self.last_detection_time = 0
        # self.relay_on devient un dict par relais
        self.relay_on = {}  # {relay_num: False}
        self.relay_on_time = {}  # {relay_num: datetime}
        self.timer_task = {}  # {zone_name: asyncio.Task}
        self.relay_timer_task = {}  # {relay_num: asyncio.Task}
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
        self.telegram_alert_enabled = telegram_alert_enabled
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

    async def on_detection(self, timestamp: float, frame=None, detections=None, cid=None):
        """
        Optimisé : factorisation du dessin, typage, gestion des exceptions.
        """
        self.last_detection_time = timestamp
        zone_names_detected = set()
        now = datetime.now()
        # Récupérer les zones détectées dans cette frame
        if detections:
            for det in detections:
                if len(det) > 5 and isinstance(det[-1], list):
                    zone_names_detected.update(det[-1])
        # Activation des relais pour chaque zone détectée
        for zone_name in zone_names_detected:
            relay_nums = self._get_relay_nums_from_zone(zone_name)
            for relay_num in relay_nums:
                self.relay_active_zones.setdefault(relay_num, set()).add(zone_name)
                self.logger.debug(f"self.relay_on : {self.relay_on.get(relay_num)}")
                if not self.relay_on.get(relay_num, False):
                    self.relays.action_on(relay_num)
                    self.logger.info(f"Activation du relais pour la zone {zone_name} (relais numéro {relay_num})")
                    self.relay_on[relay_num] = True
                self.relay_on_time[relay_num] = now
            self.last_detection_time_by_zone[zone_name] = timestamp
            # Annuler le timer d'extinction pour cette zone
            timer = self.timer_task.get(zone_name)
            if timer and not timer.done():
                timer.cancel()
        # Gestion de l'enregistrement des frames et alertes
        if frame is not None and cid is not None:
            last_time = self.camera_last_detection.get(cid)
            try:
                current_frame = frame.copy()
                h, w = current_frame.shape[:2]
                self.logger.debug(f"Détection reçue pour la caméra {cid} détections : {detections} à {now.strftime('%Y-%m-%d %H:%M:%S')}")
                self._draw_detections(current_frame, detections, h, w)
                # Enregistrement si la dernière détection remonte à >120s
                if last_time is None or (now - last_time).total_seconds() >= 120:
                    self.camera_last_detection[cid] = now
                    self.recording_executor.submit(save_frame_to_file, current_frame, cid, now)
                # Envoi Telegram
                if self.telegram_alert_enabled:
                    last_telegram = self.last_telegram_sent.get(cid)
                    if last_telegram is None or (now - last_telegram).total_seconds() >= 120:
                        caption = f"Détection caméra {cid} le {now.strftime('%Y-%m-%d %H:%M:%S')}"
                        await self.telegram_bot.send_detection_frame(current_frame, caption)
                        self.last_telegram_sent[cid] = now
            except Exception as e:
                self.logger.error(f"Erreur lors de l'enregistrement ou l'envoi Telegram : {e}")

    def _draw_detections(self, frame, detections, h, w):
        """Dessine les rectangles et labels sur la frame."""
        if not detections:
            return
        for det in detections:
            x1 = max(0, min(w-1, int(det[0])))
            y1 = max(0, min(h-1, int(det[1])))
            x2 = max(0, min(w-1, int(det[2])))
            y2 = max(0, min(h-1, int(det[3])))
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            if len(det) > 5:
                label = f"{det[4]:.2f} {COCO_CLASSES.get(det[5], 'unknown')}"
                cv2.putText(frame, label, (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            if len(det) > 5 and isinstance(det[-1], list):
                zone_names = det[-1]
                for i, zone_name in enumerate(zone_names):
                    color = (255, 0, 0)
                    for z in self.zones:
                        if z["name"] == zone_name:
                            color = z.get("color", (255, 0, 0))
                            break
                    cv2.putText(frame, zone_name, (x1, y2 + 20 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    async def on_no_more_detection(self, timestamp: float, zone_names=None):
        """
        Optimisé : extinction indépendante par relais, factorisation, typage.
        """
        if not zone_names:
            zone_names = list(self.last_detection_time_by_zone.keys())

        relays_to_check = set()
        for zone_name in zone_names:
            relay_nums = self._get_relay_nums_from_zone(zone_name)
            for relay_num in relay_nums:
                self.relay_active_zones.setdefault(relay_num, set()).discard(zone_name)
                relays_to_check.add(relay_num)

        for relay_num in relays_to_check:
            if not self.relay_active_zones[relay_num]:
                await self._cancel_and_restart_timer(relay_num)

    async def _cancel_and_restart_timer(self, relay_num: int):
        """Annule le timer existant et lance l'extinction asynchrone du relais."""
        timer = self.relay_timer_task.get(relay_num)
        if timer and not timer.done():
            timer.cancel()
            try:
                await timer
            except asyncio.CancelledError:
                self.logger.info(f"Timer extinction annulé pour relais {relay_num}")
        self.relay_timer_task[relay_num] = asyncio.create_task(self._delayed_off_relay(relay_num))

    async def _delayed_off_relay(self, relay_num: int):
        """Extinction du relais après temporisation de sécurité."""
        try:
            time_on = self.relay_on_time.get(relay_num)
            now = datetime.now()
            if time_on:
                elapsed = (now - time_on).total_seconds()
                if elapsed < 11:
                    wait_time = 11 - elapsed
                    self.logger.info(f"Protection : attente supplémentaire de {wait_time:.2f}s pour garantir 11s d'allumage du relais {relay_num}")
                    await asyncio.sleep(wait_time)
                else:
                    await asyncio.sleep(0)
            else:
                await asyncio.sleep(11)
            if not self.relay_active_zones[relay_num] and self.relay_on.get(relay_num, False):
                if time_on is None:
                    self.logger.warning(f"[ATTENTION] Extinction demandée pour relais {relay_num} sans activation préalable. Temporisation 11s avant extinction réelle.")
                    await asyncio.sleep(11)
                    # Vérifier à nouveau l'état des zones avant extinction
                    if not self.relay_active_zones[relay_num] and self.relay_on.get(relay_num, False):
                        time_off = datetime.now()
                        self.logger.info(f"Extinction du relais {relay_num} après temporisation 11s (aucune activation préalable)")
                        self.relays.action_off(relay_num)
                        self.relay_on[relay_num] = False
                        duration = 0
                        self.relay_on_time[relay_num] = None
                        last_det_ts = max([self.last_detection_time_by_zone.get(z, 0) for z in self.last_detection_time_by_zone], default=0)
                        if last_det_ts:
                            try:
                                last_det_str = datetime.fromtimestamp(last_det_ts).strftime('%Y-%m-%d %H:%M:%S.%f')
                            except Exception:
                                last_det_str = str(last_det_ts)
                        else:
                            last_det_str = 'None'
                        self.logger.info(
                            f"[DIAG] Après extinction, zones actives pour relais {relay_num} : {self.relay_active_zones[relay_num]} | "
                            f"Dernière détection (toutes zones) : {last_det_str} | "
                            f"Fin extinction (time_off) : {time_off.strftime('%Y-%m-%d %H:%M:%S.%f')} | "
                            f"Durée d'allumage : {duration:.2f} secondes"
                        )
                else:
                    time_off = datetime.now()
                    self.logger.info(f"Extinction du relais {relay_num} après 11s sans détection (toutes zones)")
                    self.relays.action_off(relay_num)
                    self.relay_on[relay_num] = False
                    duration = (time_off - time_on).total_seconds()
                    insert_relay_event(f"relay_{relay_num}", duration, time_on, time_off)
                    self.relay_on_time[relay_num] = None
                    last_det_ts = max([self.last_detection_time_by_zone.get(z, 0) for z in self.last_detection_time_by_zone], default=0)
                    if last_det_ts:
                        try:
                            last_det_str = datetime.fromtimestamp(last_det_ts).strftime('%Y-%m-%d %H:%M:%S.%f')
                        except Exception:
                            last_det_str = str(last_det_ts)
                    else:
                        last_det_str = 'None'
                    self.logger.info(
                        f"[DIAG] Après extinction, zones actives pour relais {relay_num} : {self.relay_active_zones[relay_num]} | "
                        f"Dernière détection (toutes zones) : {last_det_str} | "
                        f"Fin extinction (time_off) : {time_off.strftime('%Y-%m-%d %H:%M:%S.%f')} | "
                        f"Durée d'allumage : {duration:.2f} secondes"
                    )
        except asyncio.CancelledError:
            self.logger.info(f"Extinction annulée (détection relancée) pour relais {relay_num}")
            pass

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
