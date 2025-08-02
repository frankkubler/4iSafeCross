import cv2
import numpy as np
import logging
from utils.constants import MOTIONTRESHOLD

class MotionDetector:
    def __init__(self):
        super().__init__()
        self.fgbg = cv2.createBackgroundSubtractorMOG2()
        self.logger = logging.getLogger(__name__)
        # Pour la méthode frame differencing (type Frigate)
        self.background = None
        self.frame_diff_threshold = 50  # seuil de différence pixel (ajustable)
        self.min_area = 30  # surface minimale pour considérer un mouvement

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
        motion = True if white_pixels > white_pixels_threshold else False
        self.logger.debug(f'[FrameDiff] {motion} with {white_pixels}')
        return motion, white_pixels, thresh

    def detect(self, frame, white_pixels_threshold) -> bool:
        motion = False
        if frame is None or not isinstance(frame, np.ndarray):
            self.logger.warning("Frame invalide pour la détection de mouvement (None ou non-numpy array)")
            return False, 0
        motion_mask = self.fgbg.apply(frame, -1)
        white_pixels = cv2.countNonZero(motion_mask)
        motion = True if white_pixels > white_pixels_threshold else False
        self.logger.debug(f'{motion} with  {white_pixels}')
        return motion, white_pixels

    def get_motion_roi_info_framediff(self, frame, padding=40, white_pixels_threshold=MOTIONTRESHOLD):
        motion, white_pixels, mask = self.detect_frame_diff(frame, white_pixels_threshold)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi = None
        x_pad, y_pad = 0, 0
        x, y, w, h = 0, 0, 0, 0
        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest_contour) > self.min_area:
                x, y, w, h = cv2.boundingRect(largest_contour)
                x_pad = max(x - padding, 0)
                y_pad = max(y - padding, 0)
                w_pad = min(w + 2 * padding, frame.shape[1] - x_pad)
                h_pad = min(h + 2 * padding, frame.shape[0] - y_pad)
                roi = frame[y_pad:y_pad+h_pad, x_pad:x_pad+w_pad]
        return roi, motion, white_pixels, x_pad, y_pad, x, y, w, h

    def get_motion_roi_info(self, frame, padding=40, white_pixels_threshold=MOTIONTRESHOLD):
        motion, white_pixels = self.detect(frame, white_pixels_threshold)
        motion_mask = self.fgbg.apply(frame, -1)
        contours, _ = cv2.findContours(motion_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi = None
        x_pad, y_pad = 0, 0
        x, y, w, h = 0, 0, 0, 0
        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest_contour) > 100:
                x, y, w, h = cv2.boundingRect(largest_contour)
                x_pad = max(x - padding, 0)
                y_pad = max(y - padding, 0)
                w_pad = min(w + 2 * padding, frame.shape[1] - x_pad)
                h_pad = min(h + 2 * padding, frame.shape[0] - y_pad)
                roi = frame[y_pad:y_pad+h_pad, x_pad:x_pad+w_pad]
        return roi, motion, white_pixels, x_pad, y_pad, x, y, w, h
