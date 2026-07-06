import multiprocessing
import gunicorn.app.base
import logging

from app import app  # noqa: E402  — imports Flask app + initialises CameraManager


class StandaloneApplication(gunicorn.app.base.BaseApplication):
    """Embed gunicorn programmatically so we keep our logging setup."""

    def __init__(self, flask_app, options=None):
        self.options = options or {}
        self.application = flask_app
        super().__init__()

    def load_config(self):
        for key, value in self.options.items():
            if key in self.cfg.settings and value is not None:
                self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


if __name__ == '__main__':
    # 1 worker pre-fork : GLib/GStreamer state reste dans le process principal,
    # pas de duplication inter-worker. 4 threads pour les requêtes Flask.
    options = {
        'bind': '0.0.0.0:5050',
        'workers': 1,
        'threads': 4,
        'worker_class': 'gthread',
        'timeout': 120,
        'accesslog': '-',    # stdout
        'errorlog': '-',     # stderr
        'loglevel': 'info',
        'forwarded_allow_ips': '*',
    }
    logging.getLogger('gunicorn.error').propagate = True
    logging.getLogger('gunicorn.access').propagate = True

    StandaloneApplication(app, options).run()
