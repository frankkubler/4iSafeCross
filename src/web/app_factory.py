"""Factory Flask : crée l'application et enregistre les blueprints.

L'app étant définie dans src/web/, les dossiers templates/ et static/ de la
racine projet doivent être passés explicitement (Flask(__name__) chercherait
sinon dans src/web/). PROJECT_ROOT fonctionne aussi compilé en .so : __file__
pointe alors sur src/web/app_factory.*.so, même profondeur.
"""
import hmac
import logging
import os
from pathlib import Path

from flask import Flask, Response, request

PROJECT_ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger(__name__)

# Authentification HTTP Basic, activée uniquement si les deux variables sont
# définies. Basic plutôt qu'un en-tête X-API-Key : le navigateur gère lui-même
# le défi et rejoue les identifiants sur tous les fetch() du tableau de bord,
# donc aucune modification du frontend n'est nécessaire.
AUTH_USER = os.environ.get('SAFECROSS_AUTH_USER', '')
AUTH_PASSWORD = os.environ.get('SAFECROSS_AUTH_PASSWORD', '')
AUTH_ENABLED = bool(AUTH_USER and AUTH_PASSWORD)


def _credentials_valid(auth) -> bool:
    """Compare les identifiants en temps constant (anti-timing)."""
    if auth is None or auth.type != 'basic':
        return False
    user_ok = hmac.compare_digest((auth.username or ''), AUTH_USER)
    pwd_ok = hmac.compare_digest((auth.password or ''), AUTH_PASSWORD)
    return user_ok and pwd_ok


def _register_auth(app):
    """Installe le contrôle d'accès sur toutes les routes de l'application."""
    if not AUTH_ENABLED:
        logger.warning(
            "⚠️  INTERFACE WEB NON AUTHENTIFIÉE : toute machine joignant le port "
            "5050 peut modifier les zones de sécurité, désactiver la détection "
            "ou couper les alertes. Définir SAFECROSS_AUTH_USER et "
            "SAFECROSS_AUTH_PASSWORD (voir .env.example) pour activer "
            "l'authentification HTTP Basic."
        )
        return

    logger.info("🔐 Authentification HTTP Basic active (utilisateur : %s)", AUTH_USER)

    @app.before_request
    def _require_auth():
        # Les ressources statiques (CSS/JS/images) ne portent aucune donnée
        # d'exploitation et sont servies sans défi, pour éviter des invites
        # d'authentification répétées dans le navigateur.
        # /health est exempté : le HEALTHCHECK Docker interroge la sonde sans
        # identifiants, et son corps ne divulgue aucune donnée d'exploitation.
        if request.endpoint in ('static', 'system.health'):
            return None
        if _credentials_valid(request.authorization):
            return None
        return Response(
            'Authentification requise.', 401,
            {'WWW-Authenticate': 'Basic realm="4iSafeCross"'},
        )


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

    _register_auth(app)

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
