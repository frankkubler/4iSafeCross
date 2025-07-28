import threading
import time
import numpy as np
import logging
import requests
import io
import cv2
from utils.constants import MOTIONTRESHOLD, INF_THRESHOLD


class InferenceServerThread(threading.Thread):
    def __init__(self, home_dir, get_frame_func, white_pixels_threshold=MOTIONTRESHOLD, detection_callback=None, stop_event=None):
        super().__init__()
        self.home_dir = home_dir
        self.get_frame_func = get_frame_func  # Fonction pour obtenir la frame courante
        self.detection_callback = detection_callback  # Callback pour envoyer les résultats
        self.stop_event = stop_event or threading.Event()
        self.logger = logging.getLogger(__name__).getChild(__class__.__name__)
        #self.fonction = "/predict_frame/"
        self.fonction = "/predict_frame_rf_detr/"
        self.url = rf"http://127.0.0.1:8002/{self.fonction}"
        self.is_detection = False
        self.motion_detector = MotionDetector()
        self.white_pixels_threshold = white_pixels_threshold
        self._motion = False  # Attribut privé
        # self.old_motion_bool = False
        self.past_detections = []
        self.detections = []
        self.confidence_threshold = INF_THRESHOLD
        self.class_id = 1 if "rf_detr" in self.fonction else 0

    @property
    def motion(self):
        return self._motion

    def _call_detection_callback(self, detections):
        """Appelle le callback de détection s'il est défini."""
        if self.detection_callback:
            self.detection_callback(detections)
            # self.logger.info(f"Appel de la fonction de rappel avec {len(detections)} détections.")

    def run(self):
        self.logger.info(f"Thread d'inférence démarré pour {self.url}")
        while not self.stop_event.is_set():
            frame = self.get_frame_func()
            if frame is None:
                time.sleep(0.1)
                continue
            # Détection de mouvement
            motion_bool, whites_pixels = self.motion_detector.detect(frame, self.white_pixels_threshold)
            self._motion = motion_bool  # Met à jour l'attribut privé
            # self.logger.info(f"Détection de mouvement : {motion_bool} avec {whites_pixels} pixels blancs")
            if not motion_bool:
                # Appeler le callback avec une détection vide pour effacer l'affichage côté client
                self._call_detection_callback([])
                self.logger.debug("Aucune détection de mouvement et pas de détection en cours.")
                time.sleep(0.1)
                continue
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
                        # Filtrer pour ne garder que les détections avec class_id == 0 (personnes)
                        current_detections = np.array([
                            [d["x_min"], d["y_min"], d["x_max"], d["y_max"], d["confidence"], d["class_id"]]
                            for d in detections if d["class_id"] == self.class_id
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

            self._call_detection_callback(self.detections)
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
        self.url = rf"http://127.0.0.1:8002/{self.fonction}"
        self.logger.info(f"Mode d'inférence changé : {self.fonction}")

    @property
    def inference_mode(self):
        return "RFDETR" if self.fonction == "/predict_frame_rf_detr/" else "YOLO"


class MotionDetector:
    def __init__(self):
        """
        Initializes a new instance of the MotionDetector class.

        This constructor initializes the MotionDetector object by calling the constructor of the base class using the `super()` function.
        It then creates a background subtractor object using the `cv2.createBackgroundSubtractorMOG2()` function and assigns it to the `fgbg` attribute.
        The `fgbg` attribute is used for background subtraction.

        Additionally, the constructor initializes the `motion` attribute to `False` and the `logger` attribute to a logger object obtained from the `logging.getLogger(__name__)` function.
        The `motion` attribute is used to track motion in a video frame, and the `logger` attribute is used for logging messages.

        Parameters:
            None

        Returns:
            None
        """
        super().__init__()
        self.fgbg = cv2.createBackgroundSubtractorMOG2()
        # self.fgbg = cv2.bgsegm.createBackgroundSubtractorGMG()
        # self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self.motion = False
        self.logger = logging.getLogger(__name__)

    def detect(self, frame, white_pixels_threshold=MOTIONTRESHOLD) -> bool:
        """
        A function that detects motion in a given frame.

        Parameters:
            self: The object instance.
            frame: The frame to analyze for motion.

        Returns:
            A tuple containing a boolean representing motion detection and the number of white pixels in the motion mask.
        """
        if frame is None or not isinstance(frame, np.ndarray):
            self.logger.warning("Frame invalide pour la détection de mouvement (None ou non-numpy array)")
            return False, 0
        # motion_mask = self.fgbg.apply(frame, 0.5)
        # self.logger.info(f"Détection de mouvement en cours... threshold: {white_pixels_threshold}")
        motion_mask = self.fgbg.apply(frame, -1)
        # motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_OPEN, self.kernel)
        # background = self.fgbg.getBackgroundImage()
        # # Display the motion mask and background
        # cv2.imshow('background', background)
        # cv2.imshow('Motion Mask', motion_mask)
        white_pixels = cv2.countNonZero(motion_mask)
        self.motion = True if white_pixels > white_pixels_threshold else False
        self.logger.debug(f'{self.motion} with  {white_pixels}')
        return self.motion, white_pixels
