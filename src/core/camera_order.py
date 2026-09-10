"""Ordre et identité des caméras.

L'index d'une caméra (0, 1, …) est le contrat qui relie tout le reste : sections
``zone*_cam<i>`` et ``mask*_cam<i>`` des fichiers INI, relais pilotés, vue
``Camera <i+1>`` de l'IHM, éditeur de zones, fail-safe par caméra. Il doit donc
être **la position de l'hôte dans ``[RTSP] HOST`` de config.ini**, et rien
d'autre — jamais l'ordre dans lequel les caméras répondent au réseau, ni un
ordre compacté après retrait des caméras absentes.

Historique : le test RTSP parallèle du démarrage remplissait son dictionnaire de
résultats dans l'ordre de *fin* des tests (``as_completed``) et seules les caméras
ayant répondu étaient conservées. La première à répondre devenait l'index 0 : un
démarrage sur deux, la caméra .61 héritait des zones, relais et vue de la .60,
et une zone dessinée dans l'éditeur était enregistrée sous le mauvais ``_cam``.

Module sans dépendance (ni GStreamer, ni état applicatif) : testable à sec.
"""
from urllib.parse import urlsplit


def order_cameras(configured, results):
    """Retourne ``(toutes, disponibles)``, les deux **dans l'ordre configuré**.

    ``configured`` : identifiants caméra dans l'ordre de config.ini.
    ``results``    : ``{identifiant: bool}`` issu du test RTSP, dans n'importe
                     quel ordre (celui de fin des tests, en pratique).

    ``toutes`` est la liste à exposer comme ``state.cam_ids`` : une caméra
    absente y garde sa place, donc son index, ses zones et son fail-safe.
    ``disponibles`` ne sert qu'à décider si le démarrage peut continuer.
    """
    toutes = list(configured)
    disponibles = [cid for cid in configured if results.get(cid, False)]
    return toutes, disponibles


def rtsp_host(cam_id):
    """Hôte d'une URL RTSP, pour libeller les vues sans exposer les identifiants.

    ``rtsp://login:pwd@172.16.10.169:554/stream1`` → ``172.16.10.169``.
    Un identifiant non-URL (index V4L2 entier) est renvoyé tel quel.
    """
    if not isinstance(cam_id, str):
        return str(cam_id)
    try:
        return urlsplit(cam_id).hostname or cam_id
    except ValueError:
        return cam_id
