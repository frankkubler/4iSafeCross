# constants.py
# Fichier pour stocker les constantes globales de l'application


#TOKEN = "7161709928:AAEBcG3agiQU-G0Ar12sIu-yDQrwBVP6S3Q"  # dev bot
#CHAT_ID = "-4161590134"  # dev_4itec_supervision
import configparser
import ast
import os
import re

def load_zones_by_camera_from_ini(ini_path):
    config = configparser.ConfigParser()
    config.read(ini_path, encoding='utf-8')
    print("Zones config file loaded:", os.path.abspath(ini_path))
    print("Sections trouvées dans zones.ini:", config.sections())
    zones_by_camera = {}
    for section in config.sections():
        zone = {"name": section}
        if "rect" in config[section]:
            zone["rect"] = tuple(map(int, config[section]["rect"].split(',')))
        if "polygon" in config[section]:
            poly_str = config[section]["polygon"].replace(' ', '')
            pts = re.findall(r'\((\d+),(\d+)\)', poly_str)
            zone["polygon"] = [ (int(x), int(y)) for x, y in pts ]
        if "color" in config[section]:
            zone["color"] = tuple(map(int, config[section]["color"].split(',')))
        if "_cam" in section:
            try:
                cam_id = int(section.split("_cam")[-1])
                zones_by_camera.setdefault(cam_id, []).append(zone)
            except Exception:
                pass
    return zones_by_camera


# Gestion robuste du chemin pour zones.ini (compatible script et Nuitka)
# import sys
# def get_config_path(filename):
#     if getattr(sys, 'frozen', False):
#         base_dir = os.path.dirname(sys.executable)
#     else:
#         base_dir = os.path.dirname(os.path.abspath(__file__))
#         print(f"Base directory for config: {base_dir}")
#         path = os.path.join(base_dir, '..', 'config', filename)
#         print(f"Config path: {path}")
#     return path


# ZONES_INI_PATH = get_config_path('zones.ini')
ZONES_BY_CAMERA = load_zones_by_camera_from_ini('config/zones.ini')

# Chargement classique de config.ini (chemin relatif)
config = configparser.ConfigParser()
config.read('config/config.ini', encoding='utf-8')
print("Config file loaded:", os.path.abspath('config/config.ini'))
print("Sections trouvées:", config.sections())

LOG_LEVEL = config.get('logging', 'level', fallback='INFO')

TOKEN = config.get('TELEGRAM', 'TOKEN')
CHAT_ID = config.get('TELEGRAM', 'CHAT_ID')

MOTIONTRESHOLD = config.getint('APP', 'MOTIONTRESHOLD')
APP_NAME = config.get('APP', 'APP_NAME')
APP_VERSION = config.get('APP', 'APP_VERSION')
INF_THRESHOLD = config.getfloat('APP', 'INF_THRESHOLD')
RTSP_LOGIN = config.get('RTSP', 'LOGIN')
RTSP_PASSWORD = config.get('RTSP', 'PASSWORD')
RTSP_HOST = ast.literal_eval(config.get('RTSP', 'HOST'))
RTSP_PORT = config.getint('RTSP', 'PORT')
RTSP_STREAM = config.get('RTSP', 'STREAM')

DB_PATH = config.get('APP', 'DB_PATH')
DETECTION = config.get('APP', 'DETECTION', fallback='simple')

# Nouvelle constante pour le temps d'attente avant test RTSP
WAIT_BEFORE_TEST_RTSP = config.getint('APP', 'WAIT_BEFORE_TEST_RTSP', fallback=20)

# Ajout des constantes pour la fonction et l'URL d'inférence
FONCTION = config.get('APP', 'FONCTION', fallback='/predict_frame_rf_detr/')
URL = config.get('APP', 'URL', fallback='http://127.0.0.1:8002')

# # Définition des zones de détection par caméra (exemple pour 2 caméras)
# ZONES_BY_CAMERA = {
#     0: [
#         # {"name": "zone3_cam0", "rect": (0, 0, 1920, 180), "color": (255, 255, 0)},
#         {"name": "zone3_cam0", "polygon": 
#             [(1105, 40), (1105, 110), (1238, 290),(1270, 330), (1385, 331), (1697, 732), (1757, 830), (1920, 1080), (0, 1080),
#              (0, 388), (443, 388), (443, 225), (743, 225), (743, 40)],
#             "color": (255, 255, 0)},
#         {"name": "zone2_cam0", "polygon": [(1101, 111), (1479, 108),
#                                         (1484, 314), (1583, 314),
#                                         (1920, 661), (1920, 1080)],
#                                         "color": (0, 255, 255)},  # Cyan
#         # {"name": "zone2_cam0", "rect": (0, 180, 1920, 740), "color": (0, 255, 255)},   # Jaune
#         # {"name": "zone1_cam0", "rect": (0, 380, 1920, 1080), "color": (255, 0, 255)},  # Magenta
#         {"name": "zone1_cam0", "polygon": [(0, 225), (1200, 225), (1270, 330), (1385, 331), (1697, 732), (1757, 830), (1920, 1080), (0, 1080)], "color": (255, 0, 255)},  # Magenta
#     ],
#     1: [
#         {"name": "zone3_cam1", "rect": (0, 0, 800, 600), "color": (255, 255, 0)},      # Cyan
#         {"name": "zone2_cam1", "rect": (801, 0, 1600, 600), "color": (0, 255, 255)},   # Jaune
#         {"name": "zone1_cam1", "rect": (0, 601, 1600, 1200), "color": (255, 0, 255)},  # Magenta
#     ],
# }

# Schéma explicatif pour la définition des zones par caméra :
#
#  Caméra 0 (1920x1080)
#  +-------------------------------+
#  | zone3_cam0                    |
#  | (0,0,1920,180)                |
#  +-------------------------------+
#  |         zone2_cam0            |
#  |       (0,180,1920,740)        |
#  +-------------------------------+
#  |               zone1_cam0      |
#  |           (0,380,1920,1080)   |
#  +-------------------------------+
#
#
#  Les coordonnées sont au format (x1, y1, x2, y2) :
#    - (x1, y1) = coin supérieur gauche
#    - (x2, y2) = coin inférieur droit
#  Adapter les valeurs selon la résolution de chaque caméra et la zone à surveiller.
#
#  Pour ajouter une nouvelle caméra, suivre la même logique :
#    ZONES_BY_CAMERA[<id_cam>] = [ ... ]
#
#  Astuce : Utilisez un outil de visualisation d'image pour tester les coordonnées.
#
