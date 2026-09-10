"""Sonde RTSP hors application — même URL, même pipeline GStreamer que 4iSafeCross.

Lance le pipeline de production pour chaque hôte de [RTSP] HOST, laisse
FIRST_FRAME_TIMEOUT secondes à la première image, remonte les messages du bus
(ERROR / WARNING / EOS) et mesure ensuite le débit. Sert à distinguer :
  - « le port 554 répond mais rien ne parle RTSP »  → BUS ERROR « Could not read from
    resource » vers +12 s, AUCUNE IMAGE ;
  - « la caméra est lente à livrer sa 1re image »   → PREMIÈRE IMAGE après N s, à comparer
    à RTSP_FIRST_FRAME_TIMEOUT (config.ini) ;
  - « identifiants / chemin de flux faux »          → BUS ERROR 401 / 404 immédiat.

Usage, depuis le poste de maintenance ou le boîtier (root), l'application pouvant
tourner en parallèle (NVDEC accepte plusieurs instances) :

    docker exec -i 4isafecross /app/.venv/bin/python - < scripts/rtsp_probe.py

Ou en le collant dans un heredoc `docker exec -i ... python - <<'PY' ... PY`.
Voir docs/deployment/install-prod-jetson-docker.md § 12.2.
"""
import sys, time
sys.path.insert(0, '/app')
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
from utils.constants import (RTSP_SCHEME, RTSP_LOGIN, RTSP_PASSWORD, RTSP_HOST, RTSP_PORT,
                             RTSP_STREAM, RTSP_FIRST_FRAME_TIMEOUT)

FIRST_FRAME_TIMEOUT = 20      # secondes accordées ici à la première image
MEASURE_WINDOW = 5            # puis mesure du débit

Gst.init(None)
for host in RTSP_HOST:
    url = f"{RTSP_SCHEME}://{RTSP_LOGIN}:{RTSP_PASSWORD}@{host}:{RTSP_PORT}/{RTSP_STREAM}"
    pipe_str = (f"rtspsrc location={url} latency=200 protocols=tcp ! rtph264depay ! h264parse "
                f"! nvv4l2decoder ! nvvidconv ! video/x-raw,format=BGRx,width=1920,height=1080 "
                f"! videoconvert ! video/x-raw,format=BGR ! appsink name=sink")
    print(f"\n=== {host} ===")
    pipeline = Gst.parse_launch(pipe_str)
    sink = pipeline.get_by_name('sink')
    bus = pipeline.get_bus()
    t0 = time.monotonic()
    ret = pipeline.set_state(Gst.State.PLAYING)
    print(f"set_state(PLAYING) -> {ret.value_nick}")

    first = None
    while time.monotonic() - t0 < FIRST_FRAME_TIMEOUT and first is None:
        msg = bus.timed_pop_filtered(0, Gst.MessageType.ERROR | Gst.MessageType.WARNING | Gst.MessageType.EOS)
        if msg is not None:
            if msg.type == Gst.MessageType.ERROR:
                err, dbg = msg.parse_error()
                print(f"  BUS ERROR  +{time.monotonic()-t0:5.2f}s : {err} | {dbg}")
                break
            if msg.type == Gst.MessageType.WARNING:
                err, dbg = msg.parse_warning()
                print(f"  BUS WARN   +{time.monotonic()-t0:5.2f}s : {err}")
            if msg.type == Gst.MessageType.EOS:
                print(f"  BUS EOS    +{time.monotonic()-t0:5.2f}s"); break
        sample = sink.emit('try-pull-sample', 500_000_000)   # 0,5 s
        if sample:
            first = time.monotonic() - t0
            s = sample.get_caps().get_structure(0)
            print(f"  PREMIÈRE IMAGE après {first:.2f}s  ({s.get_value('width')}x{s.get_value('height')})")

    if first is None:
        print(f"  AUCUNE IMAGE en {FIRST_FRAME_TIMEOUT}s")
    else:
        n, t1 = 0, time.monotonic()
        while time.monotonic() - t1 < MEASURE_WINDOW:
            if sink.emit('try-pull-sample', 500_000_000): n += 1
        print(f"  débit ensuite : {n/MEASURE_WINDOW:.1f} img/s sur {MEASURE_WINDOW}s")
        if first > RTSP_FIRST_FRAME_TIMEOUT:
            verdict = f"1re image en {first:.1f}s > RTSP_FIRST_FRAME_TIMEOUT={RTSP_FIRST_FRAME_TIMEOUT}s : augmenter ce paramètre"
        else:
            verdict = f"OK — 1re image en {first:.1f}s, sous RTSP_FIRST_FRAME_TIMEOUT={RTSP_FIRST_FRAME_TIMEOUT}s"
        print(f"  VERDICT : {verdict}")
    pipeline.set_state(Gst.State.NULL)
