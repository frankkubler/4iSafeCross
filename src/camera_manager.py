import cv2
import threading
import logging
import platform
import time
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import os

class CameraManager:
    def __init__(self, cam_ids, buffer_size=5, frame_width=None, frame_height=None):
        self.logger = logging.getLogger(__name__).getChild(__class__.__name__)
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

        for cid in filtered_cam_ids:
            t = threading.Thread(target=self.update, args=(cid,), daemon=True)
            t.start()
            self.threads.append(t)

    def update(self, cid):
        Gst.init(None)
        reconnect_delay = 3  # secondes entre tentatives
        while self.running:
            # Boucle de tentative de connexion au flux RTSP
            pipeline = None
            while self.running:
                pipeline_str = (
                    f"rtspsrc location={cid} latency=200 ! "
                    "rtph264depay ! h264parse ! nvv4l2decoder ! "
                    "nvvidconv ! video/x-raw,format=BGRx,width=1920,height=1080 ! "
                    "videoconvert ! video/x-raw,format=BGR ! "
                    "appsink name=sink"
                )
                self.logger.info(f"Pipeline GStreamer: {pipeline_str}")
                try:
                    pipeline = Gst.parse_launch(pipeline_str)
                    appsink = pipeline.get_by_name('sink')
                    bus = pipeline.get_bus()
                    bus.add_signal_watch()
                    eos_or_error = threading.Event()

                    def on_message(bus, message):
                        t = message.type
                        if t == Gst.MessageType.ERROR:
                            err, debug = message.parse_error()
                            self.logger.error(f"GStreamer ERROR: {err}, debug: {debug}")
                            eos_or_error.set()
                        elif t == Gst.MessageType.WARNING:
                            err, debug = message.parse_warning()
                            self.logger.warning(f"GStreamer WARNING: {err}, debug: {debug}")
                        elif t == Gst.MessageType.EOS:
                            self.logger.warning(f"GStreamer EOS (fin de flux) pour {cid}")
                            eos_or_error.set()
                    bus.connect('message', on_message)
                    ret = pipeline.set_state(Gst.State.PLAYING)
                    self.logger.info(f"Mise en PLAYING, retour: {ret.value_nick}")
                    if ret != Gst.StateChangeReturn.FAILURE:
                        break  # Succès, on sort de la boucle de tentative
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
            # Pipeline initialisé avec succès, on traite les frames
            fail_count = 0
            self.cams_status[cid] = 'online'  # flux ok au lancement
            while self.running and not eos_or_error.is_set():
                sample = appsink.emit('pull-sample')
                if sample:
                    buf = sample.get_buffer()
                    caps = sample.get_caps()
                    width = caps.get_structure(0).get_value('width')
                    height = caps.get_structure(0).get_value('height')
                    import numpy as np
                    success, mapinfo = buf.map(Gst.MapFlags.READ)
                    if success:
                        frame = np.frombuffer(mapinfo.data, dtype=np.uint8)
                        try:
                            frame = frame.reshape((height, width, 3))
                            fail_count = 0
                            self.cams_status[cid] = 'online'  # flux ok
                        except Exception as e:
                            self.logger.error(f"Erreur reshape frame: {e}, shape={frame.shape}, width={width}, height={height}")
                            frame = np.zeros((height, width, 3), dtype=np.uint8)
                        buf.unmap(mapinfo)
                        with self.locks[cid]:
                            self.frames[cid] = frame
                    else:
                        self.logger.warning(f"Impossible de mapper le buffer GStreamer pour {cid}")
                else:
                    fail_count += 1
                    self.logger.warning(f"Aucune frame reçue via GStreamer pour {cid} (compteur: {fail_count})")
                    self.cams_status[cid] = 'offline'  # perte du flux
                    # Attente active de reconnexion réseau avant de relancer le pipeline
                    while self.running:
                        self.logger.info(f"Attente de reconnexion au flux RTSP {cid}...")
                        if self.test_rtsp_stream(cid):
                            self.logger.info(f"Reconnexion détectée pour {cid}, relance du pipeline.")
                            time.sleep(20)
                            break
                        time.sleep(2)
                    break  # On sort pour relancer le pipeline
            else:
                # Si on sort de la boucle sans erreur, c'est que le flux est ok
                self.cams_status[cid] = 'online'
            pipeline.set_state(Gst.State.NULL)
            if not self.running:
                break
            self.logger.warning(f"Redémarrage du pipeline pour {cid} dans {reconnect_delay}s...")
            time.sleep(reconnect_delay)
        # Sortie définitive
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
        # Extraire l'adresse IP ou le host du flux RTSP
        match = re.match(r"rtsp://(?:[^@]+@)?([^/:]+)", cid)
        if not match:
            logger.warning(f"Impossible d'extraire le host du flux RTSP : {cid}")
            return False
        host = match.group(1)
        # Test ping (1 paquet, timeout 1s)
        try:
            ping_cmd = ["ping", "-n" if os.name == "nt" else "-c", "1", "-w", "1000", host]
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
