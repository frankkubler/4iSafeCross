"""Métriques de ressources : empreinte de l'application, du conteneur et de l'hôte.

Trois niveaux, du plus utile au plus contextuel :

- **app_**       : le process Python courant via ``psutil.Process``. L'app étant
                   mono-process multi-threads (waitress sans fork + GStreamer +
                   inférence + asyncio), ce process capture toute son empreinte,
                   threads natifs OpenCV/GStreamer inclus.
- **container_** : usage/limite lus dans les fichiers cgroup v2 quand on tourne
                   en conteneur (Docker). Englobe d'éventuels sous-process et
                   reflète la vraie limite si elle est fixée dans le compose.
- **host_**      : la machine entière (``psutil.virtual_memory`` / CPU global) —
                   conservé pour situer l'app dans la charge globale.

La mesure CPU est **non bloquante** : ``cpu_percent(None)`` renvoie le
pourcentage écoulé depuis l'appel précédent (le panneau debug interroge toutes
les secondes), contrairement à ``cpu_percent(interval=…)`` qui bloquait un
thread waitress une demi-seconde par requête. Un verrou sérialise les appels
concurrents pour ne pas corrompre l'état de delta interne.
"""
import logging
import os
import threading
import time

import psutil

logger = logging.getLogger(__name__)

_MB = 1024 * 1024

# cgroup v2 (Docker moderne) : fichiers présents à la racine du cgroup du conteneur.
_CG_MEM_CURRENT = "/sys/fs/cgroup/memory.current"
_CG_MEM_MAX = "/sys/fs/cgroup/memory.max"
_CG_CPU_STAT = "/sys/fs/cgroup/cpu.stat"

_lock = threading.Lock()

# Process courant conservé : cpu_percent(None) mesure le delta entre appels.
_proc = psutil.Process()
_proc.cpu_percent(None)          # amorce (le premier appel retourne toujours 0.0)
psutil.cpu_percent(None)         # idem pour le CPU hôte global
_peak_rss_mb = 0.0

# État pour le CPU cgroup : delta usage_usec / delta temps réel.
_cg_last = {"usage_usec": None, "ts": None}


def _in_container() -> bool:
    return os.path.exists("/.dockerenv") or os.path.exists(_CG_MEM_CURRENT)


def _read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _read_cpu_usage_usec():
    """Lit usage_usec (µs CPU cumulées) dans cpu.stat, ou None."""
    try:
        with open(_CG_CPU_STAT) as f:
            for line in f:
                if line.startswith("usage_usec"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1])
    except (OSError, ValueError):
        pass
    return None


def _container_metrics(ncpu):
    """Métriques cgroup v2 du conteneur, ou None si non conteneurisé/indisponible."""
    if not _in_container():
        return None

    result = {}

    cur = _read_int(_CG_MEM_CURRENT)
    if cur is not None:
        result["mem_used_mb"] = round(cur / _MB, 1)

    # memory.max vaut "max" quand aucune limite n'est fixée dans le compose.
    try:
        with open(_CG_MEM_MAX) as f:
            raw = f.read().strip()
        if raw != "max":
            limit = int(raw)
            result["mem_limit_mb"] = round(limit / _MB, 1)
            if cur is not None and limit > 0:
                result["mem_percent"] = round(cur / limit * 100, 1)
    except (OSError, ValueError):
        pass

    usage = _read_cpu_usage_usec()
    now = time.time()
    if usage is not None:
        last_usage = _cg_last["usage_usec"]
        last_ts = _cg_last["ts"]
        _cg_last["usage_usec"] = usage
        _cg_last["ts"] = now
        if last_usage is not None and last_ts is not None and now > last_ts:
            # (µs CPU consommées) / (µs écoulées) = fraction d'un cœur.
            cpu_frac = (usage - last_usage) / ((now - last_ts) * 1_000_000)
            result["cpu_percent"] = round(cpu_frac * 100, 1)
            result["cpu_percent_norm"] = round(cpu_frac / ncpu * 100, 1)

    return result or None


def get_resource_metrics():
    """Retourne un dict plat de métriques app/conteneur/hôte pour /debug_info.

    Ne lève jamais : toute défaillance de lecture est neutralisée pour ne pas
    faire échouer la route de debug.
    """
    global _peak_rss_mb
    ncpu = psutil.cpu_count() or 1
    metrics = {"cpu_count": ncpu}

    with _lock:
        # ── Application (process courant) ──────────────────────────────────
        try:
            rss_mb = _proc.memory_info().rss / _MB
            app_cpu = _proc.cpu_percent(None)  # % cumulé sur les cœurs (>100 possible)
            _peak_rss_mb = max(_peak_rss_mb, rss_mb)
            metrics["app_ram_mb"] = round(rss_mb, 1)
            metrics["app_ram_peak_mb"] = round(_peak_rss_mb, 1)
            metrics["app_cpu_percent"] = round(app_cpu, 1)
            metrics["app_cpu_percent_norm"] = round(app_cpu / ncpu, 1)
            metrics["app_threads"] = _proc.num_threads()
        except psutil.Error as e:
            logger.warning(f"Métriques process indisponibles : {e}")

        # ── Conteneur (cgroup v2) ──────────────────────────────────────────
        container = _container_metrics(ncpu)

    # ── Hôte (contexte) ────────────────────────────────────────────────────
    try:
        vm = psutil.virtual_memory()
        metrics["host_ram_used_mb"] = round(vm.used / _MB, 1)
        metrics["host_ram_total_mb"] = round(vm.total / _MB, 1)
        metrics["host_ram_percent"] = vm.percent
        metrics["host_cpu_percent"] = psutil.cpu_percent(None)  # non bloquant
    except psutil.Error as e:
        logger.warning(f"Métriques hôte indisponibles : {e}")

    metrics["container"] = container
    return metrics
