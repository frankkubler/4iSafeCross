from waitress import serve
import faulthandler
import logging


if __name__ == '__main__':
    # Dump de pile sur crash natif (SIGSEGV/SIGABRT — GStreamer, OpenCV…) :
    # sans lui, un GPF tue le processus sans aucune trace exploitable.
    faulthandler.enable()

    # waitress : serveur WSGI multi-thread sans fork.
    # Compatible GStreamer/GLib : pas de fork() après Gst.init(),
    # donc pas d'assertions GLib ni de GPF dans les threads daemon.
    #
    # Le crash originel (GPF pool-python3 dans libc) était causé par
    # subprocess.run(ping) dans ThreadPoolExecutor — corrigé en ec070e0
    # (remplacement par socket.create_connection TCP).

    # create_application() exécute toute la séquence de boot : licence,
    # relais fail-safe, caméras, threads — voir src/core/bootstrap.py.
    from src.core.bootstrap import create_application

    app, state = create_application()

    # waitress ajoute son propre StreamHandler(stderr) au démarrage.
    # On le neutralise pour que tous les logs passent par le root logger
    # (stdout) configuré dans src/core/bootstrap.py.
    waitress_logger = logging.getLogger('waitress')
    waitress_logger.handlers.clear()
    waitress_logger.propagate = True

    serve(app, host='0.0.0.0', port=5050, threads=8)  # nosec B104
