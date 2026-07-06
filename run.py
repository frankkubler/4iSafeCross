import gunicorn.app.base
import logging


class StandaloneApplication(gunicorn.app.base.BaseApplication):
    """Embed gunicorn programmatically so we keep our logging setup.

    preload_app=True est CRITIQUE ici :
    - Sans preload : gunicorn importe app dans le worker forké
      → CameraManager + Gst.init() s'exécutent dans le child
      → GLib détecte le fork post-Gst.init() → GPF dans libc
    - Avec preload : app est importé dans le master avant fork()
      → le worker hérite du module via copy-on-write
      → GStreamer/GLib ne sont jamais ré-initialisés dans le child
    """

    def __init__(self, options=None):
        self.options = options or {}
        super().__init__()

    def load_config(self):
        for key, value in self.options.items():
            if key in self.cfg.settings and value is not None:
                self.cfg.set(key.lower(), value)

    def load(self):
        # Importé ici : avec preload_app=True, gunicorn appelle load()
        # dans le master avant fork() — pas dans le worker.
        from app import app
        return app


if __name__ == '__main__':
    options = {
        'bind': '0.0.0.0:5050',
        'workers': 1,
        'threads': 4,
        'worker_class': 'gthread',
        'timeout': 120,
        'preload_app': True,   # import app dans le master, pas dans le worker forké
        'accesslog': '-',
        'errorlog': '-',
        'loglevel': 'info',
        'forwarded_allow_ips': '*',
    }
    logging.getLogger('gunicorn.error').propagate = True
    logging.getLogger('gunicorn.access').propagate = True

    StandaloneApplication(options).run()
