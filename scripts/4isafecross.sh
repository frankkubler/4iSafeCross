#!/bin/bash


# Chemin vers votre script Python
#SCRIPT="$HOME/github/person_detection_app/person_detection_dev.py"
APP_PATH="$HOME/github/4iSafeCross/"


# Liste des paramètres à transmettre à votre script Python
PARAMETRES="--threads=4 --host=0.0.0.0 --port=5050"

# Changer de répertoire vers le chemin du script
cd $APP_PATH

# Exécuter le script Python dans l'environnement virtuel
DISPLAY=:1 "$HOME/.local/bin/uv" run waitress-serve $PARAMETRES app:app

# DISPLAY=:1 "$HOME/.local/bin/uv" run gunicorn -w 4 -k gevent -b 0.0.0.0:5050 app:app


# uv run waitress-serve --threads=1 --host=0.0.0.0 --port=5050 app:app