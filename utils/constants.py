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
        relays_str = config[section].get("relays", "").strip()
        zone["relays"] = [int(r.strip()) for r in relays_str.split(',') if r.strip().isdigit()]
        skip_str = config[section].get("skip_keypoint_filter", "false").strip().lower()
        zone["skip_keypoint_filter"] = skip_str in ("true", "1", "yes")
        debounce_frames_str = config[section].get("debounce_frames", "").strip()
        zone["debounce_frames"] = int(debounce_frames_str) if debounce_frames_str.isdigit() else None
        debounce_reset_str = config[section].get("debounce_reset_seconds", "").strip()
        try:
            zone["debounce_reset_seconds"] = float(debounce_reset_str) if debounce_reset_str else None
        except ValueError:
            zone["debounce_reset_seconds"] = None
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


def load_masks_by_camera_from_ini(ini_path):
    """Charge les masques polygonaux depuis un fichier INI.

    Les sections sont au format 'mask{i}_cam{j}'. Seule la clé 'polygon' est lue.
    Si le fichier n'existe pas, retourne un dictionnaire vide.

    Args:
        ini_path: Chemin vers le fichier masks.ini.

    Returns:
        Dict {cam_id (int): [{name, polygon (list of tuples)}]}.
    """
    masks_by_camera = {}
    if not os.path.exists(ini_path):
        return masks_by_camera
    config_parser = configparser.ConfigParser()
    config_parser.read(ini_path, encoding='utf-8')
    for section in config_parser.sections():
        if 'polygon' not in config_parser[section]:
            continue
        poly_str = config_parser[section]['polygon'].replace(' ', '')
        pts = re.findall(r'\((\d+),(\d+)\)', poly_str)
        polygon = [(int(x), int(y)) for x, y in pts]
        if len(polygon) < 3:
            continue
        mask = {'name': section, 'polygon': polygon}
        if '_cam' in section:
            try:
                cam_id = int(section.split('_cam')[-1])
                masks_by_camera.setdefault(cam_id, []).append(mask)
            except Exception:
                pass
    return masks_by_camera


MASKS_BY_CAMERA = load_masks_by_camera_from_ini('config/masks.ini')


def load_relay_positions_from_ini(ini_path):
    """Charge les positions des icônes de projecteurs depuis un fichier INI.

    Format des sections : relay{relay_id}_cam{cam_id}, clés 'x' et 'y'
    (coordonnées réelles en pixels).

    Returns:
        Dict {cam_id (int): {relay_id (int): (x, y)}}.
    """
    positions = {}
    if not os.path.exists(ini_path):
        return positions
    config_parser = configparser.ConfigParser()
    config_parser.read(ini_path, encoding='utf-8')
    for section in config_parser.sections():
        if 'x' not in config_parser[section] or 'y' not in config_parser[section]:
            continue
        if '_cam' not in section:
            continue
        try:
            cam_id = int(section.split('_cam')[-1])
            relay_part = section.split('_cam')[0]
            relay_id = int(relay_part.replace('relay', ''))
            x = int(config_parser[section]['x'])
            y = int(config_parser[section]['y'])
            positions.setdefault(cam_id, {})[relay_id] = (x, y)
        except (ValueError, AttributeError):
            pass
    return positions


RELAY_POSITIONS_BY_CAMERA = load_relay_positions_from_ini('config/relay_positions.ini')


# Chargement classique de config.ini (chemin relatif)
config = configparser.ConfigParser()
config.read('config/config.ini', encoding='utf-8')
print("Config file loaded:", os.path.abspath('config/config.ini'))
print("Sections trouvées:", config.sections())

LOG_LEVEL = config.get('logging', 'level', fallback='INFO')

TOKEN = config.get('TELEGRAM', 'TOKEN')
CHAT_ID = config.get('TELEGRAM', 'CHAT_ID')

MOTIONTHRESHOLD = config.getint('APP', 'MOTIONTHRESHOLD')
FGBG_HISTORY = config.getint('APP', 'FGBG_HISTORY', fallback=500)
FGBG_VAR_THRESHOLD = config.getint('APP', 'FGBG_VAR_THRESHOLD', fallback=10)
FGBG_DETECT_SHADOWS = config.getboolean('APP', 'FGBG_DETECT_SHADOWS', fallback=True)
MOTION_ON_FRAMES = config.getint('APP', 'MOTION_ON_FRAMES', fallback=2)
MOTION_OFF_FRAMES = config.getint('APP', 'MOTION_OFF_FRAMES', fallback=5)
MOTION_GAUSSIAN_BLUR = config.getboolean('APP', 'MOTION_GAUSSIAN_BLUR', fallback=True)
MOTION_ASPECT_FILTER = config.getboolean('APP', 'MOTION_ASPECT_FILTER', fallback=False)
MOTION_MIN_SINGLE_CONTOUR = config.getint('APP', 'MOTION_MIN_SINGLE_CONTOUR', fallback=1500)
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
POSE_ENABLED = config.getboolean('APP', 'POSE_ENABLED', fallback=True)
EXTENDED_CLASSES = ast.literal_eval(config.get('APP', 'EXTENDED_CLASSES', fallback='[1, 3, 6, 7, 8]'))
TRANSFERT_CLASSES = ast.literal_eval(config.get('APP', 'TRANSFERT_CLASSES', fallback='[0, 1, 2, 3, 4, 5]'))
SIMPLE_CLASSES = ast.literal_eval(config.get('APP', 'SIMPLE_CLASSES', fallback='[1, 2]'))

# Collecte automatique du dataset
DATASET_COLLECTION = config.getboolean('APP', 'DATASET_COLLECTION', fallback=False)
DATASET_COLLECTION_INTERVAL = config.getint('APP', 'DATASET_COLLECTION_INTERVAL', fallback=10)
DATASET_COLLECTION_START_HOUR = config.getint('APP', 'DATASET_COLLECTION_START_HOUR', fallback=7)
DATASET_COLLECTION_END_HOUR = config.getint('APP', 'DATASET_COLLECTION_END_HOUR', fallback=19)
DATASET_COLLECTION_MAX_PER_CLASS = config.getint('APP', 'DATASET_COLLECTION_MAX_PER_CLASS_PER_HOUR', fallback=30)
DATASET_OUTPUT_DIR = config.get('APP', 'DATASET_OUTPUT_DIR', fallback='dataset')
DATASET_BG_INTERVAL = config.getint('APP', 'DATASET_BG_INTERVAL', fallback=30)
DATASET_BG_ENABLED = config.getboolean('APP', 'DATASET_BG_ENABLED', fallback=True)
DATASET_HARD_NEG_CONFIDENCE = config.getfloat('APP', 'DATASET_HARD_NEG_CONFIDENCE', fallback=0.35)
DATASET_HARD_NEG_ENABLED = config.getboolean('APP', 'DATASET_HARD_NEG_ENABLED', fallback=True)

# Nouvelle constante pour le temps d'attente avant test RTSP
WAIT_BEFORE_TEST_RTSP = config.getint('APP', 'WAIT_BEFORE_TEST_RTSP', fallback=10)

# Période de grâce fail-safe au démarrage avant extinction initiale des relais
STARTUP_GRACE_PERIOD = config.getint('APP', 'STARTUP_GRACE_PERIOD', fallback=15)

# Nombre de relais physiques (fallback si Yoctopuce non connecté)
NUM_RELAYS = config.getint('APP', 'NUM_RELAYS', fallback=5)

# Ajout des constantes pour la fonction et l'URL d'inférence
FONCTION_RFDETR = config.get('APP', 'FONCTION_RFDETR', fallback='/predict_frame_rf_detr/')
URL_RFDETR = config.get('APP', 'URL_RFDETR', fallback='http://127.0.0.1:8002/')

FONCTION_YOLO = config.get('APP', 'FONCTION_YOLO', fallback='/predict_frame/')
URL_YOLO = config.get('APP', 'URL_YOLO', fallback='http://127.0.0.1:8004/')


# Chargement des couleurs de stature depuis config.ini
STATURE_COLORS = {}
if 'STATURE_COLORS' in config:
    for key, value in config['STATURE_COLORS'].items():
        STATURE_COLORS[key] = ast.literal_eval(value)

OBJECT_COLORS = {}
if 'OBJECT_COLORS' in config:
    for key, value in config['OBJECT_COLORS'].items():
        OBJECT_COLORS[key] = ast.literal_eval(value)

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
