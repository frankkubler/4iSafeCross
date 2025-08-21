import threading
import time
import numpy as np
import logging
import requests
import io
import cv2
from utils.constants import MOTIONTRESHOLD, INF_THRESHOLD, DETECTION, URL, FONCTION
from src.motion import MotionDetector

class InferenceServerThread(threading.Thread):
    def __init__(self, home_dir, get_frame_func, white_pixels_threshold=MOTIONTRESHOLD, detection_callback=None, stop_event=None):
        super().__init__()
        self.home_dir = home_dir
        self.get_frame_func = get_frame_func  # Fonction pour obtenir la frame courante
        self.detection_callback = detection_callback  # Callback pour envoyer les résultats
        self.stop_event = stop_event or threading.Event()
        self.logger = logging.getLogger(__name__).getChild(__class__.__name__)
        self.fonction = FONCTION
        self.url = rf"{URL}/{self.fonction}"
        self.is_detection = False
        self.motion_detector = MotionDetector()
        self.white_pixels_threshold = white_pixels_threshold
        self._motion = False  # Attribut privé
        # self.old_motion_bool = False
        self.past_detections = []
        self.detections = []
        self.confidence_threshold = INF_THRESHOLD
        if DETECTION == 'extended':
            self.class_id = [1, 3, 6, 7, 8]
        else:
            self.class_id = [1]       
        # self.class_id = 1 if "rf_detr" in self.fonction else 0

    @property
    def motion(self):
        return self._motion

    def _call_detection_callback(self, result):
        """Appelle le callback de détection s'il est défini."""
        if self.detection_callback:
            self.detection_callback(result)
            # self.logger.info(f"Appel de la fonction de rappel avec {len(detections)} détections.")

    def run(self):
        self.logger.info(f"Thread d'inférence démarré pour {self.url}")
        while not self.stop_event.is_set():
            frame = self.get_frame_func()
            if frame is None:
                time.sleep(0.1)
                continue
            # Détection de mouvement
            roi, motion_bool, white_pixels, coords = self.motion_detector.get_mog2_motion_roi_info(
                frame,
                padding=getattr(self.motion_detector, 'padding', 40),
                white_pixels_threshold=self.white_pixels_threshold,
                min_contour_area=getattr(self.motion_detector, 'min_area', 30),
                varThreshold=getattr(self.motion_detector, 'varThreshold', 16),
                history=getattr(self.motion_detector, 'history', 500),
                detectShadows=getattr(self.motion_detector, 'detectShadows', True)
            )
            # Si tu veux aussi passer varThreshold, history, detectShadows dynamiquement, il faut les ajouter dans la signature de get_mog2_motion_roi_info et dans motion.py
            x_pad, y_pad, w_pad, h_pad, x, y, w, h = coords
            # motion_bool, whites_pixels = self.motion_detector.detect(frame, self.white_pixels_threshold)
            self._motion = motion_bool  # Met à jour l'attribut privé
            # self.logger.info(f"Détection de mouvement : {motion_bool} avec {whites_pixels} pixels blancs")
            if (not motion_bool) or (w_pad <= 0 or h_pad <= 0):
                # Appeler le callback avec une détection vide pour effacer l'affichage côté client
                self._call_detection_callback([])
                self.logger.debug("Aucune détection de mouvement ou zone de mouvement invalide (w_pad <= 0 ou h_pad <= 0).")
                time.sleep(0.1)
                continue
            
            # Découper la frame sur la zone de mouvement
            # frame_roi = frame[y_pad:y_pad+h_pad, x_pad:x_pad+w_pad]
            
            buffer = io.BytesIO()
            np.save(buffer, frame, allow_pickle=True)
            buffer.seek(0)
            current_detections = []
            try:
                response = requests.post(
                    self.url,
                    files={"frame": buffer.getvalue()},
                    params={"confidence": self.confidence_threshold}
                )
                if response.status_code == 200:
                    detections = response.json().get("detections", [])
                    if detections:
                        # Remettre les coordonnées dans le repère image d'origine
                        current_detections = np.array([
                            [
                                d["x_min"], # + x_pad,
                                d["y_min"], # + y_pad,
                                d["x_max"], #+ x_pad,
                                d["y_max"], #+ y_pad,
                                d["confidence"],
                                d["class_id"],
                                d["tracking_id"]
                            ]
                            for d in detections if d["class_id"] in self.class_id
                        ])
                        if len(current_detections) > 0:
                            self.is_detection = True
                            self.logger.debug(f"Détections actuelles : {current_detections}")
                        else:
                            self.is_detection = False
                            self.logger.debug("Aucune détection de classe 0 trouvée.")
                    else:
                        self.logger.debug("Aucune détection reçue.")
                        self.is_detection = False
                        current_detections = []
                else:
                    self.logger.error("La réponse du serveur est invalide ou absente.")
            except requests.ConnectionError:
                self.logger.error("Impossible de se connecter au serveur.")
                time.sleep(1)
                continue
            if self.is_detection is True:
                if len(current_detections) > 0:
                    if len(self.detections) == 0:
                        self.detections = current_detections
                    else:
                        self.detections = np.vstack((self.detections, current_detections))
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
            time.sleep(0.05)

    def switch_inference_mode(self):
        """Bascule entre YOLO (predict_frame) et RFDETR (predict_frame_rf_detr)."""
        if self.fonction == "predict_frame/" or self.fonction == "/predict_frame/":
            self.fonction = "/predict_frame_rf_detr/"
            self.class_id = 1
        else:
            self.fonction = "/predict_frame/"
            self.class_id = 0
        self.url = rf"{URL}/{self.fonction}"
        self.logger.info(f"Mode d'inférence changé : {self.fonction}")

    @property
    def inference_mode(self):
        return "RFDETR" if self.fonction == "/predict_frame_rf_detr/" else "YOLO"