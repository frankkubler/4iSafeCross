from waitress import serve
import logging
import sys


if __name__ == '__main__':
    # waitress : serveur WSGI multi-thread sans fork.
    # Compatible GStreamer/GLib : pas de fork() après Gst.init(),
    # donc pas d'assertions GLib ni de GPF dans les threads daemon.
    #
    # Le crash originel (GPF pool-python3 dans libc) était causé par
    # subprocess.run(ping) dans ThreadPoolExecutor — corrigé en ec070e0
    # (remplacement par socket.create_connection TCP).

    # waitress ajoute son propre StreamHandler(stderr) au démarrage.
    # On le neutralise pour que tous les logs passent par le root logger
    # (stdout) configuré dans app.py.
    from app import app  # noqa: E402 — importe Flask app + initialise CameraManager

    waitress_logger = logging.getLogger('waitress')
    waitress_logger.handlers.clear()
    waitress_logger.propagate = True

    serve(app, host='0.0.0.0', port=5050, threads=8)  # nosec B104
