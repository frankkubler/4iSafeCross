#!/usr/bin/env python3
"""Rapport de décomposition des latences du pipeline d'inférence.

Interroge les deux extrémités de la chaîne et affiche où part le temps d'un
cycle de détection, pour arbitrer sur l'intérêt d'un transport ZeroMQ :

  - 4iSafeCross  GET /api/inference/stats  → mesures par caméra (côté client)
  - inf_jetson   GET /timing_stats/        → mesures agrégées (côté serveur)

Usage (depuis la Jetson, les deux services étant en network_mode: host) :

    python3 scripts/latency_report.py
    python3 scripts/latency_report.py --host 192.168.2.10
    python3 scripts/latency_report.py --reset      # vide les fenêtres puis sort

Protocole de mesure conseillé :
    1. --reset, puis laisser tourner 2-3 min avec UNE seule caméra active
       (désactiver la détection de la seconde via l'UI) → relever le rapport.
    2. --reset, réactiver les deux caméras, attendre 2-3 min → relever à nouveau.
    L'écart sur `wait` entre les deux runs mesure la contention réelle.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request


def fetch(url, method="GET", timeout=5):
    """Récupère un JSON, ou retourne None en cas d'échec (service arrêté)."""
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as err:
        print(f"  ⚠️  {url} injoignable : {err}", file=sys.stderr)
        return None


def format_phase_table(phases, order):
    """Rend un tableau p50/p95/moyenne pour les phases demandées."""
    lines = [f"    {'phase':<14}{'p50':>9}{'p95':>9}{'moy':>9}{'n':>8}"]
    lines.append(f"    {'-' * 48}")
    for phase in order:
        values = phases.get(phase)
        if not values or not values.get("count"):
            lines.append(f"    {phase:<14}{'—':>9}{'—':>9}{'—':>9}{0:>8}")
            continue
        lines.append(
            f"    {phase:<14}"
            f"{values['p50']:>9.1f}"
            f"{values.get('p95', 0):>9.1f}"
            f"{values['mean']:>9.1f}"
            f"{values['count']:>8}"
        )
    return "\n".join(lines)


CLIENT_PHASES = ("serialize", "uplink", "parse", "deserialize",
                 "detect", "pose", "downlink", "roundtrip")
SERVER_PHASES = ("wait", "parse", "deserialize", "detect", "pose", "server_total")


def report_client(app_url):
    """Affiche la décomposition par caméra vue du client 4iSafeCross."""
    print("═" * 60)
    print("CÔTÉ CLIENT (4iSafeCross) — décomposition par caméra")
    print("═" * 60)

    stats = fetch(f"{app_url}/api/inference/stats")
    if not stats:
        return None

    verdicts = []
    for camera_name, camera in sorted(stats.get("cameras", {}).items()):
        latency = camera.get("latency")
        print(f"\n  {camera_name}  (mode {camera.get('inference_mode')}, "
              f"{camera.get('skip_rate')}% de frames sautées)")
        if not latency or not latency.get("cycle_p50_ms"):
            print("    aucune mesure — la caméra a-t-elle détecté du mouvement ?")
            continue

        print(format_phase_table(latency["phases"], CLIENT_PHASES))
        transport = latency["transport_overhead_p50_ms"]
        inference = latency["inference_p50_ms"]
        cycle = latency["cycle_p50_ms"]
        print(f"\n    transport (supprimable par ZeroMQ) : {transport:>7.1f} ms"
              f"  ({latency['transport_share_pct']}% du cycle)")
        print(f"    inférence TensorRT (incompressible) : {inference:>7.1f} ms")
        print(f"    cycle complet                       : {cycle:>7.1f} ms")
        verdicts.append((camera_name, transport, inference, cycle))

    return verdicts


def report_server(inference_url):
    """Affiche la vue serveur, y compris le parallélisme réel des requêtes."""
    print("\n" + "═" * 60)
    print("CÔTÉ SERVEUR (inf_jetson_yolo) — vue agrégée")
    print("═" * 60)

    stats = fetch(f"{inference_url}/timing_stats/")
    if not stats:
        return

    print(f"\n{format_phase_table(stats['phases'], SERVER_PHASES)}")
    print(f"\n    transport imputable HTTP : {stats['transport_overhead_p50_ms']:>7.1f} ms")
    print(f"    inférence TensorRT       : {stats['inference_p50_ms']:>7.1f} ms")

    peak = stats.get("inflight_max", 0)
    print(f"\n    requêtes simultanées (pic) : {peak}")
    if peak <= 1:
        print("    → Les requêtes sont sérialisées. `model.predict()` est un appel")
        print("      bloquant dans un `async def` : il gèle l'event loop uvicorn.")
        print("      Avec 2 caméras, la seconde requête attend la fin complète de")
        print("      la première — ce délai apparaît dans la phase `wait`.")


def print_verdict(verdicts):
    """Conclut sur l'intérêt du passage à ZeroMQ au vu des mesures."""
    if not verdicts:
        return
    print("\n" + "═" * 60)
    print("LECTURE")
    print("═" * 60)

    total_transport = sum(v[1] for v in verdicts) / len(verdicts)
    total_cycle = sum(v[3] for v in verdicts) / len(verdicts)
    share = total_transport / total_cycle * 100 if total_cycle else 0

    print(f"\n  Transport moyen : {total_transport:.1f} ms sur {total_cycle:.1f} ms"
          f" de cycle ({share:.0f}%).")
    if share >= 25:
        print("  → ZeroMQ vaut l'effort : le transport pèse plus d'un quart du cycle.")
    elif share >= 12:
        print("  → Gain réel mais modéré. À arbitrer contre le coût de migration ;")
        print("    vérifier d'abord la phase `wait` (contention) qui, elle, se")
        print("    corrige sans changer de transport.")
    else:
        print("  → ZeroMQ n'est pas le levier : le cycle est dominé par l'inférence.")
        print("    Chercher le gain côté modèle (imgsz, batch) ou côté cadence.")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1",
                        help="Hôte des deux services (défaut : 127.0.0.1)")
    parser.add_argument("--app-port", type=int, default=5050,
                        help="Port de 4iSafeCross (défaut : 5050)")
    parser.add_argument("--inference-port", type=int, default=8004,
                        help="Port du serveur d'inférence (défaut : 8004)")
    parser.add_argument("--reset", action="store_true",
                        help="Vide la fenêtre de mesure côté serveur puis sort")
    args = parser.parse_args()

    app_url = f"http://{args.host}:{args.app_port}"
    inference_url = f"http://{args.host}:{args.inference_port}"

    if args.reset:
        if fetch(f"{inference_url}/timing_stats/reset/", method="POST") is not None:
            print("Fenêtre de mesure serveur réinitialisée.")
            print("Note : les fenêtres client se renouvellent d'elles-mêmes "
                  "(200 derniers cycles).")
        return

    verdicts = report_client(app_url)
    report_server(inference_url)
    print_verdict(verdicts)


if __name__ == "__main__":
    main()
