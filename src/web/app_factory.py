"""Factory Flask : crée l'application et enregistre les blueprints.

L'app étant définie dans src/web/, les dossiers templates/ et static/ de la
racine projet doivent être passés explicitement (Flask(__name__) chercherait
sinon dans src/web/). PROJECT_ROOT fonctionne aussi compilé en .so : __file__
pointe alors sur src/web/app_factory.*.so, même profondeur.
"""
from pathlib import Path

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_app(state):
    """Crée l'app Flask et enregistre tous les blueprints (sans url_prefix :
    les URLs publiques sont un contrat, voir AGENTS.md).

    Les blueprints accèdent à l'état via le singleton src.core.state.state ;
    `state` est reçu ici pour expliciter la dépendance au boot.
    """
    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / 'templates'),
        static_folder=str(PROJECT_ROOT / 'static'),
    )

    from src.web.routes_detection import detection_bp
    from src.web.routes_stream import stream_bp
    from src.web.routes_system import system_bp
    from src.web.routes_ui import ui_bp
    from src.web.routes_zones_api import zones_api_bp

    app.register_blueprint(ui_bp)
    app.register_blueprint(stream_bp)
    app.register_blueprint(detection_bp)
    app.register_blueprint(zones_api_bp)
    app.register_blueprint(system_bp)

    return app
