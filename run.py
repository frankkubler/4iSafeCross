from app import app
from waitress import serve
import logging

waitress_logger = logging.getLogger('waitress')
waitress_logger.handlers.clear()
waitress_logger.propagate = True  # hérite du root logger (stdout)
serve(app, host='0.0.0.0', port=5050)  # nosec B104 — binding intentionnel pour conteneur
