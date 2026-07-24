"""Charge GPU — multi-plateforme, best-effort, jamais bloquant ni fatal.

Toutes les sources sont des lectures sysfs (aucun outil, aucun sous-process,
aucun accès PMU, aucun privilège requis) — hormis le repli tegrastats du Jetson.

Cibles :
- **Jetson** (Orin, cible principale) : charge GPU lue dans sysfs
  (``/sys/devices/.../load``, valeur en pour-mille) ; repli sur un lecteur
  ``tegrastats`` en arrière-plan si le chemin sysfs est absent.
- **AMD** : ``gpu_busy_percent`` exposé directement dans sysfs.
- **Intel iGPU** : occupation calculée depuis la résidence RC6 (état
  d'inactivité GPU) dans ``/sys/class/drm/card*/power/rc6_residency_ms`` —
  ``busy% = 100 − ΔRC6/Δt``. Fichier world-readable ; ``intel_gpu_top`` n'est
  pas utilisé (fragile en conteneur : bug get_num_gts sur Gen9, et besoin PMU).

Le GPU Jetson/Intel partageant la RAM système, l'empreinte mémoire GPU est déjà
couverte par les métriques process/cgroup (voir src/core/system_metrics.py).

⚠️  Chemins sysfs Jetson à confirmer sur la cible (varient selon JetPack/SoC).
Le calcul RC6 Intel est validé ; le parseur tegrastats est testé sur exemples.
"""
import glob
import logging
import os
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
# Intel i915 : résidence RC6 (ms cumulées d'inactivité GPU).
_INTEL_RC6_GLOB = "/sys/class/drm/card*/power/rc6_residency_ms"

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
    # Intel : chemins sysfs + dernier échantillon RC6 pour le calcul du delta.
    "intel_rc6_path": None,
    "intel_card": None,
    "intel_last": {"rc6": None, "ts": None},
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


def rc6_busy_percent(rc6_ms, ts, last_rc6_ms, last_ts):
    """Occupation GPU (%) à partir de deux échantillons de résidence RC6.

    RC6 = temps cumulé (ms) passé par le GPU en état d'inactivité.
    ``busy% = 100 − (ΔRC6 / Δt_ms)``, borné [0, 100]. Retourne None si le
    delta n'est pas calculable (premier échantillon, horloge non avancée).

    Fonction pure (testable).
    """
    if (rc6_ms is None or last_rc6_ms is None or last_ts is None
            or ts <= last_ts):
        return None
    idle_frac = (rc6_ms - last_rc6_ms) / ((ts - last_ts) * 1000.0)
    return round(max(0.0, min(100.0, 100.0 * (1.0 - idle_frac))), 1)


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
    # Intel i915 : résidence RC6 en sysfs (world-readable, ni outil ni PMU).
    for rc6 in glob.glob(_INTEL_RC6_GLOB):
        if _read_int(rc6) is not None:
            _state["backend"] = "intel"
            _state["intel_rc6_path"] = rc6
            # .../drm/cardN/power/rc6_residency_ms → .../drm/cardN
            _state["intel_card"] = os.path.dirname(os.path.dirname(rc6))
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
            # Occupation via delta de résidence RC6 (aucun outil, aucun PMU).
            rc6 = _read_int(_state["intel_rc6_path"])
            last = _state["intel_last"]
            busy = rc6_busy_percent(rc6, now, last["rc6"], last["ts"])
            _state["intel_last"] = {"rc6": rc6, "ts": now}
            if busy is not None:
                result["gpu_percent"] = busy
            else:
                result["note"] = "charge GPU : amorçage de la mesure RC6"
            # Fréquence GPU (contexte, best-effort).
            act = _read_int(os.path.join(_state["intel_card"], "gt_act_freq_mhz"))
            mx = _read_int(os.path.join(_state["intel_card"], "gt_max_freq_mhz"))
            if act is not None:
                result["freq_mhz"] = act
            if mx is not None:
                result["freq_max_mhz"] = mx

        _state["cached"] = result
        _state["cached_ts"] = now
        return result
