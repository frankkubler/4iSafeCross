"""
collect_dataset.py — Collecte automatique d'images pour constituer un dataset YOLO.

Deux modes d'utilisation :

  MODE INTÉGRÉ (recommandé, zéro surcharge) :
    Importer DatasetCollectionThread dans app.py.
    Le thread réutilise les frames et les détections déjà calculées par l'app principale :
      - aucun nouveau pipeline GStreamer / connexion RTSP
      - aucune requête supplémentaire vers le serveur IA (port 8004)
      - aucun nouveau détecteur MOG2
    Seul coût réel : cv2.imencode + écriture disque toutes les N minutes (~3ms).
    Activation : DATASET_COLLECTION = true dans config/config.ini.

  MODE STANDALONE (déconseillé en parallèle de l'app) :
    uv run scripts/collect_dataset.py [options]
    Crée son propre CameraManager + inférence → double la charge.
    À réserver pour la collecte hors-production (tests, recette).

Stratégie d'échantillonnage (valable dans les deux modes) :
  1. Temporel   : toutes les INTERVAL_MINUTES minutes → diversité lumineuse/temporelle.
  2. Événementiel : quand des détections sont présentes, avec gap minimal de 5s
                    et quota horaire par classe (évite l'over-sampling).

Classes cibles (remappées depuis le modèle en mode "transfert") :
    0  →  forklift  (chariot à fourche)
    1  →  driver    (conducteur sur chariot)
    2  →  person    (piéton)
"""

import argparse
import configparser
import csv
import io
import logging
import os
import sys
import threading
import time
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import requests

# Ajouter la racine du projet au sys.path pour importer les modules locaux
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Configuration des classes cibles (remapping depuis le modèle courant)
# ---------------------------------------------------------------------------
# Le modèle en mode "transfert" renvoie des class_id 0–5 correspondant à :
#   0=person, 1=forklift, 2=driver  (les 3 premières sont celles qui nous intéressent)
# Remapping vers notre dataset custom avec 3 classes :
TRANSFERT_TO_DATASET = {
    0: 2,   # person  → classe 2 "person"
    1: 0,   # forklift → classe 0 "forklift"
    2: 1,   # driver  → classe 1 "driver"
    # Les class_id 3-5 sont ignorés (non pertinents pour ce dataset)
}
DATASET_CLASSES = {
    0: "forklift",
    1: "driver",
    2: "person",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("collect_dataset")


# ---------------------------------------------------------------------------
# Thread intégré (mode recommandé — zéro surcharge sur l'app principale)
# ---------------------------------------------------------------------------
class DatasetCollectionThread(threading.Thread):
    """
    Thread de collecte dataset à intégrer directement dans app.py.

    Réutilise les ressources de l'app principale :
      - get_frame_func  : même fonction que le thread d'inférence (frames déjà décodées)
      - shared_detections / shared_detections_lock : résultats IA déjà calculés
    Aucun pipeline GStreamer, aucun appel IA supplémentaire.

    Args:
        cam_idx: Index de la caméra (entier).
        get_frame_func: Callable → np.ndarray BGR (ex: get_frame_func_factory(i)).
        shared_detections: Dict partagé {cam_idx: list[dict]} mis à jour par le callback.
        shared_detections_lock: threading.Lock protégeant shared_detections.
        shared_motion_roi: Dict partagé {cam_idx: dict} avec w_pad/h_pad du mouvement (optionnel).
        shared_motion_roi_lock: Lock protégeant shared_motion_roi (optionnel).
        output_dir: Répertoire racine du dataset.
        interval_minutes: Intervalle en minutes entre deux captures temporelles.
        start_hour: Heure de début de collecte (0-23).
        end_hour: Heure de fin de collecte (0-23).
        max_per_class_per_hour: Quota max de frames par classe et par heure.
        background_interval_minutes: Intervalle en minutes entre deux captures background
            (frames sans détection, label vide — diversité lumineuse/fonds statiques).
        hard_neg_confidence: Seuil bas pour détecter les faux positifs potentiels (poteaux…).
            Une inférence secondaire est lancée avec ce seuil quand il y a du mouvement MOG2
            mais aucune détection au-dessus du seuil principal. Les frames résultantes sont
            sauvegardées avec un label vide (background) pour corriger les FP du modèle.
        bg_enabled: Active/désactive la stratégie background (stratégie 3).
        hard_neg_enabled: Active/désactive la stratégie hard negative (stratégie 4).
        inf_url: URL du serveur IA (nécessaire uniquement pour hard_neg).
        stop_event: threading.Event pour arrêter proprement le thread.
    """

    def __init__(
        self,
        cam_idx: int,
        get_frame_func: Callable,
        shared_detections: dict,
        shared_detections_lock: threading.Lock,
        shared_motion_roi: dict | None = None,
        shared_motion_roi_lock: threading.Lock | None = None,
        output_dir: str = "dataset",
        interval_minutes: int = 10,
        start_hour: int = 7,
        end_hour: int = 19,
        max_per_class_per_hour: int = 30,
        background_interval_minutes: int = 30,
        hard_neg_confidence: float = 0.35,
        bg_enabled: bool = True,
        hard_neg_enabled: bool = True,
        inf_url: str = "http://127.0.0.1:8004/predict_frame/",
        stop_event: threading.Event | None = None,
    ):
        super().__init__(daemon=True, name=f"DatasetCollector-cam{cam_idx}")
        self.cam_idx = cam_idx
        self.get_frame_func = get_frame_func
        self.shared_detections = shared_detections
        self.shared_detections_lock = shared_detections_lock
        self.shared_motion_roi = shared_motion_roi
        self.shared_motion_roi_lock = shared_motion_roi_lock
        self.output_dir = Path(output_dir)
        self.interval_minutes = interval_minutes
        self.start_hour = start_hour
        self.end_hour = end_hour
        self.max_per_class_per_hour = max_per_class_per_hour
        self.background_interval_sec = background_interval_minutes * 60
        self.hard_neg_confidence = hard_neg_confidence
        self.bg_enabled = bg_enabled
        self.hard_neg_enabled = hard_neg_enabled
        self.inf_url = inf_url
        self.stop_event = stop_event or threading.Event()
        self.logger = logging.getLogger(__name__).getChild(f"cam{cam_idx}")

        self.min_event_gap_seconds = 5.0
        self.hard_neg_gap_seconds = 30.0  # Gap minimal entre deux hard_neg (évite flood disque)
        self.last_temporal_capture: float = 0.0
        self.last_event_capture: float = 0.0
        self.last_background_capture: float = 0.0
        self.last_hard_neg_capture: float = 0.0
        self.class_hour_count: dict[tuple, int] = {}

        for sub in ("images/raw", "labels/raw"):
            (self.output_dir / sub).mkdir(parents=True, exist_ok=True)
        self._init_log()

        self.logger.info(
            f"✅ DatasetCollectionThread prêt (cam{cam_idx}) "
            f"| temporel {interval_minutes}min "
            f"| background {'✓' if bg_enabled else '✗'} {background_interval_minutes}min "
            f"| hard_neg {'✓' if hard_neg_enabled else '✗'} conf={hard_neg_confidence} "
            f"| {start_hour:02d}h–{end_hour:02d}h"
        )

    # ------------------------------------------------------------------
    # Helpers partagés avec le mode standalone
    # ------------------------------------------------------------------

    @property
    def log_path(self) -> Path:
        return self.output_dir / "sampling_log.csv"

    def _init_log(self) -> None:
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["timestamp", "cam_id", "filename", "strategy",
                     "n_detections", "classes_present"]
                )

    def _is_working_hours(self) -> bool:
        now = datetime.now().time()
        return dtime(self.start_hour, 0) <= now < dtime(self.end_hour, 0)

    def _class_quota_reached(self, class_id: int) -> bool:
        hour = datetime.now().hour
        return self.class_hour_count.get((self.cam_idx, hour, class_id), 0) >= self.max_per_class_per_hour

    def _increment_class_count(self, detections: list[dict]) -> None:
        hour = datetime.now().hour
        for cls in {d["dataset_class_id"] for d in detections if "dataset_class_id" in d}:
            key = (self.cam_idx, hour, cls)
            self.class_hour_count[key] = self.class_hour_count.get(key, 0) + 1

    def _remap_detections(self, raw_detections: list[dict]) -> list[dict]:
        """Convertit les détections de l'app (class_id modèle) vers les classes dataset."""
        result = []
        for d in raw_detections:
            dataset_class = TRANSFERT_TO_DATASET.get(int(d.get("class_id", -1)))
            if dataset_class is None:
                continue
            result.append({
                "x_min": float(d["x_min"]),
                "y_min": float(d["y_min"]),
                "x_max": float(d["x_max"]),
                "y_max": float(d["y_max"]),
                "confidence": float(d.get("confidence", 1.0)),
                "class_id": int(d["class_id"]),
                "dataset_class_id": dataset_class,
                "label": DATASET_CLASSES[dataset_class],
            })
        return result

    def _has_motion(self) -> bool:
        """Retourne True si le thread d'inférence voit du mouvement (MOG2 actif).

        Utilise shared_motion_roi si disponible (w_pad > 0 = zone de mouvement détectée).
        """
        if self.shared_motion_roi is None or self.shared_motion_roi_lock is None:
            return False
        with self.shared_motion_roi_lock:
            roi = self.shared_motion_roi.get(self.cam_idx, {})
        return roi.get("w_pad", 0) > 0 and roi.get("h_pad", 0) > 0

    def _run_hard_neg_inference(self, frame: np.ndarray) -> bool:
        """Lance une inférence à faible seuil pour détecter les faux positifs potentiels.

        Envoie la frame au serveur IA avec un seuil bas (hard_neg_confidence).
        Retourne True si une détection de type 'person' est trouvée dans la plage basse,
        ce qui signale un candidat faux positif (poteau, zone sombre, etc.).

        Args:
            frame: Image BGR courante.

        Returns:
            True si au moins une détection person borderline est trouvée.
        """
        try:
            with io.BytesIO() as buf:
                np.save(buf, frame, allow_pickle=True)
                buf.seek(0)
                resp = requests.post(
                    self.inf_url,
                    files={"frame": buf.getvalue()},
                    params={"confidence": self.hard_neg_confidence},
                    timeout=5,
                )
            if resp.status_code != 200:
                return False
            detections = resp.json().get("detections", [])
            # N'interresse que les class_id correspondant à 'person' dans le modèle courant
            person_class_ids = {k for k, v in TRANSFERT_TO_DATASET.items() if v == 2}
            return any(int(d.get("class_id", -1)) in person_class_ids for d in detections)
        except requests.RequestException:
            return False

    def _save_sample(
        self,
        frame: np.ndarray,
        detections: list[dict],
        strategy: str,
    ) -> str | None:
        """Sauvegarde une frame JPEG + son fichier label YOLO."""
        h, w = frame.shape[:2]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"cam{self.cam_idx}_{ts}_{strategy}"
        img_path = self.output_dir / "images" / "raw" / f"{filename}.jpg"
        lbl_path = self.output_dir / "labels" / "raw" / f"{filename}.txt"

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            self.logger.error(f"Échec encodage JPEG {filename}")
            return None
        img_path.write_bytes(buf.tobytes())

        yolo_lines = []
        for d in detections:
            cx = max(0.0, min(1.0, ((d["x_min"] + d["x_max"]) / 2) / w))
            cy = max(0.0, min(1.0, ((d["y_min"] + d["y_max"]) / 2) / h))
            bw = max(0.0, min(1.0, (d["x_max"] - d["x_min"]) / w))
            bh = max(0.0, min(1.0, (d["y_max"] - d["y_min"]) / h))
            yolo_lines.append(f"{d['dataset_class_id']} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
        lbl_path.write_text("\n".join(yolo_lines))

        classes_present = ",".join(sorted({d["label"] for d in detections}) if detections else ["neg"])
        with open(self.log_path, "a", newline="") as f:
            csv.writer(f).writerow(
                [datetime.now().isoformat(timespec="milliseconds"),
                 self.cam_idx, f"{filename}.jpg", strategy,
                 len(detections), classes_present]
            )

        self.logger.info(
            f"💾 [{strategy:10s}] cam{self.cam_idx} → {filename}.jpg "
            f"| {len(detections)} det. | {classes_present}"
        )
        self._increment_class_count(detections)
        return filename

    # ------------------------------------------------------------------
    # Boucle principale du thread
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Boucle de collecte : réutilise frames et détections déjà calculées."""
        interval_sec = self.interval_minutes * 60
        self.logger.info(f"🚀 Thread démarré — caméra {self.cam_idx}")

        while not self.stop_event.is_set():
            now = time.time()

            if not self._is_working_hours():
                self.stop_event.wait(60)
                continue

            frame = self.get_frame_func()
            if frame is None:
                self.stop_event.wait(1.0)
                continue

            # Lire les détections déjà calculées par le thread d'inférence (sans coût IA)
            with self.shared_detections_lock:
                raw_dets = list(self.shared_detections.get(self.cam_idx, []))
            detections = self._remap_detections(raw_dets)
            has_motion = self._has_motion()

            # ---- Stratégie 1 : temporelle ----
            # Capture périodique quoi qu'il arrive → diversité lumineuse/temporelle
            if now - self.last_temporal_capture >= interval_sec:
                self._save_sample(frame, detections, "temporal")
                self.last_temporal_capture = now

            # ---- Stratégie 2 : événementielle (détection active, gap respecté) ----
            elif (
                detections
                and now - self.last_event_capture >= self.min_event_gap_seconds
            ):
                rare_classes = {0, 1}  # forklift, driver
                present = {d["dataset_class_id"] for d in detections}
                has_rare = bool(present & rare_classes)
                quota_ok = any(not self._class_quota_reached(c) for c in present)

                if has_rare or quota_ok:
                    self._save_sample(frame, detections, "event")
                    self.last_event_capture = now

            # ---- Stratégie 3 : background (aucune détection, aucun mouvement) ----
            # Capture des fonds «propres» : poteaux au repos, allées vides, transitions
            # lumineuses normales. Label vide → backgrounds négatifs pour le modèle.
            elif (
                self.bg_enabled
                and not detections
                and not has_motion
                and now - self.last_background_capture >= self.background_interval_sec
            ):
                self._save_sample(frame, [], "background")
                self.last_background_capture = now

            # ---- Stratégie 4 : hard negative (mouvement MOG2 sans détection principale) ----
            # Typiquement : changement de luminosité sur un poteau, reflet, ombre mouvante.
            # Le modèle principal (seuil 0.7) ne détecte rien, mais une inférence à seuil
            # bas (0.35) peut révéler une activation borderline → on sauvegarde avec label
            # vide pour corriger ces faux positifs lors du fine-tuning.
            elif (
                self.hard_neg_enabled
                and has_motion
                and not detections
                and now - self.last_hard_neg_capture >= self.hard_neg_gap_seconds
            ):
                if self._run_hard_neg_inference(frame):
                    self._save_sample(frame, [], "hard_neg")
                    self.last_hard_neg_capture = now

            # Sleep court — ne consomme quasiment pas de CPU
            self.stop_event.wait(0.5)

        self.logger.info(f"⏹  Thread arrêté — caméra {self.cam_idx}")


# ---------------------------------------------------------------------------
# Classe standalone (mode script autonome — déconseillé en parallèle de l'app)
# ---------------------------------------------------------------------------
class DatasetCollector:
    """
    Collecte autonome avec son propre CameraManager et son propre thread d'inférence.

    ⚠️  NE PAS utiliser en parallèle de app.py : double les pipelines GStreamer,
    double les requêtes vers le serveur IA, double la charge CPU/réseau.
    Réservé aux sessions de collecte hors-production.

    Attributes:
        output_dir: Répertoire racine du dataset (default: dataset/).
        interval_minutes: Intervalle en minutes pour l'échantillonnage temporel.
        start_hour: Heure de début de collecte (0-23).
        end_hour: Heure de fin de collecte (0-23).
        confidence_threshold: Seuil de confiance pour retenir une détection.
        max_per_class_per_hour: Limite de frames par classe et par heure.
    """

    def __init__(
        self,
        output_dir: str = "dataset",
        interval_minutes: int = 10,
        start_hour: int = 7,
        end_hour: int = 19,
        confidence_threshold: float = 0.65,
        max_per_class_per_hour: int = 30,
    ):
        # Import ici pour ne pas charger GStreamer / motion en mode intégré
        from src.camera_manager import CameraManager as _CameraManager
        from src.motion import MotionDetector as _MotionDetector
        self._CameraManager = _CameraManager
        self._MotionDetector = _MotionDetector

        self.output_dir = Path(output_dir)
        self.interval_minutes = interval_minutes
        self.start_hour = start_hour
        self.end_hour = end_hour
        self.confidence_threshold = confidence_threshold
        self.max_per_class_per_hour = max_per_class_per_hour
        self.min_event_gap_seconds = 5.0

        self.config = self._load_config()
        self.inf_url = (
            self.config.get("APP", "URL_YOLO", fallback="http://127.0.0.1:8004")
            + self.config.get("APP", "FONCTION_YOLO", fallback="/predict_frame/")
        )
        self.motion_threshold = self.config.getint("APP", "MOTIONTHRESHOLD", fallback=10000)

        self._setup_dirs()
        self.log_path = self.output_dir / "sampling_log.csv"
        self._init_log()

        self.last_temporal_capture: dict[int, float] = {}
        self.last_event_capture: dict[int, float] = {}
        self.class_hour_count: dict[tuple, int] = {}
        self.motion_detectors: dict = {}

        logger.info(f"🗂  Dataset collector (standalone) → {self.output_dir.resolve()}")
        logger.warning(
            "⚠️  Mode standalone : crée ses propres pipelines GStreamer et appels IA. "
            "NE PAS utiliser en parallèle de app.py. "
            "Préférez DATASET_COLLECTION = true dans config.ini pour le mode intégré."
        )
        logger.info(f"   Intervalle temporel    : toutes les {interval_minutes} min")
        logger.info(f"   Plage horaire          : {start_hour:02d}h – {end_hour:02d}h")
        logger.info(f"   Seuil confiance IA     : {confidence_threshold}")
        logger.info(f"   URL serveur inférence  : {self.inf_url}")

    # ------------------------------------------------------------------
    # Init helpers
    # ------------------------------------------------------------------

    def _load_config(self) -> configparser.ConfigParser:
        """Charge config/config.ini depuis la racine du projet."""
        cfg = configparser.ConfigParser()
        cfg_path = PROJECT_ROOT / "config" / "config.ini"
        cfg.read(str(cfg_path), encoding="utf-8")
        return cfg

    def _setup_dirs(self) -> None:
        """Crée la structure de répertoires du dataset."""
        for sub in ("images/raw", "labels/raw"):
            (self.output_dir / sub).mkdir(parents=True, exist_ok=True)

    def _init_log(self) -> None:
        """Crée le fichier CSV de log si absent."""
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["timestamp", "cam_id", "filename", "strategy",
                     "n_detections", "classes_present", "motion_pixels"]
                )

    # ------------------------------------------------------------------
    # Vérifications horaires et compteurs
    # ------------------------------------------------------------------

    def _is_working_hours(self) -> bool:
        """Retourne True si l'heure courante est dans la plage de collecte."""
        now = datetime.now().time()
        return dtime(self.start_hour, 0) <= now < dtime(self.end_hour, 0)

    def _class_quota_reached(self, cam_id: int, class_id: int) -> bool:
        """Vérifie si le quota horaire pour cette classe/caméra est atteint."""
        hour = datetime.now().hour
        key = (cam_id, hour, class_id)
        return self.class_hour_count.get(key, 0) >= self.max_per_class_per_hour

    def _increment_class_count(self, cam_id: int, detections: list[dict]) -> None:
        """Incrémente les compteurs de classes pour la caméra donnée."""
        hour = datetime.now().hour
        seen = {d["dataset_class_id"] for d in detections if "dataset_class_id" in d}
        for cls in seen:
            key = (cam_id, hour, cls)
            self.class_hour_count[key] = self.class_hour_count.get(key, 0) + 1

    # ------------------------------------------------------------------
    # Inférence IA
    # ------------------------------------------------------------------

    def _run_inference(self, frame: np.ndarray) -> list[dict]:
        """
        Envoie une frame au serveur IA et retourne les détections filtrées + remappées.

        Args:
            frame: Image BGR (numpy array).

        Returns:
            Liste de dicts avec clés : x_min, y_min, x_max, y_max, confidence,
            class_id (original), dataset_class_id (remappe), label.
        """
        try:
            with io.BytesIO() as buf:
                np.save(buf, frame, allow_pickle=True)
                buf.seek(0)
                resp = requests.post(
                    self.inf_url,
                    files={"frame": buf.getvalue()},
                    params={"confidence": self.confidence_threshold},
                    timeout=5,
                )
            if resp.status_code != 200:
                return []

            raw_detections = resp.json().get("detections", [])
            result = []
            for d in raw_detections:
                orig_class = int(d.get("class_id", -1))
                dataset_class = TRANSFERT_TO_DATASET.get(orig_class)
                if dataset_class is None:
                    continue  # Classe non pertinente pour notre dataset
                result.append(
                    {
                        "x_min": float(d["x_min"]),
                        "y_min": float(d["y_min"]),
                        "x_max": float(d["x_max"]),
                        "y_max": float(d["y_max"]),
                        "confidence": float(d["confidence"]),
                        "class_id": orig_class,
                        "dataset_class_id": dataset_class,
                        "label": DATASET_CLASSES[dataset_class],
                    }
                )
            return result
        except requests.RequestException as exc:
            logger.warning(f"⚠️  Serveur IA injoignable : {exc}")
            return []

    # ------------------------------------------------------------------
    # Sauvegarde frame + label YOLO
    # ------------------------------------------------------------------

    def _save_sample(
        self,
        cam_id: int,
        frame: np.ndarray,
        detections: list[dict],
        strategy: str,
        motion_pixels: int = 0,
    ) -> str | None:
        """
        Sauvegarde une frame JPEG et son fichier label YOLO (.txt).

        Args:
            cam_id: Identifiant de la caméra.
            frame: Image BGR (numpy).
            detections: Détections remappées (format interne).
            strategy: "temporal" | "event".
            motion_pixels: Nombre de pixels blancs mouvement.

        Returns:
            Nom du fichier image sauvegardé, ou None si erreur.
        """
        h, w = frame.shape[:2]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # ms inclus
        filename = f"cam{cam_id}_{ts}_{strategy}"
        img_path = self.output_dir / "images" / "raw" / f"{filename}.jpg"
        lbl_path = self.output_dir / "labels" / "raw" / f"{filename}.txt"

        # Sauvegarde image JPEG (qualité 92)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            logger.error(f"Échec encodage JPEG pour {filename}")
            return None
        img_path.write_bytes(buf.tobytes())

        # Sauvegarde labels YOLO (vide = pas de détection = image négative)
        yolo_lines = []
        for d in detections:
            cx = ((d["x_min"] + d["x_max"]) / 2) / w
            cy = ((d["y_min"] + d["y_max"]) / 2) / h
            bw = (d["x_max"] - d["x_min"]) / w
            bh = (d["y_max"] - d["y_min"]) / h
            # Clamp pour rester dans [0, 1]
            cx = max(0.0, min(1.0, cx))
            cy = max(0.0, min(1.0, cy))
            bw = max(0.0, min(1.0, bw))
            bh = max(0.0, min(1.0, bh))
            yolo_lines.append(
                f"{d['dataset_class_id']} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"
            )
        lbl_path.write_text("\n".join(yolo_lines))

        # Log CSV
        classes_present = ",".join(
            sorted({d["label"] for d in detections}) if detections else ["neg"]
        )
        with open(self.log_path, "a", newline="") as f:
            csv.writer(f).writerow(
                [
                    datetime.now().isoformat(timespec="milliseconds"),
                    cam_id,
                    f"{filename}.jpg",
                    strategy,
                    len(detections),
                    classes_present,
                    motion_pixels,
                ]
            )

        logger.info(
            f"💾 [{strategy:8s}] cam{cam_id} → {filename}.jpg "
            f"| {len(detections)} det. | classes: {classes_present}"
        )
        self._increment_class_count(cam_id, detections)
        return filename

    # ------------------------------------------------------------------
    # Boucle principale
    # ------------------------------------------------------------------

    def run(self, cam_manager: CameraManager) -> None:
        """
        Lance la boucle de collecte indéfinie.

        Args:
            cam_manager: Instance CameraManager déjà initialisée.
        """
        n_cams = len(cam_manager.cam_ids)
        logger.info(f"🚀 Démarrage de la collecte sur {n_cams} caméra(s)…")
        logger.info("   Ctrl+C pour arrêter proprement.\n")

        # Initialisation d'un MotionDetector par caméra
        for i in range(n_cams):
            self.motion_detectors[i] = MotionDetector()

        interval_sec = self.interval_minutes * 60

        # Décalage initial : forcer un premier échantillon temporel immédiatement
        for i in range(n_cams):
            self.last_temporal_capture[i] = 0.0
            self.last_event_capture[i] = 0.0

        try:
            while True:
                now = time.time()

                if not self._is_working_hours():
                    next_check = 60  # Vérifier toutes les minutes hors horaires
                    logger.debug(
                        f"Hors plage horaire ({self.start_hour}h–{self.end_hour}h). "
                        f"Pause {next_check}s."
                    )
                    time.sleep(next_check)
                    continue

                for cam_idx in range(n_cams):
                    frame = cam_manager.get_frame_array(cam_idx)
                    if frame is None:
                        logger.debug(f"Frame vide pour cam{cam_idx}, ignorée.")
                        continue

                    # ---- Détection de mouvement (rapide, locale) ----
                    _, motion_bool, white_pixels, _ = (
                        self.motion_detectors[cam_idx].get_mog2_motion_info(
                            frame,
                            padding=40,
                            white_pixels_threshold=self.motion_threshold,
                        )
                    )

                    # =====================================================
                    # Stratégie 1 — Échantillonnage TEMPOREL
                    # Capture toutes les interval_minutes minutes quelle
                    # que soit l'activité pour couvrir la diversité temporelle.
                    # =====================================================
                    if now - self.last_temporal_capture.get(cam_idx, 0) >= interval_sec:
                        detections = self._run_inference(frame)
                        self._save_sample(cam_idx, frame, detections, "temporal", white_pixels)
                        self.last_temporal_capture[cam_idx] = now

                    # =====================================================
                    # Stratégie 2 — Échantillonnage ÉVÉNEMENTIEL
                    # Capture uniquement si mouvement ET classes rares détectées.
                    # Respecte un gap minimal pour éviter les doublons.
                    # =====================================================
                    elif (
                        motion_bool
                        and now - self.last_event_capture.get(cam_idx, 0) >= self.min_event_gap_seconds
                    ):
                        detections = self._run_inference(frame)
                        if not detections:
                            # Pas de détection utile → on sauvegarde quand même 1 fois
                            # sur 10 pour garder des images vides (négatifs difficiles)
                            if int(now) % 10 == 0:
                                self._save_sample(cam_idx, frame, [], "event_neg", white_pixels)
                            self.last_event_capture[cam_idx] = now
                            continue

                        # Filtre par quota horaire : on ne capture que si au moins
                        # une classe n'a pas encore atteint son quota
                        rare_classes = {0, 1}  # forklift et driver → plus rares
                        present_classes = {d["dataset_class_id"] for d in detections}
                        has_rare = bool(present_classes & rare_classes)
                        quota_ok = any(
                            not self._class_quota_reached(cam_idx, c)
                            for c in present_classes
                        )

                        if has_rare or quota_ok:
                            self._save_sample(cam_idx, frame, detections, "event", white_pixels)
                            self.last_event_capture[cam_idx] = now

                # Sleep court pour ne pas saturer le CPU
                time.sleep(0.5)

        except KeyboardInterrupt:
            logger.info("⏹  Collecte arrêtée par l'utilisateur.")
            self._print_summary()

    # ------------------------------------------------------------------
    # Résumé final
    # ------------------------------------------------------------------

    def _print_summary(self) -> None:
        """Affiche un résumé du nombre d'images collectées par classe."""
        if not self.log_path.exists():
            return
        counts: dict[str, int] = {}
        n_total = 0
        with open(self.log_path) as f:
            for row in csv.DictReader(f):
                n_total += 1
                for cls in row["classes_present"].split(","):
                    cls = cls.strip()
                    counts[cls] = counts.get(cls, 0) + 1

        logger.info("\n" + "=" * 55)
        logger.info(f"  Total frames collectées : {n_total}")
        for cls, cnt in sorted(counts.items()):
            logger.info(f"  {cls:12s} : {cnt:>5d} frames")
        logger.info("=" * 55)


# ---------------------------------------------------------------------------
# Utilitaire : split train/val/test
# ---------------------------------------------------------------------------

def split_dataset(
    dataset_dir: str = "dataset",
    train_ratio: float = 0.75,
    val_ratio: float = 0.15,
    seed: int = 42,
) -> None:
    """
    Divise les images dans dataset/images/raw/ en trois splits :
    train / val / test en respectant les ratios donnés.

    Les fichiers sont COPIÉS (pas déplacés) pour conserver raw/ intact.
    Le split est fait de façon aléatoire mais reproductible via seed.

    Args:
        dataset_dir: Répertoire racine du dataset.
        train_ratio: Proportion du jeu d'entraînement (default 0.75).
        val_ratio: Proportion de validation (default 0.15).
        seed: Graine aléatoire pour la reproductibilité.
    """
    import shutil
    import random

    random.seed(seed)
    root = Path(dataset_dir)
    raw_imgs = sorted((root / "images" / "raw").glob("*.jpg"))
    if not raw_imgs:
        logger.error("Aucune image dans dataset/images/raw/. Collectez d'abord des images.")
        return

    random.shuffle(raw_imgs)
    n = len(raw_imgs)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)

    splits = {
        "train": raw_imgs[:n_train],
        "val": raw_imgs[n_train: n_train + n_val],
        "test": raw_imgs[n_train + n_val:],
    }

    for split, imgs in splits.items():
        img_out = root / "images" / split
        lbl_out = root / "labels" / split
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)
        for img_path in imgs:
            lbl_path = root / "labels" / "raw" / (img_path.stem + ".txt")
            shutil.copy2(img_path, img_out / img_path.name)
            if lbl_path.exists():
                shutil.copy2(lbl_path, lbl_out / lbl_path.name)
            else:
                # Fichier label vide si absent (image sans détection)
                (lbl_out / (img_path.stem + ".txt")).write_text("")

    logger.info(
        f"✅ Split terminé : {len(splits['train'])} train | "
        f"{len(splits['val'])} val | {len(splits['test'])} test"
    )


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse les arguments en ligne de commande."""
    p = argparse.ArgumentParser(
        description="Collecte automatique d'images pour dataset YOLO (4iSafeCross)."
    )
    p.add_argument(
        "--interval", type=int, default=10, metavar="MIN",
        help="Intervalle en minutes entre deux captures temporelles (défaut: 10).",
    )
    p.add_argument(
        "--output", type=str, default="dataset", metavar="DIR",
        help="Répertoire de sortie du dataset (défaut: dataset/).",
    )
    p.add_argument(
        "--hours", type=int, nargs=2, default=[7, 19], metavar=("START", "END"),
        help="Plage horaire de collecte, ex: --hours 7 19 (défaut: 7h–19h).",
    )
    p.add_argument(
        "--confidence", type=float, default=0.65, metavar="CONF",
        help="Seuil de confiance IA pour retenir une détection (défaut: 0.65).",
    )
    p.add_argument(
        "--max-per-class", type=int, default=30, metavar="N",
        help="Nombre max de frames par classe et par heure (défaut: 30).",
    )
    p.add_argument(
        "--split", action="store_true",
        help="Si présent, effectue uniquement le split train/val/test sur les images existantes.",
    )
    p.add_argument(
        "--train-ratio", type=float, default=0.75,
        help="Proportion train pour le split (défaut: 0.75).",
    )
    p.add_argument(
        "--val-ratio", type=float, default=0.15,
        help="Proportion val pour le split (défaut: 0.15).",
    )
    return p.parse_args()


def main() -> None:
    """Point d'entrée principal."""
    # Changer le répertoire courant à la racine du projet pour que
    # les imports relatifs (config.ini, etc.) fonctionnent correctement.
    os.chdir(PROJECT_ROOT)

    args = parse_args()

    if args.split:
        split_dataset(
            dataset_dir=args.output,
            train_ratio=args.train_ratio,
            val_ratio=args.val_ratio,
        )
        return

    # Chargement de la configuration RTSP
    cfg = configparser.ConfigParser()
    cfg.read("config/config.ini", encoding="utf-8")
    import ast
    rtsp_hosts = ast.literal_eval(cfg.get("RTSP", "HOST", fallback='["127.0.0.1"]'))
    rtsp_port = cfg.getint("RTSP", "PORT", fallback=554)
    rtsp_login = cfg.get("RTSP", "LOGIN", fallback="admin")
    rtsp_pwd = cfg.get("RTSP", "PASSWORD", fallback="")
    rtsp_stream = cfg.get("RTSP", "STREAM", fallback="stream1")

    cam_ids = [
        f"rtsp://{rtsp_login}:{rtsp_pwd}@{host}:{rtsp_port}/{rtsp_stream}"
        for host in rtsp_hosts
    ]
    logger.info(f"Connexion à {len(cam_ids)} caméra(s) RTSP…")

    manager = CameraManager(cam_ids, frame_width=1920, frame_height=1080)

    collector = DatasetCollector(
        output_dir=args.output,
        interval_minutes=args.interval,
        start_hour=args.hours[0],
        end_hour=args.hours[1],
        confidence_threshold=args.confidence,
        max_per_class_per_hour=args.max_per_class,
    )

    # Laisser GStreamer s'initialiser
    logger.info("Attente 3s d'initialisation GStreamer…")
    time.sleep(3)

    collector.run(manager)


if __name__ == "__main__":
    main()
