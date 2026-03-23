import threading
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from utils.utils import save_frame_to_file
from datetime import datetime
import logging
import cv2
import asyncio
from src.detection_db import init_db, insert_relay_event  # , insert_detection
from utils.coco_classes import COCO_CLASSES

# Queue avec limite pour éviter l'accumulation de tâches en mémoire
MAX_RECORDING_QUEUE_SIZE = 20


class AlerteManager:
    def __init__(self, relays, telegram_bot=None, zones=None, zones_by_camera=None, telegram_alert_enabled=False):
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
        # ExecutorService pour gérer les enregistrements en arrière-plan avec queue limitée
        self._recording_queue = Queue(maxsize=MAX_RECORDING_QUEUE_SIZE)
        self.recording_executor = ThreadPoolExecutor(max_workers=4)
        self._pending_tasks = 0
        self._pending_tasks_lock = threading.Lock()
        self.telegram_bot = telegram_bot  # Injecté depuis app.py
        self.last_telegram_sent = {}  # par caméra
        self.telegram_alert_enabled = telegram_alert_enabled
        # Construire le lookup plat zone_name -> zone_dict pour toutes les caméras
        # Doit être fait AVANT _get_relay_nums_from_zone (appelé dans la boucle d'init)
        if zones_by_camera is not None:
            self._zones_flat = {
                z["name"]: z
                for cam_zones in zones_by_camera.values()
                for z in cam_zones
            }
            self.zones = [z for cam_zones in zones_by_camera.values() for z in cam_zones]
        else:
            flat_zones = zones if zones is not None else []
            self._zones_flat = {z["name"]: z for z in flat_zones}
            self.zones = flat_zones
        # Initialiser relay_on et timer_task pour chaque zone
        relay_nums = set()
        for zone in self.zones:
            for relay_num in self._get_relay_nums_from_zone(zone["name"]):
                relay_nums.add(relay_num)
        for relay_num in relay_nums:
            self.relay_on[relay_num] = True  # MODE FAIL-SAFE : relais ON par défaut
            self.relay_on_time[relay_num] = datetime.now()  # Enregistrer l'heure de démarrage
            self.relay_active_zones[relay_num] = set()
        for zone in self.zones:
            name = zone["name"]
            self.timer_task[name] = None
            self.last_detection_time_by_zone[name] = 0
        init_db()  # Initialise la base de données à la création du manager

    def _on_task_done(self):
        """Callback appelé quand une tâche d'enregistrement est terminée."""
        with self._pending_tasks_lock:
            self._pending_tasks = max(0, self._pending_tasks - 1)

    def set_telegram_alert_enabled(self, enabled: bool):
        self.telegram_alert_enabled = enabled

    def _get_relay_nums_from_zone(self, zone_name):
        """Retourne la liste des relais associés à une zone.

        Cherche d'abord dans la config data-driven (_zones_flat[zone_name]['relays']).
        Si absent ou liste vide, utilise le mapping hardcodé (rétrocompatibilité).
        """
        zone = self._zones_flat.get(zone_name, {})
        relays = zone.get("relays")
        if relays:  # liste non-vide définie dans la config
            return relays
        # Fallback hardcodé (rétrocompatibilité zones sans champ 'relays')
        if "zone1" in zone_name or "zone3" in zone_name:
            return [0, 1, 2]
        elif "zone2" in zone_name or "zone4" in zone_name or "zone5" in zone_name:
            return [1]
        self.logger.warning(f"Zone {zone_name} non reconnue pour le relais")
        return []

    def should_trigger_alert_for_detection(self, detection):
        """
        Détermine si une détection doit déclencher une alerte.

        Filtre anti-faux positifs par keypoints : si le serveur a fourni la pose
        et que moins de 4 keypoints humains ne sont visibles (conf >= 0.40), la
        détection est écartée (probable arrière de chariot élévateur).
        Si pose est vide (fail-safe / serveur sans modèle pose), l'alerte passe.

        Args:
            detection (dict): Dictionnaire de détection (label, pose, zones, …).

        Returns:
            bool: True si l'alerte doit être déclenchée, False sinon.
        """
        if detection.get("label") != "person":
            return False

        # pose=None / absent → modèle non disponible ou crop trop petit → fail-safe, laisser passer
        # pose=[]           → modèle a tourné, 0 personne détectée  → faux positif, rejeter
        # pose=[[x,y,c]..] → keypoints trouvés                     → compter les visibles
        # Seuils calibrés sur observations réelles :
        #   conf >= 0.40  : élimine les keypoints "hallusinés" sur structures non humaines
        #   min 4 kp      : un chariot peut générer 2-3 kp parasites à > 0.40, pas 4+
        KP_CONF_THRESHOLD = 0.40
        KP_MIN_VISIBLE = 4

        pose = detection.get("pose")
        if pose is not None:
            # pose=[] signifie que le modèle a tourné mais n'a trouvé aucun corps humain.
            # Ce cas est TOUJOURS rejeté : skip_keypoint_filter ne bypass que le seuil
            # de nombre de keypoints (peu de kp visibles), pas l'absence totale de corps.
            # Un chariot élévateur détecté comme "person" génère typiquement pose=[].
            if len(pose) == 0:
                detection_zones = detection.get("zones", [])
                self.logger.info(
                    f"Faux positif écarté — pose=[] zones={detection_zones} "
                    f"(skip_keypoint_filter ignoré pour pose=[])"
                )
                return False
            else:
                visible_kp = sum(
                    1 for kp in pose if len(kp) >= 3 and float(kp[2]) >= KP_CONF_THRESHOLD
                )
                if visible_kp < KP_MIN_VISIBLE:
                    # skip_keypoint_filter bypass uniquement le seuil N-kp (pas le pose=[])
                    detection_zones = detection.get("zones", [])
                    skip = any(
                        self._zones_flat.get(zn, {}).get("skip_keypoint_filter", False)
                        for zn in detection_zones
                    )
                    if skip:
                        self.logger.info(
                            f"Filtre keypoints bypassé (skip_keypoint_filter=True) pour zone(s) {detection_zones}"
                            f" — {visible_kp} keypoint(s) visible(s), seuil non appliqué"
                        )
                    else:
                        self.logger.debug(
                            f"Faux positif écarté — seulement {visible_kp} keypoint(s) humain(s)"
                            f" visible(s) (seuil : {KP_MIN_VISIBLE}, conf >= {KP_CONF_THRESHOLD})"
                            " — probable chariot élévateur"
                        )
                        return False

        if not detection.get("zones"):
            return False

        return True

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
                if isinstance(det, dict) and "zones" in det:
                    # Bug fix: ne maintenir le timer que pour les personnes
                    if det.get("label") == "person":
                        zone_names_detected.update(det["zones"])
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
                # Annuler le timer d'extinction du relais si une détection arrive
                timer = self.relay_timer_task.get(relay_num)
                if timer and not timer.done():
                    timer.cancel()
                    self.logger.debug(f"Timer d'extinction annulé pour relais {relay_num} (re-détection zone {zone_name})")
            self.last_detection_time_by_zone[zone_name] = timestamp
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
                    # Limiter la queue pour éviter l'accumulation en mémoire
                    with self._pending_tasks_lock:
                        if self._pending_tasks < MAX_RECORDING_QUEUE_SIZE:
                            self._pending_tasks += 1
                            future = self.recording_executor.submit(save_frame_to_file, current_frame, cid, now)
                            future.add_done_callback(lambda f: self._on_task_done())
                        else:
                            self.logger.warning(f"Queue d'enregistrement pleine ({MAX_RECORDING_QUEUE_SIZE}), frame ignorée pour caméra {cid}")
                # Envoi Telegram
                if self.telegram_alert_enabled:
                    last_telegram = self.last_telegram_sent.get(cid)
                    if last_telegram is None or (now - last_telegram).total_seconds() >= 120:
                        caption = f"Détection caméra {cid} le {now.strftime('%Y-%m-%d %H:%M:%S')}"
                        await self.telegram_bot.send_detection_frame(current_frame, caption)
                        self.last_telegram_sent[cid] = now
            except Exception as e:
                self.logger.error(f"Erreur lors de l'enregistrement ou l'envoi Telegram : {e}")

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

    def set_zones(self, zones_or_by_camera):
        """Met à jour les zones et reconstruit le lookup relais.

        Args:
            zones_or_by_camera: dict {cam_id: [zones]} ou liste de zones.
        """
        if isinstance(zones_or_by_camera, dict):
            self._zones_flat = {
                z["name"]: z
                for cam_zones in zones_or_by_camera.values()
                for z in cam_zones
            }
            self.zones = [z for cam_zones in zones_or_by_camera.values() for z in cam_zones]
        else:
            self.zones = zones_or_by_camera
            self._zones_flat = {z["name"]: z for z in self.zones}
        self.logger.info(f"Zones mises à jour : {len(self.zones)} zones sur {len(set(z['name'].split('_cam')[-1] for z in self.zones if '_cam' in z['name']))} caméra(s)")
        # Éteindre physiquement les relais qui étaient allumés avant la reconfiguration
        for relay_num, was_on in list(self.relay_on.items()):
            if was_on:
                self.relays.action_off(relay_num)
                self.logger.info(f"Extinction du relais {relay_num} suite à la reconfiguration des zones")
        # Annuler les timers d'extinction en cours
        for relay_num, timer in list(self.relay_timer_task.items()):
            if timer and not timer.done():
                timer.cancel()
        self.relay_timer_task = {}
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

    def _draw_detections(self, frame, detections, h, w):
        """Dessine les rectangles et labels sur la frame."""
        if not detections:
            return
        for det in detections:
            # det est maintenant un dictionnaire
            x1 = max(0, min(w-1, int(det["x_min"])))
            y1 = max(0, min(h-1, int(det["y_min"])))
            x2 = max(0, min(w-1, int(det["x_max"])))
            y2 = max(0, min(h-1, int(det["y_max"])))
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            confidence = det.get("confidence", 0)
            class_id = det.get("class_id", -1)
            label = det.get("label", "unknown")
            text = f"{label} {confidence:.2f}"
            # label = f"{confidence:.2f} {COCO_CLASSES.get(class_id, 'unknown')}"
            cv2.putText(frame, text, (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            zone_names = det.get("zones", [])
            if zone_names:
                for i, zone_name in enumerate(zone_names):
                    color = (255, 0, 0)
                    for z in self.zones:
                        if z["name"] == zone_name:
                            color = z.get("color", (255, 0, 0))
                            break
                    cv2.putText(frame, zone_name, (x1, y2 + 20 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
