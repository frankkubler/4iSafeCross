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
import re
from urllib.parse import urlsplit

# Autorité d'une URL RTSP telle que l'application la construit :
# ``<schéma>://<login>:<mot de passe>@<hôte>[:<port>]/<chemin>``. Le mot de passe
# n'est PAS percent-encodé (config.ini / .env bruts) : il peut contenir ``?``, ``#``,
# ``/`` ou ``@``, que urlsplit interprète comme début de requête, de fragment, de
# chemin ou fin d'userinfo — l'hôte devient alors le login. On repère donc le
# DERNIER ``@`` suivi d'un hôte plausible, et on ne fait confiance qu'à ce qui suit.
_AUTHORITY_RE = re.compile(r'^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>.*)@(?P<rest>[^/@?#]+(?:/.*)?)$')


def split_userinfo(url):
    """``(préfixe 'rtsp://', userinfo, reste 'hôte[:port]/chemin')`` ou ``None``.

    ``None`` si l'URL n'a pas d'userinfo (``rtsp://hôte/…``) ou n'est pas une URL.
    """
    if not isinstance(url, str):
        return None
    m = _AUTHORITY_RE.match(url)
    if not m:
        return None
    return m.group('scheme'), m.group('userinfo'), m.group('rest')


# Une URL RTSP telle qu'elle apparaît DANS un texte : chaîne de pipeline GStreamer,
# message d'erreur, ligne de commande. Elle s'arrête au premier blanc.
_URL_IN_TEXT = re.compile(r'rtsps?://\S*')


def strip_userinfo(value, replacement='***@'):
    """Masque login et mot de passe de **toute** URL RTSP contenue dans ``value``.

    Le masquage doit fonctionner au milieu d'un texte, pas seulement sur une URL
    isolée : le pipeline GStreamer est journalisé en entier
    (``rtspsrc location=rtsp://login:mdp@hote:554/stream1 latency=200 ! …``) et
    c'est là que le mot de passe a fui — une expression ancrée sur l'URL entière
    ne reconnaissait pas cette chaîne et la renvoyait telle quelle.
    """
    if not isinstance(value, str):
        return value

    def _masque(m):
        parts = split_userinfo(m.group(0))
        if parts is None:
            return m.group(0)          # URL sans identifiants : rien à masquer
        scheme, _, rest = parts
        return f"{scheme}{replacement}{rest}"

    return _URL_IN_TEXT.sub(_masque, value)


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


def camera_label(idx, cam_id):
    """Libellé d'une vue caméra : ``Caméra 0 — 172.16.10.169``.

    L'index affiché est l'index technique, **sans décalage** : c'est celui des
    sections ``*_cam<i>``, des images ``cam_<i>_*.jpg``, des URL ``/zone_editor/<i>``
    et de tous les messages de journal. L'IHM affichait auparavant ``Camera <i+1>``,
    seule numérotation 1-based du système : un « caméra 1 » lu dans un journal
    désignait la vue « Camera 2 » de l'écran.
    """
    return f"Caméra {idx} — {rtsp_host(cam_id)}"


def rtsp_host_port(url, default_port=554):
    """``(hôte, port)`` d'une URL RTSP, ou ``None`` si ce n'en est pas une.

    Sert au test TCP de disponibilité : l'ancienne expression ``(?:[^@]+@)?([^/:]+)``
    s'arrêtait au PREMIER ``@`` — un ``@`` dans le mot de passe donnait l'hôte
    ``ret1@172.16.10.169`` et une caméra déclarée absente au démarrage.
    """
    if not isinstance(url, str) or not re.match(r'^rtsps?://', url):
        return None
    parts = split_userinfo(url)
    rest = parts[2] if parts is not None else url.split('://', 1)[1]
    authority = rest.split('/', 1)[0]
    m = re.match(r'^([^:]+)(?::(\d+))?$', authority)
    if not m or not m.group(1):
        return None
    return m.group(1), int(m.group(2)) if m.group(2) else default_port


def rtsp_host(cam_id):
    """Hôte d'une URL RTSP, pour libeller les vues sans exposer les identifiants.

    ``rtsp://login:pwd@172.16.10.169:554/stream1`` → ``172.16.10.169``.
    Un identifiant non-URL (index V4L2 entier) est renvoyé tel quel.
    """
    if not isinstance(cam_id, str):
        return str(cam_id)
    parts = split_userinfo(cam_id)
    if parts is not None:
        # Hôte = ce qui suit le dernier « @ », avant « : » (port) ou « / » (chemin).
        rest = parts[2]
        host = re.split(r'[:/]', rest, maxsplit=1)[0]
        return host or cam_id
    try:
        return urlsplit(cam_id).hostname or cam_id
    except ValueError:
        return cam_id
