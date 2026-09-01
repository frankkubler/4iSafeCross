#!/bin/bash

# Lancement manuel de l'IHM en développement.
#
# Point d'entrée = run.py (identique au conteneur Docker et au service systemd) :
# la séquence de boot — licence, relais fail-safe, caméras, threads — est
# obligatoire et n'est PAS reproductible par `waitress-serve --call`.
#
# run.py bind waitress sur 127.0.0.1:5050 UNIQUEMENT. Le TLS et l'exposition
# sur eth2 sont assurés par Caddy en frontal (config/Caddyfile).
# Conformité : CYBER_AUDIT.md — CS-1143-01, CS-143-02.

APP_PATH="$HOME/github/4iSafeCross/"

# Changer de répertoire vers la racine du projet
cd "$APP_PATH" || exit 1

# Exécuter l'application dans l'environnement virtuel du projet
DISPLAY=:1 "$HOME/.local/bin/uv" run python run.py
