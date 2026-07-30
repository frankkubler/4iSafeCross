"""
Script standalone pour tester l'éditeur de zones avec une image statique.

Lance un mini-serveur Flask sur le port 5051 qui simule l'interface
4iSafeCross avec une image fixe au lieu d'un flux caméra RTSP.

Usage :
    python test_zone_editor.py

Puis ouvrir http://localhost:5051 dans un navigateur.
"""

import os
import logging
import cv2
import numpy as np
from flask import Flask, render_template, Response, request, jsonify

from utils.constants import load_zones_by_camera_from_ini
from utils.zone_writer import save_zones_to_ini

# --- Configuration ---
ZONES_INI_PATH = "config/zones.ini"
STATIC_IMAGE_PATH = "static/res/test_snapshot.jpg"
CAM_ID = 0  # Caméra simulée

# Palette de couleurs automatiques
ZONE_COLORS_PALETTE = [
    (128, 255, 0),
    (255, 128, 0),
    (255, 255, 0),
    (0, 255, 255),
    (255, 0, 255),
    (0, 128, 255),
    (255, 64, 64),
    (128, 0, 255),
]

# --- App Flask ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Charger les zones au démarrage
zones_by_camera = load_zones_by_camera_from_ini(ZONES_INI_PATH)


@app.route("/")
def index():
    """Page d'accueil minimaliste avec aperçu et lien vers l'éditeur."""
    nb_zones = len(zones_by_camera.get(CAM_ID, []))
    return f"""<!DOCTYPE html>
<html><head>
    <title>4iSafeCross — Test Zone Editor</title>
    <style>
        body {{ font-family: Arial, sans-serif; background: #1a1a2e; color: #e0e0e0; margin: 0; padding: 0; }}
        .container {{ max-width: 900px; margin: 40px auto; text-align: center; }}
        h1 {{ color: #fff; margin-bottom: 8px; }}
        .subtitle {{ color: #888; margin-bottom: 30px; }}
        .preview {{ width: 100%; max-width: 800px; border-radius: 8px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.5); margin-bottom: 20px; }}
        .info {{ background: #16213e; padding: 16px; border-radius: 8px; margin-bottom: 20px;
                 display: inline-block; }}
        .btn {{ display: inline-block; padding: 14px 32px; border-radius: 8px; font-size: 1.1rem;
                text-decoration: none; color: #fff; margin: 8px; transition: transform 0.1s; }}
        .btn:hover {{ transform: translateY(-2px); }}
        .btn-edit {{ background: #9c27b0; }}
        .btn-reload {{ background: #555; }}
    </style>
</head><body>
    <div class="container">
        <h1>4iSafeCross — Test Zone Editor</h1>
        <p class="subtitle">Mode test avec image statique — Camera {CAM_ID}</p>
        <img src="/preview_with_zones/{CAM_ID}" class="preview" alt="Snapshot caméra avec zones">
        <div class="info">
            <strong>{nb_zones}</strong> zone(s) définies pour la caméra {CAM_ID} dans <code>zones.ini</code>
        </div>
        <br>
        <a href="/zone_editor/{CAM_ID}" class="btn btn-edit">✏️ Éditer les zones</a>
        <a href="/" class="btn btn-reload">↻ Rafraîchir</a>
    </div>
</body></html>"""


@app.route("/snapshot/<int:cid>")
def snapshot(cid):
    """Retourne l'image statique brute (utilisée par l'éditeur de zones)."""
    if not os.path.exists(STATIC_IMAGE_PATH):
        return jsonify({"error": f"Image non trouvée : {STATIC_IMAGE_PATH}"}), 404
    with open(STATIC_IMAGE_PATH, "rb") as f:
        img_bytes = f.read()
    return Response(img_bytes, mimetype="image/jpeg")


@app.route("/preview_with_zones/<int:cid>")
def preview_with_zones(cid):
    """Retourne l'image avec les zones dessinées par-dessus (aperçu)."""
    if not os.path.exists(STATIC_IMAGE_PATH):
        return jsonify({"error": f"Image non trouvée : {STATIC_IMAGE_PATH}"}), 404

    # Lire l'image avec OpenCV
    frame = cv2.imread(STATIC_IMAGE_PATH)
    if frame is None:
        return jsonify({"error": "Impossible de lire l'image"}), 500

    h, w = frame.shape[:2]
    zones = zones_by_camera.get(cid, [])

    for zone in zones:
        color_rgb = zone.get("color", (0, 255, 0))
        # OpenCV utilise BGR
        color_bgr = (color_rgb[2], color_rgb[1], color_rgb[0])

        if "polygon" in zone:
            pts = np.array(zone["polygon"], dtype=np.int32)
            # Dessiner le contour du polygone
            cv2.polylines(frame, [pts], isClosed=True, color=color_bgr, thickness=3)
            # Remplissage semi-transparent
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], color=color_bgr)
            cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)
            # Nom de la zone
            if len(pts) > 0:
                cv2.putText(
                    frame, zone["name"],
                    (int(pts[0][0]), int(pts[0][1]) + 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color_bgr, 2,
                )

    # Encoder en JPEG
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(buffer.tobytes(), mimetype="image/jpeg")


@app.route("/api/zones/<int:cid>", methods=["GET"])
def get_zones(cid):
    """Retourne les zones polygones en JSON."""
    zones = zones_by_camera.get(cid, [])
    result = []
    for zone in zones:
        if "polygon" not in zone:
            continue
        result.append({
            "name": zone["name"],
            "polygon": [list(pt) for pt in zone["polygon"]],
            "color": list(zone.get("color", (255, 0, 0))),
        })
    return jsonify(result)


@app.route("/api/zones/<int:cid>", methods=["POST"])
def save_zones(cid):
    """Sauvegarde les zones et recharge."""
    global zones_by_camera
    data = request.get_json()
    zones_data = data.get("zones", [])

    for i, zone in enumerate(zones_data):
        if "color" not in zone or not zone["color"]:
            zone["color"] = list(ZONE_COLORS_PALETTE[i % len(ZONE_COLORS_PALETTE)])
        if "name" not in zone or not zone["name"]:
            zone["name"] = f"zone{i + 1}_cam{cid}"

    try:
        save_zones_to_ini(ZONES_INI_PATH, cid, zones_data)
        zones_by_camera = load_zones_by_camera_from_ini(ZONES_INI_PATH)
        logger.info(f"✅ Zones cam{cid} sauvegardées ({len(zones_data)} zones)")
        return jsonify({"status": "ok", "zones_count": len(zones_data)})
    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/zone_editor/<int:cid>")
def zone_editor(cid):
    """Page d'édition des zones."""
    return render_template(
        "zone_editor.html",
        cid=cid,
        cam_name=f"Camera {cid + 1}",
        app_name="4iSafeCross (test)",
        app_version="dev",
    )


if __name__ == "__main__":
    # Vérifier que l'image statique existe
    if not os.path.exists(STATIC_IMAGE_PATH):
        print(f"⚠️  Image non trouvée : {STATIC_IMAGE_PATH}")
        print(f"   Placez une image JPEG à cet emplacement pour tester.")
        print(f"   Chemin absolu : {os.path.abspath(STATIC_IMAGE_PATH)}")
    else:
        print(f"✅ Image statique : {STATIC_IMAGE_PATH}")

    print(f"✅ Zones INI : {os.path.abspath(ZONES_INI_PATH)}")
    print(f"   Zones cam{CAM_ID} : {len(zones_by_camera.get(CAM_ID, []))} zone(s)")
    print()
    print(f"🌐 Serveur démarré sur http://localhost:5051")
    print(f"   Éditeur direct : http://localhost:5051/zone_editor/{CAM_ID}")
    print()

    app.run(host="0.0.0.0", port=5051, debug=True)
