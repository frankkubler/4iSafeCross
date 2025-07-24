# constants.py
# Fichier pour stocker les constantes globales de l'application


#TOKEN = "7161709928:AAEBcG3agiQU-G0Ar12sIu-yDQrwBVP6S3Q"  # dev bot
#CHAT_ID = "-4161590134"  # dev_4itec_supervision
TOKEN = "6741846240:AAGe2Mcw4sbTmuOCHhN1xJ07Onf9TrSv_fo"  # production bot
CHAT_ID = "-4115471727"

MOTIONTRESHOLD = 15000  # seuil de détection de mouvement pour zone logisitique HAM 
APP_NAME = "4iSafeCross"
APP_VERSION = "0.1"

RTSP_LOGIN = "admin"
RTSP_PASSWORD = "4iTec2025!"
RTSP_HOST = ["192.168.2.156", "192.168.2.157"]  # IP fixes des caméras utilisées par défaut (modifiable ici)
RTSP_PORT = 554
RTSP_STREAM = "stream1"
DB_PATH = 'db/detections.db'

# Définition des zones de détection par défaut
ZONES_DEFAULT = [
    {"name": "zone3", "rect": (0, 0, 640, 480), "color": (255, 255, 0)},    # Cyan
    {"name": "zone2", "rect": (641, 0, 1280, 480), "color": (0, 255, 255)},   # Jaune
    {"name": "zone1", "rect": (0, 481, 640, 960), "color": (255, 0, 255)},    # Magenta
]
# Définition des zones de détection par caméra (exemple pour 2 caméras)
ZONES_BY_CAMERA = {
    0: [
        # {"name": "zone3_cam0", "rect": (0, 0, 1920, 180), "color": (255, 255, 0)},
        {"name": "zone3_cam0", "polygon": [(1105, 30), (1103, 110), (1238, 290), (1887, 1074), (1, 1068),
                                            (1, 388), (443, 388), (441, 225), (743, 225), (743, 32)],
                                            "color": (255, 255, 0)},
        {"name": "zone2_cam0", "polygon": [(1200, 80), (1500, 80), (1920, 800), (1800, 1080)], "color": (0, 255, 255)},# Cyan
        # {"name": "zone2_cam0", "rect": (0, 180, 1920, 740), "color": (0, 255, 255)},   # Jaune
        # {"name": "zone1_cam0", "rect": (0, 380, 1920, 1080), "color": (255, 0, 255)},  # Magenta
        {"name": "zone1_cam0", "polygon": [(0, 380), (1350, 380), (1920, 1080), (0, 1080)], "color": (255, 0, 255)},  # Magenta
    ],
    1: [
        {"name": "zone3_cam1", "rect": (0, 0, 800, 600), "color": (255, 255, 0)},      # Cyan
        {"name": "zone2_cam1", "rect": (801, 0, 1600, 600), "color": (0, 255, 255)},   # Jaune
        {"name": "zone1_cam1", "rect": (0, 601, 1600, 1200), "color": (255, 0, 255)},  # Magenta
    ],
}

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
