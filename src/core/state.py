"""Conteneur d'état partagé de l'application.

Singleton module-level : les callbacks de détection, le watchdog fail-safe et
les threads dataset s'exécutent hors contexte de requête Flask, un accès via
`current_app` n'est donc pas possible. Waitress est mono-processus sans fork
(voir run.py), le singleton est donc sûr.

Les attributs sont remplis par src/core/bootstrap.py au démarrage ; les routes
qui rechargent la config à chaud (zones, masques, positions relais) réaffectent
directement les attributs correspondants.
"""
import threading
import time


class AppState:

    def __init__(self):
        # Config runtime rechargeable (config/zones.ini, masks.ini, relay_positions.ini)
        self.zones_by_camera = {}
        self.masks_by_camera = {}
        self.relay_positions_by_camera = {}

        # Services
        self.manager = None          # CameraManager
        self.cam_ids = []            # URLs RTSP des caméras disponibles
        self.relays = None           # YoctoMultiRelay
        self.alert_manager = None    # AlerteManager
        self.telegram_bot = None     # BotThread ou None
        self.main_loop = None        # Boucle asyncio principale (MAIN_LOOP)

        # Threads d'inférence et de collecte dataset
        self.inference_threads = {}
        self.inference_stop_events = {}
        self.dataset_threads = {}

        # Données partagées entre threads d'inférence et affichage
        self.shared_detections = {}
        self.shared_detections_lock = threading.Lock()
        self.shared_motion_roi = {}
        self.shared_motion_roi_lock = threading.Lock()

        # Toggles par caméra (index caméra → bool/int)
        self.stream_enabled = {}
        self.detection_enabled = {}
        self.roi_display_enabled = {}
        self.mask_overlay_enabled = {}
        self.stream_display_width = {}
        self.telegram_alert_enabled = False

        # Heartbeat fail-safe (voir src/core/failsafe.py)
        self.heartbeat_lock = threading.Lock()
        self.last_heartbeat = time.time()
        self.application_healthy = True


state = AppState()
