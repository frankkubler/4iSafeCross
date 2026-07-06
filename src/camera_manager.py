import cv2
import threading
import logging
import platform
import time
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import os
import numpy as np

# ---------------------------------------------------------------------------
# Backends GStreamer H.264 supportés :
#   jetson      — nvv4l2decoder + nvvidconv (NVIDIA Jetson L4T / JetPack ≥ 4.x)
#   vaapi_new   — vah264dec + videoscale    (Intel iGPU, GStreamer ≥ 1.20,
#                                            paquet gstreamer1.0-plugins-bad ≥ 1.20
#                                            + intel-media-va-driver-non-free)
#                 ATTENTION : vah264dec crashe avec SIGABRT dans le driver
#                 iHD >= 23.x quand le contexte VA-API est créé depuis un
#                 thread secondaire. Utiliser GSTREAMER_BACKEND=software
#                 comme workaround en attendant un fix driver.
#   vaapi_legacy— vaapidecode + vaapipostproc (Intel iGPU, gstreamer1.0-vaapi
#                                            + i965-va-driver ou intel-media-va-driver)
#   software    — avdec_h264 (décodage CPU pur, fallback universel)
#
# Override manuel : variable d'environnement GSTREAMER_BACKEND
#   Valeurs acceptées : jetson | vaapi_new | vaapi_legacy | software
#   Exemple docker-compose : - GSTREAMER_BACKEND=software
# ---------------------------------------------------------------------------


class CameraManager:
    def __init__(self, cam_ids, buffer_size=5, frame_width=None, frame_height=None):
        """Initialise le gestionnaire de caméras RTSP.

        Args:
            cam_ids: Liste d'identifiants caméra (int pour V4L2, str pour RTSP).
            buffer_size: Taille du buffer (non utilisé directement par appsink).
            frame_width: Largeur cible des frames (None = résolution native caméra).
            frame_height: Hauteur cible des frames (None = résolution native caméra).
        """
        self.logger = logging.getLogger(__name__).getChild(__class__.__name__)
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.cams = {}
        filtered_cam_ids = []
        for cid in cam_ids:
            system = platform.system()
            if system == 'Linux' and isinstance(cid, int):
                dev_path = f"/dev/video{cid}"
                if not os.path.exists(dev_path):
                    self.logger.error(f"Périphérique {dev_path} introuvable. Caméra ignorée.")
                    continue
            filtered_cam_ids.append(cid)
        self.frames = {cid: None for cid in filtered_cam_ids}
        self.locks = {cid: threading.Lock() for cid in filtered_cam_ids}
        self.running = True
        self.threads = []
        self.cams_status = {cid: 'unknown' for cid in filtered_cam_ids}  # online/offline/unknown

        # Initialisation GStreamer une seule fois (pas dans chaque thread)
        Gst.init(None)

        # Détection automatique du backend GPU disponible
        # Peut être surchargé par la variable d'environnement GSTREAMER_BACKEND
        env_backend = os.environ.get('GSTREAMER_BACKEND', '').strip().lower()
        valid_backends = {'jetson', 'vaapi_new', 'vaapi_legacy', 'software'}
        if env_backend in valid_backends:
            self.backend = env_backend
            self.logger.info(f"Backend GStreamer forcé via env GSTREAMER_BACKEND : {self.backend}")
        else:
            if env_backend:
                self.logger.warning(
                    f"GSTREAMER_BACKEND='{env_backend}' invalide "
                    f"(valeurs acceptées : {sorted(valid_backends)}). Auto-détection."
                )
            self.backend = CameraManager.detect_backend()
            self.logger.info(f"Backend GStreamer sélectionné : {self.backend}")

        for cid in filtered_cam_ids:
            t = threading.Thread(target=self.update, args=(cid,), daemon=True)
            t.start()
            self.threads.append(t)

    @staticmethod
    def detect_backend() -> str:
        """Détecte automatiquement le backend de décodage H.264 disponible.

        Ordre de priorité :
            1. ``jetson``       : nvv4l2decoder (NVIDIA Jetson / L4T)
            2. ``vaapi_new``    : vah264dec     (Intel iGPU, GStreamer ≥ 1.20)
            3. ``vaapi_legacy`` : vaapidecode   (Intel iGPU, gstreamer1.0-vaapi)
            4. ``software``     : avdec_h264    (CPU pur, fallback)

        Returns:
            Chaîne identifiant le backend sélectionné.
        """
        probe_order = [
            ('nvv4l2decoder', 'jetson'),
            ('vah264dec',     'vaapi_new'),
            ('vaapidecode',   'vaapi_legacy'),
            ('avdec_h264',    'software'),
        ]
        logger = logging.getLogger(__name__).getChild('detect_backend')
        for element_name, backend_id in probe_order:
            if Gst.ElementFactory.find(element_name) is not None:
                logger.info(f"Élément GStreamer '{element_name}' trouvé → backend '{backend_id}'")
                return backend_id
        logger.warning("Aucun décodeur H.264 GStreamer trouvé (jetson/vaapi/software). Fallback 'software'.")
        return 'software'

    def _build_pipeline_str(self, cid: str) -> str:
        """Construit la chaîne de pipeline GStreamer adaptée au backend détecté.

        Args:
            cid: URL RTSP de la caméra.

        Returns:
            Chaîne décrivant le pipeline GStreamer complète.
        """
        if self.frame_width and self.frame_height:
            resize_caps = f"video/x-raw,format=BGRx,width={self.frame_width},height={self.frame_height}"
        else:
            resize_caps = "video/x-raw,format=BGRx"

        source = f"rtspsrc location={cid} latency=200 ! rtph264depay ! h264parse"
        tail = "videoconvert ! video/x-raw,format=BGR ! appsink name=sink"

        if self.backend == 'jetson':
            # Décodage hardware Tegra + conversion GPU
            decode = f"nvv4l2decoder ! nvvidconv ! {resize_caps}"
        elif self.backend == 'vaapi_new':
            # Intel iGPU — GStreamer ≥ 1.20
            # Historique :
            #   v1 : vah264dec ! vapostproc ! NV12 caps → SIGSEGV DMA-BUF Docker
            #   v2 : vah264dec ! video/x-raw,format=NV12,... → SIGABRT caps VA-API
            #   v3 : vah264dec ! videoscale ! video/x-raw,w,h → SIGABRT iHD thread
            # Root cause : iHD driver >= 23.x non thread-safe hors thread principal.
            # Utiliser GSTREAMER_BACKEND=software comme workaround.
            if self.frame_width and self.frame_height:
                decode = (
                    f"vah264dec ! videoscale ! "
                    f"video/x-raw,width={self.frame_width},height={self.frame_height}"
                )
            else:
                decode = "vah264dec"
        elif self.backend == 'vaapi_legacy':
            # Intel iGPU — gstreamer1.0-vaapi (legacy)
            decode = f"vaapidecode ! vaapipostproc ! {resize_caps}"
        else:
            # Fallback software CPU (avdec_h264)
            decode = f"avdec_h264 ! videoconvert ! {resize_caps}"

        return f"{source} ! {decode} ! {tail}"

    def _poll_bus_messages(self, bus, cid, eos_or_error, bus_state):
        """Lit les messages du bus GStreamer sans boucle GLib externe.

        Cette approche évite ``bus.add_signal_watch()`` qui nécessite un
        ``GLib.MainLoop`` actif et peut produire des assertions critiques
        selon la plateforme/pilotes.
        """
        message_types = (
            Gst.MessageType.ERROR
            | Gst.MessageType.WARNING
            | Gst.MessageType.EOS
        )
        while True:
            message = bus.timed_pop_filtered(0, message_types)
            if message is None:
                break

            message_type = message.type
            if message_type == Gst.MessageType.ERROR:
                err, debug = message.parse_error()
                self.logger.error(f"GStreamer ERROR: {err}, debug: {debug}")
                err_text = str(err)
                debug_text = debug or ""
                if "Unauthorized" in err_text or "401" in debug_text:
                    bus_state['auth_error'] = True
                eos_or_error.set()
            elif message_type == Gst.MessageType.WARNING:
                err, debug = message.parse_warning()
                self.logger.warning(f"GStreamer WARNING: {err}, debug: {debug}")
            elif message_type == Gst.MessageType.EOS:
                self.logger.warning(f"GStreamer EOS (fin de flux) pour {cid}")
                eos_or_error.set()

    def update(self, cid):
        reconnect_delay = 3  # secondes entre tentatives
        while self.running:
            pipeline = None
            bus = None
            while self.running:
                pipeline_str = self._build_pipeline_str(cid)
                self.logger.info(f"Pipeline GStreamer [{self.backend}]: {pipeline_str}")
                try:
                    pipeline = Gst.parse_launch(pipeline_str)
                    appsink = pipeline.get_by_name('sink')
                    bus = pipeline.get_bus()
                    eos_or_error = threading.Event()
                    bus_state = {'auth_error': False}
                    ret = pipeline.set_state(Gst.State.PLAYING)
                    self.logger.info(f"Mise en PLAYING, retour: {ret.value_nick}")
                    if ret != Gst.StateChangeReturn.FAILURE:
                        break
                    else:
                        self.logger.error(f"Échec de mise en PLAYING pour {cid}, nouvelle tentative dans {reconnect_delay}s...")
                        pipeline.set_state(Gst.State.NULL)
                        time.sleep(reconnect_delay)
                except Exception as e:
                    self.logger.error(f"Exception lors de l'init du pipeline GStreamer pour {cid}: {e}")
                    if pipeline:
                        pipeline.set_state(Gst.State.NULL)
                    self.cams_status[cid] = 'offline'
                    time.sleep(reconnect_delay)

            if not self.running or pipeline is None:
                break

            fail_count = 0
            self.cams_status[cid] = 'online'
            while self.running and not eos_or_error.is_set():
                self._poll_bus_messages(bus, cid, eos_or_error, bus_state)
                if eos_or_error.is_set():
                    break

                sample = appsink.emit('try-pull-sample', 1_000_000_000)
                if sample:
                    buf = sample.get_buffer()
                    caps = sample.get_caps()
                    width = caps.get_structure(0).get_value('width')
                    height = caps.get_structure(0).get_value('height')
                    success, mapinfo = buf.map(Gst.MapFlags.READ)
                    if success:
                        frame = np.frombuffer(mapinfo.data, dtype=np.uint8)
                        try:
                            frame = frame.reshape((height, width, 3))
                            fail_count = 0
                            self.cams_status[cid] = 'online'
                        except Exception as e:
                            self.logger.error(f"Erreur reshape frame: {e}, shape={frame.shape}, width={width}, height={height}")
                            frame = np.zeros((height, width, 3), dtype=np.uint8)
                        buf.unmap(mapinfo)
                        with self.locks[cid]:
                            self.frames[cid] = frame
                    else:
                        self.logger.warning(f"Impossible de mapper le buffer GStreamer pour {cid}")
                else:
                    self._poll_bus_messages(bus, cid, eos_or_error, bus_state)
                    if eos_or_error.is_set():
                        break

                    fail_count += 1
                    self.logger.warning(f"Aucune frame reçue via GStreamer pour {cid} (compteur: {fail_count})")
                    self.cams_status[cid] = 'offline'
                    while self.running:
                        self.logger.info(f"Attente de reconnexion au flux RTSP {cid}...")
                        if self.test_rtsp_stream(cid):
                            self.logger.info(f"Reconnexion détectée pour {cid}, relance du pipeline.")
                            time.sleep(20)
                            break
                        time.sleep(2)
                    break
            else:
                self.cams_status[cid] = 'online'
            if bus is not None:
                self._poll_bus_messages(bus, cid, eos_or_error, bus_state)
            pipeline.set_state(Gst.State.NULL)
            if not self.running:
                break
            if bus_state.get('auth_error'):
                self.cams_status[cid] = 'offline'
                auth_reconnect_delay = 15
                self.logger.error(
                    f"Échec d'authentification RTSP (401) pour {cid}. "
                    f"Vérifiez login/mot de passe. Nouvelle tentative dans {auth_reconnect_delay}s..."
                )
                time.sleep(auth_reconnect_delay)
            else:
                self.logger.warning(f"Redémarrage du pipeline pour {cid} dans {reconnect_delay}s...")
                time.sleep(reconnect_delay)
        self.logger.info(f"Thread update caméra {cid} terminé.")
        self.cams_status[cid] = 'offline'

    def get_status(self, cid):
        return self.cams_status.get(cid, 'unknown')

    def get_frame(self, cid):
        with self.locks[cid]:
            frame = self.frames[cid]
            if frame is not None:
                ret, jpeg = cv2.imencode('.jpg', frame)
                return jpeg.tobytes()
            return None

    def get_frame_array(self, cid):
        with self.locks[cid]:
            return self.frames[cid]

    def release(self):
        self.running = False

    @staticmethod
    def test_rtsp_stream(cid, timeout=5):
        """Teste la disponibilité d'un flux RTSP avec un ping réseau uniquement. Retourne True si le host répond au ping, False sinon."""
        import logging
        import re
        import subprocess
        logger = logging.getLogger(__name__).getChild('test_rtsp_stream')
        logger.info(f"Test du flux RTSP {cid} avec ping réseau...")
        match = re.match(r"rtsp://(?:[^@]+@)?([^/:]+)", cid)
        if not match:
            logger.warning(f"Impossible d'extraire le host du flux RTSP : {cid}")
            return False
        host = match.group(1)
        try:
            if os.name == 'nt':
                ping_cmd = ["ping", "-n", "1", "-w", "1000", host]
            else:
                ping_cmd = ["ping", "-c", "1", "-W", "1", host]
            ping_result = subprocess.run(ping_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
            if ping_result.returncode != 0:
                logger.warning(f"Ping échoué pour {host} (flux {cid})")
                return False
            logger.info(f"Ping OK pour {host} (flux {cid})")
            return True
        except Exception as e:
            logger.error(f"Erreur lors du ping de {host} : {e}")
            return False

    @staticmethod
    def test_rtsp_streams_parallel(cids, timeout=5, max_workers=8):
        """Teste en parallèle la disponibilité de plusieurs flux RTSP. Retourne un dict {cid: True/False}."""
        import concurrent.futures
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_cid = {executor.submit(CameraManager.test_rtsp_stream, cid, timeout): cid for cid in cids}
            for future in concurrent.futures.as_completed(future_to_cid):
                cid = future_to_cid[future]
                try:
                    results[cid] = future.result()
                except Exception as e:
                    results[cid] = False
        return results
