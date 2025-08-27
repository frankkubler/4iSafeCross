import threading
import time
import numpy as np
import logging
import requests
import io
import cv2
from src.context_vehicle import infer_in_vehicle_context
from utils.constants import (MOTIONTRESHOLD, INF_THRESHOLD,
                             DETECTION, URL, FONCTION)
from src.motion import MotionDetector

class PoseAnalyzer:
    """
    Classe pour analyser les keypoints de pose et déterminer la stature de la personne.
    Utilise les indices COCO pour les keypoints.
    """
    # Indices COCO pour les keypoints pertinents
    LEFT_HIP = 11
    RIGHT_HIP = 12
    LEFT_KNEE = 13
    RIGHT_KNEE = 14
    LEFT_ANKLE = 15
    RIGHT_ANKLE = 16

    def __init__(self, confidence_threshold=0.5):
        self.confidence_threshold = confidence_threshold

    def filter_keypoints_by_confidence(self, pose_keypoints):
        """
        Filtre les keypoints dont la confidence est supérieure au seuil.
        Pose keypoints est une liste de dicts {"x": float, "y": float, "confidence": float} pour chaque point.
        """
        filtered = []
        for i, kp in enumerate(pose_keypoints):
            if isinstance(kp, dict) and kp.get("confidence", 0) > self.confidence_threshold:
                x = kp.get("x", 0)
                y = kp.get("y", 0)
                conf = kp.get("confidence", 0)
                filtered.append((i, x, y, conf))  # (index, x, y, conf)
        return filtered

    def analyze_stature(self, pose_keypoints):
        """
        Analyse la stature basée sur les keypoints filtrés.
        Retourne : 'debout', 'assis', 'jambes_masquees', ou 'inconnu'
        """
        filtered_kps = self.filter_keypoints_by_confidence(pose_keypoints)
        kp_dict = {idx: (x, y) for idx, x, y, conf in filtered_kps}

        # Vérifier si les keypoints des jambes sont présents
        hips_present = self.LEFT_HIP in kp_dict or self.RIGHT_HIP in kp_dict
        knees_present = self.LEFT_KNEE in kp_dict or self.RIGHT_KNEE in kp_dict
        ankles_present = self.LEFT_ANKLE in kp_dict or self.RIGHT_ANKLE in kp_dict

        if not hips_present or not knees_present:
            return 'jambes_masquees' if not ankles_present else 'inconnu'

        # Calculer les hauteurs moyennes
        hip_y = []
        if self.LEFT_HIP in kp_dict:
            hip_y.append(kp_dict[self.LEFT_HIP][1])
        if self.RIGHT_HIP in kp_dict:
            hip_y.append(kp_dict[self.RIGHT_HIP][1])
        avg_hip_y = sum(hip_y) / len(hip_y) if hip_y else 0

        knee_y = []
        if self.LEFT_KNEE in kp_dict:
            knee_y.append(kp_dict[self.LEFT_KNEE][1])
        if self.RIGHT_KNEE in kp_dict:
            knee_y.append(kp_dict[self.RIGHT_KNEE][1])
        avg_knee_y = sum(knee_y) / len(knee_y) if knee_y else 0

        ankle_y = []
        if self.LEFT_ANKLE in kp_dict:
            ankle_y.append(kp_dict[self.LEFT_ANKLE][1])
        if self.RIGHT_ANKLE in kp_dict:
            ankle_y.append(kp_dict[self.RIGHT_ANKLE][1])
        avg_ankle_y = sum(ankle_y) / len(ankle_y) if ankle_y else 0

        # Logique simple pour stature
        if avg_ankle_y > avg_knee_y > avg_hip_y and (avg_knee_y - avg_hip_y) > 50:  # Debout : cheville > genou > hanche
            return 'debout'
        elif abs(avg_knee_y - avg_hip_y) < 30 and avg_ankle_y > avg_knee_y:  # Assis : genou proche de hanche, cheville plus basse
            return 'assis'
        elif not ankles_present or not knees_present:
            return 'jambes_masquees'
        else:
            return 'inconnu'


class InferenceServerThread(threading.Thread):
    def __init__(self, home_dir, get_frame_func,
                 white_pixels_threshold=MOTIONTRESHOLD,
                 detection_callback=None, stop_event=None):
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
        self.pose_analyzer = PoseAnalyzer(confidence_threshold=0.5)

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
                        current_detections = [
                            {
                                "x_min": float(d["x_min"]),
                                "y_min": float(d["y_min"]),
                                "x_max": float(d["x_max"]),
                                "y_max": float(d["y_max"]),
                                "confidence": float(d["confidence"]),
                                "class_id": int(d["class_id"]),
                                "label": d.get("label", ""),
                                "tracker_id": int(d.get("tracker_id") or -1),  # Utilise 'or -1' au lieu de la valeur par défaut
                                "pose": d.get("pose", []),
                                "personne_type": (d.get("personne_type") if (d.get("personne_type") in ("sitting_in_vehicle", "pieton")) else ("pieton" if int(d["class_id"]) == 1 else ""))
                            }
                            for d in detections if d["class_id"] in self.class_id
                        ]
                        # # Si on a des personnes et des véhicules dans les détections actuelles, enrichir avec le contexte véhicule
                        # try:
                        #     if len(current_detections) > 0:
                        #         # frame shape (h,w,3)
                        #         h, w = frame.shape[:2]
                        #         # Utiliser toutes les détections reçues (pas seulement self.class_id)
                        #         all_dets = [
                        #             [
                        #                 float(d.get("x_min", 0)), float(d.get("y_min", 0)),
                        #                 float(d.get("x_max", 0)), float(d.get("y_max", 0)),
                        #                 float(d.get("confidence", 0)), int(d.get("class_id", -1)), int(d.get("tracker_id", -1)),
                        #                 d.get("personne_type") if d.get("personne_type") is not None else "inconnu"
                        #             ] for d in detections
                        #         ]
                        #         ctx = infer_in_vehicle_context(all_dets, (w, h))
                        #         # Mettre à jour personne_type pour les personnes concernées dans current_detections
                        #         for detection in current_detections:
                        #             cls_id = detection["class_id"]
                        #             trk_id = detection["tracker_id"] if detection["tracker_id"] is not None else -1
                        #             if cls_id == 1:
                        #                 in_vehicle = False
                        #                 if trk_id in ctx:
                        #                     in_vehicle = bool(ctx[trk_id].get('is_in_vehicle', False))
                        #                 detection["personne_type"] = 'sitting_in_vehicle' if in_vehicle else 'pieton'
                                
                        #         # Fallback de sécurité
                        #         for detection in current_detections:
                        #             if detection["class_id"] == 1 and detection["personne_type"] in (None, "", "inconnu"):
                        #                 detection["personne_type"] = 'pieton'
                        # except Exception:
                        #     pass
                        # Fallback de sécurité: si une personne a encore un label vide/inconnu, mettre 'pieton'
                        for detection in current_detections:
                            if detection["class_id"] == 1 and (detection["personne_type"] in (None, "", "inconnu")):
                                detection["personne_type"] = 'pieton'
                            # Analyser la stature si pose est présente et class_id == 1
                            if detection["class_id"] == 1 and detection["pose"]:
                                detection["stature"] = self.pose_analyzer.analyze_stature(detection["pose"])
                            else:
                                detection["stature"] = "inconnu"
                        if len(current_detections) > 0:
                            self.is_detection = True
                            self.logger.info(f"Détections actuelles : {current_detections}")
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
            time.sleep(0.01)  # 10ms

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
