"""Charge GPU — multi-plateforme, best-effort, jamais bloquant ni fatal.

Cibles :
- **Jetson** (Orin, cible principale) : charge GPU lue dans sysfs
  (``/sys/devices/.../load``, valeur en pour-mille) sans sous-process ;
  repli sur un lecteur ``tegrastats`` en arrière-plan si sysfs est absent.
- **AMD** : ``gpu_busy_percent`` exposé directement dans sysfs.
- **Intel iGPU** : aucune charge instantanée en sysfs ; ``intel_gpu_top`` est
  requis (outil de streaming). Le backend est détecté mais ``gpu_percent`` reste
  None avec une note — à câbler/valider sur la machine cible.

Le GPU Jetson/Intel partageant la RAM système, l'empreinte mémoire GPU est déjà
couverte par les métriques process/cgroup (voir src/core/system_metrics.py).

⚠️  Non validé sur GPU réel (développé hors Jetson/Intel) : le parseur
tegrastats est testé sur des lignes d'exemple, mais les chemins sysfs et le
lancement de tegrastats/intel_gpu_top doivent être confirmés sur la cible.
"""
import glob
import logging
import re
import shutil
import threading
import time

logger = logging.getLogger(__name__)

# Chemins sysfs candidats pour la charge GPU Jetson (varie selon JetPack/SoC).
# Valeur en pour-mille (0–1000) sur la plupart des L4T.
_JETSON_LOAD_GLOBS = [
    "/sys/devices/gpu.0/load",
    "/sys/devices/platform/gpu.0/load",
    "/sys/devices/platform/*.gpu/load",
    "/sys/devices/platform/*/*.ga10b/load",   # Orin (GPU ga10b)
    "/sys/devices/platform/bus@0/*.gpu/load",
]
# AMD : busy % directement en sysfs.
_AMD_BUSY_GLOB = "/sys/class/drm/card*/device/gpu_busy_percent"

_TTL = 1.0  # cache des lectures pour ne pas marteler sysfs à chaque poll

_lock = threading.Lock()
_state = {
    "initialized": False,
    "backend": None,        # 'jetson' | 'amd' | 'intel' | None
    "load_path": None,      # chemin sysfs retenu, le cas échéant
    "cached": None,         # dernier dict retourné
    "cached_ts": 0.0,
    # Valeur alimentée par le thread tegrastats (repli Jetson sans sysfs).
    "tegra_value": None,
    "tegra_started": False,
    # Valeur alimentée par le thread intel_gpu_top.
    "intel_value": None,
    "intel_started": False,
}


def parse_tegrastats(line):
    """Extrait la charge et la température GPU d'une ligne tegrastats.

    Fonction pure (testable) — ex. d'entrée :
      ``... GR3D_FREQ 45%@610 ... GPU@43.5C ...``
    """
    result = {}
    m = re.search(r'GR3D_FREQ\s+(\d+)%', line)
    if m:
        result["gpu_percent"] = float(m.group(1))
    m = re.search(r'GPU@([\d.]+)C', line)
    if m:
        result["gpu_temp_c"] = float(m.group(1))
    return result


def extract_intel_busy(sample):
    """Charge GPU (%) depuis un objet JSON ``intel_gpu_top -J`` : max des moteurs.

    Le format ``-J`` expose ``{"engines": {"Render/3D/0": {"busy": 0.77,
    "unit": "%"}, "Video/0": {"busy": 3.61, ...}, ...}}``. On itère sur les
    valeurs (indépendant du nommage des moteurs) et retourne le max. Retourne
    None si aucune donnée d'occupation (→ repli sur la note).

    Fonction pure (testable).
    """
    engines = sample.get("engines")
    if not isinstance(engines, dict):
        return None
    busy = []
    for eng in engines.values():
        if isinstance(eng, dict) and "busy" in eng:
            try:
                busy.append(float(eng["busy"]))
            except (TypeError, ValueError):
                pass
    if not busy:
        return None
    return {"gpu_percent": round(max(busy), 1)}


def _intel_gpu_reader():
    """Thread daemon : lit intel_gpu_top -J en flux, met à jour la dernière valeur.

    La sortie -J est un tableau JSON dont les objets arrivent au fil de l'eau
    (``[`` puis objets séparés par ``,``). On les décode un par un avec
    JSONDecoder.raw_decode dès qu'ils sont complets.
    """
    import json
    import subprocess
    try:
        proc = subprocess.Popen(
            ["intel_gpu_top", "-J", "-s", "1000"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
    except (OSError, ValueError) as e:
        logger.warning(f"intel_gpu_top indisponible : {e}")
        return
    dec = json.JSONDecoder()
    buf = ""
    for chunk in iter(lambda: proc.stdout.read(4096), ''):
        buf += chunk
        while True:
            # Sauter le '[' initial et les séparateurs entre objets.
            i = 0
            while i < len(buf) and buf[i] in '[ ,\n\r\t':
                i += 1
            buf = buf[i:]
            if not buf.startswith('{'):
                break
            try:
                obj, end = dec.raw_decode(buf)
            except ValueError:
                break  # objet encore incomplet : attendre plus de données
            buf = buf[end:]
            parsed = extract_intel_busy(obj)
            if parsed:
                with _lock:
                    _state["intel_value"] = parsed


def _read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _first_existing(globs):
    for pattern in globs:
        for path in glob.glob(pattern):
            if _read_int(path) is not None:
                return path
    return None


def _tegrastats_reader():
    """Thread daemon : lit tegrastats en continu, met à jour la dernière valeur."""
    import subprocess
    try:
        proc = subprocess.Popen(
            ["tegrastats", "--interval", "1000"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
    except (OSError, ValueError) as e:
        logger.warning(f"tegrastats indisponible : {e}")
        return
    for line in proc.stdout:
        parsed = parse_tegrastats(line)
        if parsed:
            with _lock:
                _state["tegra_value"] = parsed


def _detect_backend():
    """Détermine le backend GPU et la meilleure source de mesure (une seule fois)."""
    jetson_path = _first_existing(_JETSON_LOAD_GLOBS)
    if jetson_path is not None:
        _state["backend"] = "jetson"
        _state["load_path"] = jetson_path
        return
    # Jetson détecté mais sans sysfs load → repli tegrastats.
    if shutil.which("tegrastats") is not None:
        _state["backend"] = "jetson"
        return
    amd_path = _first_existing([_AMD_BUSY_GLOB])
    if amd_path is not None:
        _state["backend"] = "amd"
        _state["load_path"] = amd_path
        return
    if shutil.which("intel_gpu_top") is not None:
        _state["backend"] = "intel"
        return
    _state["backend"] = None


def get_gpu_metrics():
    """Retourne {backend, gpu_percent, ...} ou None si aucun GPU détecté.

    Ne lève jamais. Résultat mis en cache pendant _TTL secondes.
    """
    now = time.time()
    with _lock:
        if not _state["initialized"]:
            try:
                _detect_backend()
            except Exception as e:  # détection best-effort, ne doit jamais casser
                logger.warning(f"Détection GPU échouée : {e}")
            _state["initialized"] = True

        if _state["cached"] is not None and now - _state["cached_ts"] < _TTL:
            return _state["cached"]

        backend = _state["backend"]
        if backend is None:
            _state["cached"] = None
            _state["cached_ts"] = now
            return None

        result = {"backend": backend}

        if _state["load_path"] is not None:
            raw = _read_int(_state["load_path"])
            if raw is not None:
                # AMD : déjà en %. Jetson : pour-mille (0–1000) → %.
                if backend == "amd":
                    result["gpu_percent"] = round(float(raw), 1)
                else:
                    result["gpu_percent"] = round(raw / 10.0, 1)
        elif backend == "jetson":
            # Repli tegrastats : démarrer le lecteur une fois, lire la dernière valeur.
            if not _state["tegra_started"]:
                threading.Thread(target=_tegrastats_reader, daemon=True).start()
                _state["tegra_started"] = True
            tv = _state["tegra_value"]
            if tv is not None:
                result.update(tv)
            else:
                result["note"] = "tegrastats : mesure en cours d'amorçage"
        elif backend == "intel":
            # Lecteur intel_gpu_top en arrière-plan (best-effort, non validé matériel).
            if not _state["intel_started"]:
                threading.Thread(target=_intel_gpu_reader, daemon=True).start()
                _state["intel_started"] = True
            iv = _state["intel_value"]
            if iv is not None:
                result.update(iv)
            else:
                result["note"] = "intel_gpu_top : mesure en cours d'amorçage"

        _state["cached"] = result
        _state["cached_ts"] = now
        return result
