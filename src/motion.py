import cv2
import numpy as np
import logging
from utils.constants import MOTIONTHRESHOLD


class MotionDetector:
    def __init__(self, history=500, varThreshold=11, detectShadows=True,
                 padding=40, min_contour_area=30,
                 motion_on_frames=2, motion_off_frames=5,
                 use_gaussian_blur=True, use_aspect_filter=False,
                 min_single_contour=3000):
        self.history = history
        self.varThreshold = varThreshold
        self.detectShadows = detectShadows
        self.padding = padding
        self.min_contour_area = min_contour_area

        # Hystérésis temporelle : évite les faux positifs/négatifs sur 1 frame
        self.motion_on_frames = motion_on_frames    # frames consécutives pour confirmer ON
        self.motion_off_frames = motion_off_frames  # frames consécutives pour confirmer OFF
        self._consec_motion = 0
        self._consec_no_motion = 0
        self._confirmed_motion = False

        # Pré-traitement Gaussian blur (réduit bruit capteur, ~2ms sur Jetson)
        self.use_gaussian_blur = use_gaussian_blur

        # Filtrage optionnel par ratio h/w des contours (exclut artefacts horizontaux plats)
        self.use_aspect_filter = use_aspect_filter

        # Surface minimale d'un seul contour pour déclencher le mouvement (indépendamment du total)
        self.min_single_contour = min_single_contour

        self.fgbg = cv2.createBackgroundSubtractorMOG2(
            history=self.history,
            varThreshold=self.varThreshold,
            detectShadows=self.detectShadows
        )
        self.logger = logging.getLogger(__name__).getChild(__class__.__name__)
        self.logger.debug(
            f"MotionDetector instancié: history={self.history}, varThreshold={self.varThreshold}, "
            f"detectShadows={self.detectShadows}, padding={self.padding}, "
            f"min_contour_area={self.min_contour_area}, motion_on_frames={self.motion_on_frames}, "
            f"motion_off_frames={self.motion_off_frames}, gaussian_blur={self.use_gaussian_blur}, "
            f"aspect_filter={self.use_aspect_filter}, min_single_contour={self.min_single_contour}"
        )
        self.background = None  # pour méthode frame differencing
        self.frame_diff_threshold = 50

    def update_fgbg_params(self, varThreshold=None, history=None, detectShadows=None):
        """Met à jour les paramètres MOG2 dynamiquement.

        Args:
            varThreshold: Seuil de variance pour la classification pixel/fond.
            history: Nombre de frames pour le modèle de fond.
            detectShadows: Activer la détection des ombres.
        """
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
        self.logger.info(f"Update {updated} : Paramètres après mise à jour: history={history} / {self.history}, varThreshold= {varThreshold} /  {self.varThreshold}, detectShadows={detectShadows} / {self.detectShadows}")
        if updated:
            self.logger.info(f"Updating MOG2 params: history={self.history}, varThreshold={self.varThreshold}, detectShadows={self.detectShadows}")
            self.fgbg = cv2.createBackgroundSubtractorMOG2(
                history=self.history,
                varThreshold=self.varThreshold,
                detectShadows=self.detectShadows
            )

    def update_detection_params(self, motion_on_frames=None, motion_off_frames=None,
                                 use_gaussian_blur=None, use_aspect_filter=None,
                                 min_single_contour=None):
        """Met à jour les paramètres de détection (hystérésis, filtrages).

        Args:
            motion_on_frames: Frames consécutives pour confirmer le mouvement ON.
            motion_off_frames: Frames consécutives pour confirmer l'absence de mouvement.
            use_gaussian_blur: Active le flou gaussien avant MOG2.
            use_aspect_filter: Active le filtrage des contours plats (h/w < 0.3).
            min_single_contour: Surface minimale d'un contour seul pour déclencher.
        """
        if motion_on_frames is not None:
            self.motion_on_frames = int(motion_on_frames)
        if motion_off_frames is not None:
            self.motion_off_frames = int(motion_off_frames)
        if use_gaussian_blur is not None:
            self.use_gaussian_blur = bool(use_gaussian_blur)
        if use_aspect_filter is not None:
            self.use_aspect_filter = bool(use_aspect_filter)
        if min_single_contour is not None:
            self.min_single_contour = int(min_single_contour)
        self.logger.info(
            f"Paramètres détection mis à jour: on_frames={self.motion_on_frames}, "
            f"off_frames={self.motion_off_frames}, gaussian_blur={self.use_gaussian_blur}, "
            f"aspect_filter={self.use_aspect_filter}, min_single={self.min_single_contour}"
        )

    def get_mog2_motion_info(self, frame, padding=None, white_pixels_threshold=MOTIONTHRESHOLD,
                             min_contour_area=None):
        """Détecte le mouvement avec MOG2, hystérésis temporelle et filtrage des contours.

        Args:
            frame: Frame BGR (numpy array).
            padding: Marge en pixels autour du contour le plus grand pour le ROI.
            white_pixels_threshold: Somme des surfaces des contours significatifs pour déclencher.
            min_contour_area: Surface minimale pour qu'un contour soit considéré.

        Returns:
            Tuple (roi, motion_confirmed, white_pixels, coords).
            - roi: Région d'intérêt (numpy array ou None).
            - motion_confirmed: Booléen lissé par l'hystérésis.
            - white_pixels: Nombre de pixels blancs bruts dans le masque.
            - coords: (x_pad, y_pad, w_pad, h_pad, x, y, w, h).
        """
        if padding is None:
            padding = self.padding
        if min_contour_area is None:
            min_contour_area = self.min_contour_area

        # Pré-traitement : flou gaussien optionnel pour atténuer le bruit caméra
        if self.use_gaussian_blur:
            blurred = cv2.GaussianBlur(frame, (5, 5), 0)
        else:
            blurred = frame

        mask = self.fgbg.apply(blurred, -1)
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)

        # Morphologie améliorée : OPEN(5×5) supprime les artefacts ponctuels,
        # DILATE regroupe les zones proches, CLOSE remplit les trous dans les silhouettes
        kernel_open = np.ones((5, 5), np.uint8)
        kernel_std = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
        mask = cv2.dilate(mask, kernel_std, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_std)

        white_pixels = cv2.countNonZero(mask)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi = None
        x, y, w, h = 0, 0, 0, 0
        x_pad, y_pad, w_pad, h_pad = 0, 0, 0, 0

        # --- Filtrage des contours significatifs ---
        significant_contours = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_contour_area:
                continue
            if self.use_aspect_filter:
                bx, by, bw, bh = cv2.boundingRect(c)
                aspect = bh / bw if bw > 0 else 0
                if aspect < 0.3:
                    continue
            significant_contours.append(c)

        total_significant_area = sum(cv2.contourArea(c) for c in significant_contours)
        largest_contour_area = max((cv2.contourArea(c) for c in significant_contours), default=0)

        # Déclenchement brut : grande surface totale OU un seul contour suffisamment grand
        motion_raw = (total_significant_area > white_pixels_threshold) or (largest_contour_area > self.min_single_contour)

        # --- Hystérésis temporelle ---
        if motion_raw:
            self._consec_motion += 1
            self._consec_no_motion = 0
        else:
            self._consec_no_motion += 1
            self._consec_motion = 0

        if self._confirmed_motion:
            if self._consec_no_motion >= self.motion_off_frames:
                self._confirmed_motion = False
        else:
            if self._consec_motion >= self.motion_on_frames:
                self._confirmed_motion = True

        self.logger.debug(
            f"motion_raw={motion_raw} | white_px={white_pixels} | sig_area={total_significant_area:.0f} "
            f"| largest={largest_contour_area:.0f} | consec_on={self._consec_motion} "
            f"| consec_off={self._consec_no_motion} | confirmed={self._confirmed_motion}"
        )

        # ROI basé sur le plus grand contour significatif
        if significant_contours:
            largest_contour = max(significant_contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest_contour)
            x_pad = max(x - padding, 0)
            y_pad = max(y - padding, 0)
            w_pad = min(w + 2 * padding, frame.shape[1] - x_pad)
            h_pad = min(h + 2 * padding, frame.shape[0] - y_pad)
            roi = frame[y_pad:y_pad+h_pad, x_pad:x_pad+w_pad]

        return roi, self._confirmed_motion, white_pixels, (x_pad, y_pad, w_pad, h_pad, x, y, w, h)
