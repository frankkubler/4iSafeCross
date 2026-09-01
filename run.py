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

    # IHM servie en clair sur la boucle locale UNIQUEMENT.
    # Le chiffrement TLS et l'exposition sur le réseau de maintenance (eth2,
    # 192.168.3.0/24) sont assurés par le reverse-proxy Caddy en frontal :
    #   - config/Caddyfile               (vhosts + `tls internal` + en-têtes)
    #   - scripts/caddy-4isafecross.service  (unité systemd, hors conteneur)
    #   - scripts/install_vnc_jetson.sh  (ouvre 443/tcp au seul sous-réseau maintenance)
    # Accès local depuis le bureau RustDesk/VNC : https://localhost (via Caddy).
    # Conformité : CYBER_AUDIT.md — CS-1143-01 (protocoles chiffrés),
    # CS-143-02 (seuls les flux sécurisés nécessaires ouverts).
    serve(app, listen='127.0.0.1:5050', threads=8)
