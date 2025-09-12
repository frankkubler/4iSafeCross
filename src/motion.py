import cv2
import numpy as np
import logging
from utils.constants import MOTIONTHRESHOLD

class MotionDetector:
    def __init__(self, history=500, varThreshold=16, detectShadows=True,
                 padding=40, min_contour_area=30):
        self.history = history
        self.varThreshold = varThreshold
        self.detectShadows = detectShadows
        self.padding = padding
        self.min_contour_area = min_contour_area

        self.fgbg = cv2.createBackgroundSubtractorMOG2(
            history=self.history,
            varThreshold=self.varThreshold,
            detectShadows=self.detectShadows
        )
        self.logger = logging.getLogger(__name__).getChild(__class__.__name__)
        self.logger.info(f"MotionDetector instancié: history={self.history}, varThreshold={self.varThreshold}, detectShadows={self.detectShadows}, padding={self.padding}, min_contour_area={self.min_contour_area}")
        self.background = None  # pour méthode frame differencing
        self.frame_diff_threshold = 50

    def update_fgbg_params(self, varThreshold=None, history=None, detectShadows=None):
        self.logger.debug(f"Appel update_fgbg_params avec: varThreshold={varThreshold}, history={history}, detectShadows={detectShadows}")
        updated = False
        if varThreshold is not None and varThreshold != self.varThreshold:
            self.varThreshold = varThreshold
            updated = True
        if history is not None and history != self.history:
            self.history = history
            updated = True
        if detectShadows is not None and detectShadows != self.detectShadows:
            self.detectShadows = detectShadows
            updated = True
        if updated:
            self.logger.info(f"Updating MOG2 params: history={self.history}, varThreshold={self.varThreshold}, detectShadows={self.detectShadows}")
            self.fgbg = cv2.createBackgroundSubtractorMOG2(
                history=self.history,
                varThreshold=self.varThreshold,
                detectShadows=self.detectShadows
            )

    def get_mog2_motion_info(self, frame, padding=None, white_pixels_threshold=MOTIONTHRESHOLD,
                                 min_contour_area=None):
        if padding is None:
            padding = self.padding
        if min_contour_area is None:
            min_contour_area = self.min_contour_area

        mask = self.fgbg.apply(frame, -1)
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)

        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.dilate(mask, kernel, iterations=2)

        white_pixels = cv2.countNonZero(mask)
        motion = white_pixels > white_pixels_threshold

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi = None
        x, y, w, h = 0, 0, 0, 0
        x_pad, y_pad, w_pad, h_pad = 0, 0, 0, 0

        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest_contour) > min_contour_area:
                x, y, w, h = cv2.boundingRect(largest_contour)
                x_pad = max(x - padding, 0)
                y_pad = max(y - padding, 0)
                w_pad = min(w + 2 * padding, frame.shape[1] - x_pad)
                h_pad = min(h + 2 * padding, frame.shape[0] - y_pad)
                roi = frame[y_pad:y_pad+h_pad, x_pad:x_pad+w_pad]

        return roi, motion, white_pixels, (x_pad, y_pad, w_pad, h_pad, x, y, w, h)
