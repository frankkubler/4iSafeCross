import cv2
import numpy as np
import logging
from utils.constants import MOTIONTRESHOLD

class MotionDetector:

    def __init__(self, history=500, varThreshold=16, detectShadows=True, padding=40, min_contour_area=30):
        super().__init__()
        self.fgbg = cv2.createBackgroundSubtractorMOG2(history=history, varThreshold=varThreshold, detectShadows=detectShadows)
        self.logger = logging.getLogger(__name__)
        # Pour la méthode frame differencing (type Frigate)
        self.background = None
        self.frame_diff_threshold = 50  # seuil de différence pixel (ajustable)
        self.min_area = min_contour_area  # surface minimale pour considérer un mouvement
        self.padding = padding

    def detect_frame_diff(self, frame, white_pixels_threshold=MOTIONTRESHOLD):
        """
        Détection de mouvement par différence d'images (type Frigate).
        Retourne (motion, white_pixels, mask)
        """
        if frame is None or not isinstance(frame, np.ndarray):
            self.logger.warning("Frame invalide pour la détection de mouvement (None ou non-numpy array)")
            return False, 0, None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        if self.background is None:
            self.background = gray.copy().astype("float")
            return False, 0, np.zeros_like(gray)
        # Calcul de la différence absolue
        cv2.accumulateWeighted(gray, self.background, 0.05)  # update background
        background_uint8 = cv2.convertScaleAbs(self.background)
        frame_delta = cv2.absdiff(background_uint8, gray)
        # Seuillage
        thresh = cv2.threshold(frame_delta, self.frame_diff_threshold, 255, cv2.THRESH_BINARY)[1]
        # Morphologie pour réduire le bruit
        thresh = cv2.dilate(thresh, None, iterations=2)
        white_pixels = cv2.countNonZero(thresh)
        motion = white_pixels > white_pixels_threshold
        self.logger.debug(f'[FrameDiff] {motion} with {white_pixels}')
        return motion, white_pixels, thresh

    def get_motion_roi_info_framediff(self, frame, padding=None, white_pixels_threshold=MOTIONTRESHOLD):
        if padding is None:
            padding = self.padding
        motion, white_pixels, mask = self.detect_frame_diff(frame, white_pixels_threshold)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi = None
        x_pad, y_pad = 0, 0
        x, y, w, h = 0, 0, 0, 0
        w_pad, h_pad = 0, 0
        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest_contour) > self.min_area:
                x, y, w, h = cv2.boundingRect(largest_contour)
                x_pad = max(x - padding, 0)
                y_pad = max(y - padding, 0)
                w_pad = min(w + 2 * padding, frame.shape[1] - x_pad)
                h_pad = min(h + 2 * padding, frame.shape[0] - y_pad)
                roi = frame[y_pad:y_pad+h_pad, x_pad:x_pad+w_pad]
        # Retourne aussi les coordonnées brutes (x, y, w, h) dans le tuple padding
        return roi, motion, white_pixels, (x_pad, y_pad, w_pad, h_pad, x, y, w, h)

    def get_mog2_motion_roi_info(self, frame, padding=None, white_pixels_threshold=MOTIONTRESHOLD, min_contour_area=None):
        if padding is None:
            padding = self.padding
        if min_contour_area is None:
            min_contour_area = self.min_area
        motion_mask = self.fgbg.apply(frame, -1)
        _, motion_mask = cv2.threshold(motion_mask, 200, 255, cv2.THRESH_BINARY) # Seuillage pour obtenir un masque binaire sans ombres
        white_pixels = cv2.countNonZero(motion_mask)
        motion = white_pixels > white_pixels_threshold
        self.logger.debug(f'{motion} with  {white_pixels}')
        contours, _ = cv2.findContours(motion_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi = None
        x_pad, y_pad = 0, 0
        x, y, w, h = 0, 0, 0, 0
        w_pad, h_pad = 0, 0
        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest_contour) > min_contour_area:
                x, y, w, h = cv2.boundingRect(largest_contour)
                x_pad = max(x - padding, 0)
                y_pad = max(y - padding, 0)
                w_pad = min(w + 2 * padding, frame.shape[1] - x_pad)
                h_pad = min(h + 2 * padding, frame.shape[0] - y_pad)
                roi = frame[y_pad:y_pad+h_pad, x_pad:x_pad+w_pad]
        # Retourne aussi les coordonnées brutes (x, y, w, h) dans le tuple padding
        return roi, motion, white_pixels, (x_pad, y_pad, w_pad, h_pad, x, y, w, h)

    def get_motion_roi_info_improved(
        self,
        frame,
        padding=40,
        white_pixels_threshold=MOTIONTRESHOLD,
        min_contour_area=None,
        frame_diff_threshold=None
    ):
        """
        min_contour_area : surface minimale pour considérer un mouvement (par défaut self.min_area)
        white_pixels_threshold : seuil de pixels blancs pour considérer un mouvement
        padding : marge autour du contour détecté
        frame_diff_threshold : seuil de différence de pixel pour le seuillage (par défaut self.frame_diff_threshold)
        """
        threshold = frame_diff_threshold if frame_diff_threshold is not None else self.frame_diff_threshold
        _, white_pixels, mask = self.improved_motion_detect(frame, white_pixels_threshold, threshold)
        motion = True if white_pixels > white_pixels_threshold else False
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi = None
        x_pad, y_pad = 0, 0
        x, y, w, h = 0, 0, 0, 0
        w_pad, h_pad = 0, 0
        area_threshold = min_contour_area if min_contour_area is not None else self.min_area
        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest_contour) > area_threshold:
                x, y, w, h = cv2.boundingRect(largest_contour)
                x_pad = max(x - padding, 0)
                y_pad = max(y - padding, 0)
                w_pad = min(w + 2 * padding, frame.shape[1] - x_pad)
                h_pad = min(h + 2 * padding, frame.shape[0] - y_pad)
                roi = frame[y_pad:y_pad+h_pad, x_pad:x_pad+w_pad]
        # Retourne aussi les coordonnées brutes (x, y, w, h) dans le tuple padding
        return roi, motion, white_pixels, (x_pad, y_pad, w_pad, h_pad, x, y, w, h)

    def improved_motion_detect(self, frame, white_pixels_threshold=MOTIONTRESHOLD, frame_diff_threshold=None):
        """
        Détection de mouvement améliorée inspirée de Frigate.
        Retourne (motion, white_pixels, mask)
        """
        if frame is None or not isinstance(frame, np.ndarray):
            self.logger.warning("Frame invalide pour la détection de mouvement (None ou non-numpy array)")
            return False, 0, None

        # Conversion en niveaux de gris et flou
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        # Initialisation du fond si nécessaire
        if self.background is None:
            self.background = gray.copy().astype("float")
            return False, 0, np.zeros_like(gray)

        # Mise à jour du fond
        cv2.accumulateWeighted(gray, self.background, 0.05)
        background_uint8 = cv2.convertScaleAbs(self.background)
        frame_delta = cv2.absdiff(background_uint8, gray)

        # Utilisation du threshold paramétrable si fourni, sinon adaptatif
        if frame_diff_threshold is not None:
            thresh = cv2.threshold(frame_delta, frame_diff_threshold, 255, cv2.THRESH_BINARY)[1]
        else:
            thresh = cv2.adaptiveThreshold(
                frame_delta,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                11,
                2
            )

        # Suppression du bruit
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        thresh = cv2.dilate(thresh, None, iterations=2)

        white_pixels = cv2.countNonZero(thresh)
        # motion = True if white_pixels > white_pixels_threshold else False
        # self.logger.debug(f'[ImprovedMotion] {motion} with {white_pixels}')
        return white_pixels, thresh