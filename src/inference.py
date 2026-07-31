import threading
import time
import numpy as np
import logging
import requests
import io
import cv2
from collections import deque
from utils.constants import (MOTIONTHRESHOLD, INF_THRESHOLD,
                             DETECTION, POSE_ENABLED,
                             URL_RFDETR, FONCTION_RFDETR, URL_YOLO, FONCTION_YOLO,
                             EXTENDED_CLASSES, TRANSFERT_CLASSES, SIMPLE_CLASSES,
                             FGBG_HISTORY, FGBG_VAR_THRESHOLD, FGBG_DETECT_SHADOWS,
                             MOTION_ON_FRAMES, MOTION_OFF_FRAMES,
                             MOTION_GAUSSIAN_BLUR, MOTION_ASPECT_FILTER,
                             MOTION_MIN_SINGLE_CONTOUR)

from src.motion import MotionDetector
from src.pose_analyser import PoseAnalyzer


class InferenceServerThread(threading.Thread):
    def __init__(self, home_dir, get_frame_func,
                 white_pixels_threshold=MOTIONTHRESHOLD,
                 detection_callback=None, stop_event=None, masks=None,
                 cam_id=None):
        super().__init__()
        self.home_dir = home_dir
        self.cam_id = cam_id  # Index caméra, pour attribuer les mesures de latence
        self.get_frame_func = get_frame_func  # Fonction pour obtenir la frame courante
        self.detection_callback = detection_callback  # Callback pour envoyer les résultats
        self.stop_event = stop_event or threading.Event()
        self.masks = masks or []
        self.masks_lock = threading.Lock()
        self.logger = logging.getLogger(__name__).getChild(__class__.__name__)
        self.fonction = FONCTION_YOLO
        self.url = rf"{URL_YOLO}/{self.fonction}/"
        self.is_detection = False
        self.white_pixels_threshold = white_pixels_threshold
        self._motion = False  # Attribut privé
        # self.old_motion_bool = False
        self.past_detections = []
        self.detections = []
        self.confidence_threshold = INF_THRESHOLD
        self.pose_enabled = POSE_ENABLED
        if DETECTION == 'extended':
            self.class_id = EXTENDED_CLASSES
        elif DETECTION == 'finetuned':
            self.class_id = SIMPLE_CLASSES
        elif DETECTION == 'transfert':
            self.class_id = TRANSFERT_CLASSES
        else:
            self.class_id = [1]
        # self.class_id = 1 if "rf_detr" in self.fonction else 0
        # Initialisation avec adaptation pour différentes zones d'image
        # Utilise une hauteur d'image typique de 1080p, ajustez si nécessaire
        self.pose_analyzer = PoseAnalyzer(
            confidence_threshold=0.2,
            enable_zone_adaptation=True,
            image_height=1080
        )
        self.motion_detector = MotionDetector()
        # Initialisation des paramètres MOG2 depuis config.ini
        self.motion_detector.update_fgbg_params(
            varThreshold=FGBG_VAR_THRESHOLD,
            history=FGBG_HISTORY,
            detectShadows=FGBG_DETECT_SHADOWS
        )
        # Initialisation des paramètres de détection (hystérésis, filtrages) depuis config.ini
        self.motion_detector.update_detection_params(
            motion_on_frames=MOTION_ON_FRAMES,
            motion_off_frames=MOTION_OFF_FRAMES,
            use_gaussian_blur=MOTION_GAUSSIAN_BLUR,
            use_aspect_filter=MOTION_ASPECT_FILTER,
            min_single_contour=MOTION_MIN_SINGLE_CONTOUR,
        )

        # 🚀 Optimisations pour réduire la charge IA (100ms par inférence)
        self.last_inference_time = 0
        self.min_inference_interval = 0.2  # 200ms minimum entre inférences (5 FPS max)
        self.last_sent_frame_hash = None
        self.inference_skip_count = 0
        self.total_frames_processed = 0

        # 🚀 Optimisation sleep adaptatif
        self.consecutive_skips = 0
        self.last_motion_time = 0

        # ── Instrumentation des latences (mesure avant décision ZeroMQ) ──────
        # Découpe le coût d'un aller-retour d'inférence pour distinguer ce qui
        # relève du transport HTTP (supprimable par un passage à ZeroMQ) de ce
        # qui relève de l'inférence TensorRT (incompressible à modèle égal).
        #
        # Client et serveur tournent sur la même Jetson (network_mode: host),
        # donc les horloges sont communes et les timestamps comparables :
        #
        #   serialize  np.save() de la frame            — côté client
        #   uplink     émission → arrivée serveur       — transport montant
        #   parse      décodage multipart FastAPI       — côté serveur
        #   deserial.  np.load() de la frame            — côté serveur
        #   detect     inférence TensorRT détection     — côté serveur
        #   pose       inférence TensorRT keypoints     — côté serveur
        #   downlink   réponse serveur → réception      — transport descendant
        #   roundtrip  total mesuré par requests.post()
        self.timing_window = 200
        self.timings = {
            phase: deque(maxlen=self.timing_window)
            for phase in ("serialize", "uplink", "parse", "deserialize",
                          "detect", "pose", "downlink", "roundtrip")
        }
        self.timings_lock = threading.Lock()

    @property
    def motion(self):
        return self._motion

    def set_masks(self, masks):
        """Met à jour les masques polygonaux de manière thread-safe.

        Args:
            masks: Liste de dicts {'name': str, 'polygon': list of (x, y)}.
        """
        with self.masks_lock:
            self.masks = masks or []

    def _apply_masks(self, frame):
        """Applique les masques polygonaux sur une copie de la frame.

        Les zones masquées sont noircies (pixels mis à 0) avant toute analyse.
        Opère sur une copie pour ne pas corrompre le buffer partagé de CameraManager,
        UNIQUEMENT si des masques sont réellement définis. Sans masque, la frame
        d'origine est retournée telle quelle (pas de copie mémoire inutile).

        Args:
            frame: Frame numpy BGR (H x W x 3).

        Returns:
            Copie de la frame avec les zones masquées en noir, ou la frame
            d'origine si aucun masque n'est configuré.
        """
        with self.masks_lock:
            current_masks = self.masks

        # 🚀 Optimisation : pas de copie si aucun masque n'est actif
        if not current_masks:
            return frame

        # Copie uniquement nécessaire quand on va réellement modifier la frame
        masked = frame.copy()
        for mask in current_masks:
            polygon = mask.get('polygon')
            if not polygon or len(polygon) < 3:
                continue
            pts = np.array(polygon, dtype=np.int32)
            cv2.fillPoly(masked, [pts], (0, 0, 0))
        return masked

    def _should_run_inference(self, frame):
        """Détermine si une inférence doit être lancée pour économiser les ressources IA."""
        current_time = time.time()

        # 🚀 Limite de fréquence : max 5 FPS pour l'IA (200ms minimum)
        if current_time - self.last_inference_time < self.min_inference_interval:
            self.inference_skip_count += 1
            return False

        # 🚀 Hash de frame pour éviter les inférences redondantes
        frame_hash = self.fast_frame_hash(frame)
        if frame_hash == self.last_sent_frame_hash:
            self.inference_skip_count += 1
            return False

        self.last_sent_frame_hash = frame_hash
        self.last_inference_time = current_time
        return True

    def fast_frame_hash(self, frame, downscale_size=(16, 16)):
        """
        Calcule un hash rapide pour une image en :
        - convertissant en niveaux de gris
        - redimensionnant à petite taille fixe
        - calculant le hash sur bytes réduits
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, downscale_size, interpolation=cv2.INTER_AREA)
        return hash(small.tobytes())


    def _record_timings(self, server_timings, serialize_ms, t_send, t_received):
        """Enregistre la décomposition de latence d'un aller-retour d'inférence.

        Args:
            server_timings: Dict `timings` renvoyé par le serveur d'inférence,
                ou None si le serveur ne l'expose pas (ancienne version).
            serialize_ms: Durée du np.save() côté client, en ms.
            t_send: Timestamp d'émission de la requête.
            t_received: Timestamp de réception de la réponse.
        """
        sample = {
            "serialize": serialize_ms,
            "roundtrip": (t_received - t_send) * 1000,
        }

        if isinstance(server_timings, dict):
            # Un cache hit serveur ne reflète pas le coût d'inférence réel :
            # on garde le transport, on écarte detect/pose.
            cache_hit = server_timings.get("cache_hit", False)
            sample["uplink"] = server_timings.get("wait")
            sample["parse"] = server_timings.get("parse")
            sample["deserialize"] = server_timings.get("deserialize")
            if not cache_hit:
                sample["detect"] = server_timings.get("detect")
                sample["pose"] = server_timings.get("pose")
            t_reply = server_timings.get("t_reply")
            if t_reply:
                sample["downlink"] = (t_received - t_reply) * 1000

        with self.timings_lock:
            for phase, value in sample.items():
                if value is not None and phase in self.timings:
                    self.timings[phase].append(value)

    def get_timing_stats(self):
        """Agrège les latences par phase en p50/p95 (ms) sur la fenêtre courante."""
        with self.timings_lock:
            snapshot = {phase: sorted(values) for phase, values in self.timings.items()}

        def percentile(values, fraction):
            if not values:
                return None
            index = min(int(fraction * len(values)), len(values) - 1)
            return round(values[index], 2)

        stats = {}
        for phase, values in snapshot.items():
            if not values:
                stats[phase] = {"count": 0}
                continue
            stats[phase] = {
                "count": len(values),
                "p50": percentile(values, 0.50),
                "p95": percentile(values, 0.95),
                "mean": round(sum(values) / len(values), 2),
            }

        # Budget transport : ce qu'un passage à ZeroMQ pourrait supprimer.
        transport_p50 = sum(
            stats[phase].get("p50") or 0
            for phase in ("serialize", "uplink", "parse", "deserialize", "downlink")
        )
        inference_p50 = sum(
            stats[phase].get("p50") or 0
            for phase in ("detect", "pose")
        )
        # Le cycle complet = sérialisation (avant émission) + aller-retour.
        # `roundtrip` seul exclut le np.save(), qui fait pourtant partie du
        # coût que ZeroMQ supprimerait : c'est donc le mauvais dénominateur.
        roundtrip_p50 = stats["roundtrip"].get("p50") or 0
        serialize_p50 = stats["serialize"].get("p50") or 0
        cycle_p50 = serialize_p50 + roundtrip_p50

        return {
            "phases": stats,
            "transport_overhead_p50_ms": round(transport_p50, 2),
            "inference_p50_ms": round(inference_p50, 2),
            "roundtrip_p50_ms": roundtrip_p50,
            "cycle_p50_ms": round(cycle_p50, 2),
            "transport_share_pct": (
                round(transport_p50 / cycle_p50 * 100, 1)
                if cycle_p50 else None
            ),
        }

    def _parse_detection(self, d):
        """Valide et normalise une détection reçue du serveur d'inférence.

        Frontière de confiance : le serveur d'inférence est un service externe
        (voir AGENTS.md, « Couplage Inter-Projets »). Un changement de contrat
        côté serveur ne doit pas tuer le thread — une détection malformée est
        journalisée et ignorée, les autres continuent d'être traitées.

        Args:
            d: Dict brut issu du JSON du serveur.

        Returns:
            Dict de détection normalisé, ou None si l'entrée est inexploitable
            ou filtrée (classe non surveillée, confiance sous le seuil).
        """
        try:
            if d["class_id"] not in self.class_id:
                return None
            confidence = float(d["confidence"])
            if confidence < self.confidence_threshold:
                return None
            label = d.get("label", "")
            personne_type = d.get("personne_type")
            if personne_type not in ("sitting_in_vehicle", "pieton"):
                personne_type = "pieton" if label == "person" else ""
            return {
                "x_min": float(d["x_min"]),
                "y_min": float(d["y_min"]),
                "x_max": float(d["x_max"]),
                "y_max": float(d["y_max"]),
                "confidence": confidence,
                "class_id": int(d["class_id"]),
                "label": label,
                "tracker_id": int(d.get("tracker_id") or -1),
                # pose=None → pose désactivée (POSE_ENABLED=False, skip_pose=True)
                # pose=[]   → pose activée, modèle a tourné, aucun corps trouvé
                # pose=[..] → keypoints disponibles
                "pose": None if not self.pose_enabled else d.get("pose", []),
                "personne_type": personne_type,
            }
        except (KeyError, TypeError, ValueError) as exc:
            self.logger.error(
                "Détection malformée ignorée (%s: %s) — payload=%r",
                type(exc).__name__, exc, d
            )
            return None

    def _call_detection_callback(self, result):
        """Appelle le callback de détection s'il est défini."""
        if self.detection_callback:
            self.detection_callback(result)
            # self.logger.info(f"Appel de la fonction de rappel avec {len(detections)} détections.")

    def run(self):
        self.logger.info(f"Thread d'inférence démarré pour {self.url}")
        while not self.stop_event.is_set():
            self.total_frames_processed += 1
            frame = self.get_frame_func()
            if frame is None:
                time.sleep(0.1)
                continue
            # Appliquer les masques en amont de tout traitement (copie protégée)
            frame = self._apply_masks(frame)
            # 🚀 Étape de détection de mouvement (10ms)
            # Ensuite, lancez la détection (sans paramètres redondants ici)
            roi, motion_bool, white_pixels, coords = self.motion_detector.get_mog2_motion_info(
                frame,
                padding=getattr(self.motion_detector, 'padding', 40),
                white_pixels_threshold=self.white_pixels_threshold,
                min_contour_area=getattr(self.motion_detector, 'min_contour_area', 30),
            )

            x_pad, y_pad, w_pad, h_pad, x, y, w, h = coords
            self._motion = motion_bool

            # 🚀 Log des statistiques d'optimisation toutes les 100 frames
            if self.total_frames_processed % 100 == 0:
                skip_rate = (self.inference_skip_count / self.total_frames_processed) * 100
                self.logger.debug(f"📊 Inférence optimisée: {skip_rate:.1f}% frames sautées ({self.inference_skip_count}/{self.total_frames_processed})")

            if (not motion_bool) or (w_pad <= 0 or h_pad <= 0):
                # Appeler le callback avec une détection vide pour effacer l'affichage côté client
                self._call_detection_callback([])
                # self.logger.debug("Aucune détection de mouvement ou zone de mouvement invalide (w_pad <= 0 ou h_pad <= 0).")
                # 🚀 Pas de mouvement = sleep plus long (économie CPU)
                time.sleep(0.05)  # 50ms au lieu de 10ms quand pas de mouvement
                continue

            # 🚀 Vérification si inférence nécessaire (économie de 100ms par frame sautée)
            if not self._should_run_inference(frame):
                # Renvoyer les dernières détections connues (frame sautée, ne contribue pas au debounce)
                self._call_detection_callback({
                    "detections": self.past_detections,
                    "roi": roi,
                    "x_pad": (x_pad, y_pad, w_pad, h_pad, x, y, w, h),
                    "y_pad": None,
                    "skipped": True,  # Indique que ce n'est pas une vraie inférence
                })
                self.consecutive_skips += 1
                # 🚀 Sleep progressif : plus on skip, plus on dort longtemps (jusqu'à 50ms max)
                adaptive_sleep = min(0.001 + (self.consecutive_skips * 0.002), 0.05)
                time.sleep(adaptive_sleep)
                continue

            # Inférence IA (100ms) - maintenant limitée à 5 FPS max
            current_detections = []

            inference_start_time = time.time()
            try:
                # Utiliser with pour fermer automatiquement le BytesIO et éviter les fuites mémoire
                with io.BytesIO() as buffer:
                    np.save(buffer, frame, allow_pickle=True)
                    buffer.seek(0)
                    payload = buffer.getvalue()
                    serialize_ms = (time.time() - inference_start_time) * 1000
                    t_send = time.time()
                    response = requests.post(
                        self.url,
                        files={"frame": payload},
                        params={
                            "confidence": self.confidence_threshold,
                            "skip_pose": not self.pose_enabled,
                            "t_send": t_send,
                        },
                        timeout=30,
                    )
                t_received = time.time()
                if response.status_code == 200:
                    response_payload = response.json()
                    detections = response_payload.get("detections", [])
                    self._record_timings(response_payload.get("timings"),
                                         serialize_ms, t_send, t_received)
                    inference_time = (time.time() - inference_start_time) * 1000  # en ms
                    self.logger.debug(f"⚡ Inférence IA: {inference_time:.1f}ms")

                    if detections:
                        # Validation à la frontière : voir _parse_detection().
                        current_detections = [
                            parsed for parsed in (
                                self._parse_detection(d) for d in detections
                            )
                            if parsed is not None
                        ]
                        # Fallback de sécurité: si une personne a encore un label vide/inconnu, mettre 'pieton'
                        for detection in current_detections:
                            # Analyser la stature si pose est présente et label == "person"
                            if detection["label"] == "person" and detection["pose"]:
                                detection["stature"] = self.pose_analyzer.analyze_stature(detection["pose"], debug=True)
                            else:
                                detection["stature"] = "inconnu"
                        if len(current_detections) > 0:
                            self.is_detection = True
                            # Résumé en INFO, dictionnaires complets en DEBUG : avec
                            # POSE_ENABLED chaque détection porte 17 keypoints, et à
                            # 5 FPS × N caméras le dump saturait les 10 Mo × 5 du
                            # driver json-file, évinçant les lignes de diagnostic.
                            self.logger.info(
                                "%d détection(s) : %s",
                                len(current_detections),
                                ', '.join(
                                    f"{d['label'] or '?'}({d['confidence']:.2f})"
                                    for d in current_detections
                                ),
                            )
                            self.logger.debug(f"Détections actuelles : {current_detections}")
                        else:
                            self.is_detection = False
                            self.logger.debug("Aucune détection de classe 0 trouvée.")
                    else:
                        self.logger.debug("Aucune détection reçue.")
                        self.is_detection = False
                        current_detections = []
                else:
                    self.logger.error(
                        "Réponse serveur invalide : HTTP %s", response.status_code
                    )
            except requests.ConnectionError:
                self.logger.error("Impossible de se connecter au serveur.")
                # Mettre quand même à jour le ROI pour l'affichage vidéo
                self._call_detection_callback({
                    "detections": [],
                    "roi": roi,
                    "x_pad": (x_pad, y_pad, w_pad, h_pad, x, y, w, h),
                    "y_pad": None
                })
                time.sleep(1)
                continue
            except Exception:
                # Filet de sécurité : ce thread ne doit JAMAIS mourir sur une
                # réponse inattendue (timeout, JSON invalide, contrat modifié).
                # S'il meurt, le heartbeat s'arrête, le watchdog verrouille les
                # relais en ON et la détection ne repart plus sans redémarrage.
                self.logger.error(
                    "Erreur inattendue pendant le cycle d'inférence — cycle ignoré",
                    exc_info=True,
                )
                self._call_detection_callback({
                    "detections": [],
                    "roi": roi,
                    "x_pad": (x_pad, y_pad, w_pad, h_pad, x, y, w, h),
                    "y_pad": None
                })
                time.sleep(1)
                continue
            if self.is_detection is True:
                if len(current_detections) > 0:
                    if len(self.detections) == 0:
                        self.detections = current_detections
                    else:
                        self.detections += current_detections  # Utiliser extend() au lieu de np.vstack()

                else:
                    self.detections = []
                self.logger.debug(f"Nombre de détections : {len(self.detections)}")
                previous_detection = len(self.past_detections) > 0
                current_detection = len(self.detections) > 0
                if not previous_detection and current_detection:
                    self.is_detection = True
                    top_detection = time.time()
                    self.logger.debug(f"Détection initiale : {self.detections} à {time.asctime(time.localtime(top_detection))}")
                if previous_detection and not current_detection:
                    self.is_detection = False
                    top_detection = time.time()
                    self.logger.info(f"Plus de détection depuis {time.asctime(time.localtime(top_detection))}")
                # Callback pour transmettre les résultats

            self._call_detection_callback({
                "detections": self.detections,
                "roi": roi,
                "x_pad": (x_pad, y_pad, w_pad, h_pad, x, y, w, h),
                "y_pad": None  # y_pad n'est plus utilisé directement, inclus dans le tuple
            })
            self.past_detections = self.detections
            self.detections = []
            # self.old_motion_bool = motion_bool

            # 🚀 Réinitialiser les skips consécutifs après une inférence réussie
            self.consecutive_skips = 0
            self.last_motion_time = time.time()

            # 🚀 Sleep adaptatif selon l'activité
            # Après inférence = sleep court pour traiter les prochaines frames rapidement
            if motion_bool and len(self.detections) > 0:
                time.sleep(0.005)  # 5ms si détection active
            else:
                time.sleep(0.01)   # 10ms sinon

    def switch_inference_mode(self):
        """Bascule entre YOLO (predict_frame) et RFDETR (predict_frame_rf_detr)."""
        if self.fonction == FONCTION_RFDETR:
            self.fonction = FONCTION_YOLO
            self.url = rf"{URL_YOLO}/{self.fonction}/"
            # self.class_id = 1
        else:
            self.fonction = FONCTION_RFDETR
            # self.class_id = 0
            self.url = rf"{URL_RFDETR}/{self.fonction}/"
        self.logger.info(f"Mode d'inférence changé : {self.fonction}")

    @property
    def inference_mode(self):
        return "RFDETR" if self.fonction == FONCTION_RFDETR else "YOLO"

    def get_optimization_stats(self):
        """Retourne les statistiques d'optimisation de l'inférence."""
        if self.total_frames_processed == 0:
            return {"skip_rate": 0, "total_frames": 0, "skipped_frames": 0}

        skip_rate = (self.inference_skip_count / self.total_frames_processed) * 100
        avg_sleep = 0.01  # Valeur par défaut
        if hasattr(self, 'consecutive_skips'):
            # Estimation du sleep moyen basé sur les skips consécutifs
            avg_sleep = min(0.001 + (self.consecutive_skips * 0.002), 0.05)

        return {
            "skip_rate": round(skip_rate, 1),
            "total_frames": self.total_frames_processed,
            "skipped_frames": self.inference_skip_count,
            "inference_fps": round(1.0 / self.min_inference_interval, 1),
            "time_saved_ms": self.inference_skip_count * 100,  # 100ms économisées par frame sautée
            "consecutive_skips": getattr(self, 'consecutive_skips', 0),
            "avg_sleep_ms": round(avg_sleep * 1000, 1),
            "latency": self.get_timing_stats(),
        }