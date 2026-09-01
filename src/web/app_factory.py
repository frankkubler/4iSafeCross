"""Factory Flask : crée l'application et enregistre les blueprints.

L'app étant définie dans src/web/, les dossiers templates/ et static/ de la
racine projet doivent être passés explicitement (Flask(__name__) chercherait
sinon dans src/web/). PROJECT_ROOT fonctionne aussi compilé en .so : __file__
pointe alors sur src/web/app_factory.*.so, même profondeur.

Contrôles transverses installés ici (ordre = ordre des before_request) :
  1. _register_auth     — HTTP Basic OBLIGATOIRE (CS-1144-01)
  2. _register_security  — anti-CSRF (contrôle d'Origin) + en-têtes de sécurité (CS-R4-01)
  3. _register_audit     — journal d'audit JSON des écritures et des rejets (CS-144-01 / CS-R2-03)
"""
import datetime
import hmac
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response, request

PROJECT_ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger(__name__)

# Méthodes HTTP considérées comme des écritures (consignes de sécurité).
_WRITE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})

# Endpoints exemptés d'authentification (ressources statiques + sonde Docker).
_AUTH_EXEMPT_ENDPOINTS = frozenset({'static', 'system.health'})

# ─── Authentification HTTP Basic — OBLIGATOIRE (CS-1144-01) ──────────────────
# L'écriture des consignes de sécurité (zones, seuils de mouvement, toggle
# détection, relais) doit être protégée par mot de passe ; l'application refuse
# de démarrer si les deux variables ne sont pas définies (require_auth_config()).
# Basic plutôt qu'un en-tête X-API-Key : le navigateur gère lui-même le défi et
# rejoue les identifiants sur tous les fetch() du tableau de bord, donc aucune
# modification du frontend n'est nécessaire.
AUTH_USER = os.environ.get('SAFECROSS_AUTH_USER', '')
AUTH_PASSWORD = os.environ.get('SAFECROSS_AUTH_PASSWORD', '')
AUTH_ENABLED = bool(AUTH_USER and AUTH_PASSWORD)

_AUTH_MISSING_MSG = (
    "SAFECROSS_AUTH_USER / SAFECROSS_AUTH_PASSWORD absents : l'IHM ne démarre "
    "pas sans authentification (CS-1144-01 — écriture des consignes de sécurité "
    "protégée par mot de passe). Renseigner .env depuis .env.example."
)

# Hôtes acceptés comme Origin des requêtes d'écriture (anti-CSRF). L'hôte de la
# requête est toujours accepté ; ces valeurs couvrent l'accès local (bureau
# RustDesk/VNC) et un tunnel SSH. SAFECROSS_ALLOWED_ORIGINS (hôtes séparés par
# des virgules) permet d'en ajouter sans toucher au code.
_DEFAULT_ALLOWED_ORIGIN_HOSTS = {'localhost', '127.0.0.1', '::1'}
_EXTRA_ALLOWED_ORIGIN_HOSTS = {
    h.strip().lower()
    for h in os.environ.get('SAFECROSS_ALLOWED_ORIGINS', '').split(',')
    if h.strip()
}

# Journal d'audit : lignes JSON, rotation applicative (5 Mo × 10).
_AUDIT_LOG_PATH = PROJECT_ROOT / 'logs' / 'audit.log'


def require_auth_config():
    """Refuse le démarrage si l'authentification de l'IHM n'est pas configurée.

    Appelé tôt dans la séquence de boot (src/core/bootstrap.py), avant tout
    effet de bord (thread asyncio, licence, relais fail-safe, caméras), pour
    échouer proprement sur une erreur de configuration.
    """
    if not AUTH_ENABLED:
        raise RuntimeError(_AUTH_MISSING_MSG)


def _credentials_valid(auth) -> bool:
    """Compare les identifiants en temps constant (anti-timing)."""
    if auth is None or auth.type != 'basic':
        return False
    user_ok = hmac.compare_digest((auth.username or ''), AUTH_USER)
    pwd_ok = hmac.compare_digest((auth.password or ''), AUTH_PASSWORD)
    return user_ok and pwd_ok


def _register_auth(app):
    """Installe le contrôle d'accès sur toutes les routes de l'application.

    Défense en profondeur : si create_app() est appelé sans passer par la
    séquence de boot (require_auth_config() non exécuté), on échoue fermé
    plutôt que de servir l'IHM sans authentification.
    """
    if not AUTH_ENABLED:
        raise RuntimeError(_AUTH_MISSING_MSG)

    logger.info("🔐 Authentification HTTP Basic active (utilisateur : %s)", AUTH_USER)

    @app.before_request
    def _require_auth():
        # Les ressources statiques (CSS/JS/images) ne portent aucune donnée
        # d'exploitation et sont servies sans défi, pour éviter des invites
        # d'authentification répétées dans le navigateur.
        # /health est exempté : le HEALTHCHECK Docker interroge la sonde sans
        # identifiants, et son corps ne divulgue aucune donnée d'exploitation.
        if request.endpoint in _AUTH_EXEMPT_ENDPOINTS:
            return None
        if _credentials_valid(request.authorization):
            return None
        return Response(
            'Authentification requise.', 401,
            {'WWW-Authenticate': 'Basic realm="4iSafeCross"'},
        )


def _origin_host_allowed(origin: str) -> bool:
    """True si l'Origin d'une requête d'écriture est acceptable (anti-CSRF).

    Un navigateur envoie toujours `Origin` sur un POST ; une page tierce ne peut
    pas le falsifier. `Origin: null` (iframe sandbox, data:) est refusé. Les
    clients non-navigateur (curl, scripts, sonde) n'envoient pas `Origin` et ne
    sont donc pas concernés (ils ne sont pas le vecteur CSRF).
    """
    if origin == 'null' or not origin:
        return False
    host = (urlsplit(origin).hostname or '').lower()
    if not host:
        return False
    allowed = {(request.host or '').split(':')[0].lower()}
    allowed |= _DEFAULT_ALLOWED_ORIGIN_HOSTS
    allowed |= _EXTRA_ALLOWED_ORIGIN_HOSTS
    return host in allowed


# En-têtes de sécurité HTTP (CS-R4-01). Appliqués aussi côté application, pas
# seulement par Caddy : l'IHM doit rester protégée si elle est atteinte
# directement sur 127.0.0.1:5050 (dev, diagnostic).
# CSP : `'unsafe-inline'` est requis tant que les templates portent des
# gestionnaires `onclick=` et des blocs <script>/<style> inline. Le durcissement
# en CSP à nonce est un chantier frontend distinct.
_SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Content-Security-Policy': (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    ),
}


def _register_security(app):
    """Anti-CSRF (contrôle d'Origin sur les écritures) + en-têtes de sécurité."""

    @app.before_request
    def _csrf_origin_guard():
        if request.method not in _WRITE_METHODS:
            return None
        origin = request.headers.get('Origin')
        if origin is None:
            return None  # client non-navigateur : hors périmètre CSRF
        if _origin_host_allowed(origin):
            return None
        return Response('Origine non autorisée (CSRF).', 403)

    @app.after_request
    def _set_security_headers(response):
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        # Ne pas divulguer la pile serveur / sa version (CS-R8-01). Caddy pose
        # aussi `-Server` ; on couvre l'accès direct à waitress.
        response.headers['Server'] = '4iSafeCross'
        return response


def _build_audit_logger() -> logging.Logger:
    audit = logging.getLogger('safecross.audit')
    audit.setLevel(logging.INFO)
    audit.propagate = False  # trail dédié, pas de préfixe du root logger
    if not audit.handlers:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            _AUDIT_LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=10,
            encoding='utf-8',
        )
        handler.setFormatter(logging.Formatter('%(message)s'))
        audit.addHandler(handler)
    return audit


def _register_audit(app):
    """Journal d'audit JSON : écritures + rejets (401/403).

    Une ligne JSON par événement dans logs/audit.log (rotation 5 Mo × 10) :
    horodatage, IP source (X-Forwarded-For posé par Caddy), identité présentée,
    méthode, chemin, code de statut, type d'événement. Exigences CS-144-01
    (flux rejetés journalisés) et CS-R2-03 (traçabilité des accès).
    """
    audit = _build_audit_logger()

    @app.after_request
    def _audit_log(response):
        status = response.status_code
        is_write = request.method in _WRITE_METHODS
        is_reject = status in (401, 403)
        if not (is_write or is_reject):
            return response

        xff = request.headers.get('X-Forwarded-For', '')
        ip = xff.split(',')[0].strip() or (request.remote_addr or '-')
        auth = request.authorization
        presented_user = (
            (auth.username or '-') if (auth and auth.type == 'basic') else '-'
        )
        if status == 401:
            event = 'auth_reject'
        elif status == 403:
            event = 'forbidden'
        else:
            event = 'write'

        entry = {
            'ts': datetime.datetime.now().astimezone().isoformat(
                timespec='milliseconds'),
            'ip': ip,
            'user': presented_user,
            'method': request.method,
            'path': request.path,
            'status': status,
            'event': event,
        }
        origin = request.headers.get('Origin')
        if origin:
            entry['origin'] = origin
        audit.info(json.dumps(entry, ensure_ascii=False))
        return response


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
    _register_security(app)
    _register_audit(app)

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
