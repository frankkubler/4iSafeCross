# Dépendances système — GStreamer et PyGObject

`pygobject` (binding Python vers GLib/GStreamer) est une extension C qui doit être compilée
contre les headers système. Les paquets ci-dessous sont **obligatoires** avant `uv sync`.

---

## Dépendances communes (toutes plateformes Linux)

```bash
sudo apt install \
    libgirepository1.0-dev \
    python3-gi \
    gir1.2-gstreamer-1.0 \
    gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-good \
    gstreamer1.0-rtsp \
    gstreamer1.0-plugins-ugly
```

---

## PC Linux — Intel iGPU (décodage hardware VA-API)

> Backend sélectionné automatiquement : `vaapi_new` (GStreamer ≥ 1.20)

```bash
sudo apt install \
    libgirepository1.0-dev \
    python3-gi \
    gir1.2-gstreamer-1.0 \
    gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-rtsp \
    intel-media-va-driver-non-free
```

Vérification :
```bash
gst-inspect-1.0 vah264dec | head -3   # doit retourner "VA-API H.264 Decoder"
vainfo 2>&1 | head -5                 # doit afficher le driver iHD ou i965
```

---

## NVIDIA Jetson (Tegra — JetPack ≥ 4.x)

> Backend sélectionné automatiquement : `jetson` (nvv4l2decoder + nvvidconv)

Les paquets GStreamer NVIDIA sont inclus dans **JetPack**. Si manquants :

```bash
sudo apt install \
    libgirepository1.0-dev \
    python3-gi \
    gir1.2-gstreamer-1.0 \
    gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-good \
    gstreamer1.0-rtsp \
    nvidia-l4t-gstreamer
```

Vérification :
```bash
gst-inspect-1.0 nvv4l2decoder | head -3   # doit retourner le décodeur NVIDIA V4L2
gst-inspect-1.0 nvvidconv    | head -3    # doit retourner le convertisseur NVIDIA
```

---

## Après installation des dépendances système

```bash
cd /mnt/storage/GitLab/4iSafeCross
uv sync
uv run python -c "import gi; gi.require_version('Gst','1.0'); from gi.repository import Gst; Gst.init(None); print('GStreamer OK:', Gst.version_string())"
```

---

## Détection automatique du backend au démarrage

`CameraManager` détecte automatiquement le meilleur backend disponible dans l'ordre suivant :

| Priorité | Backend | Élément GStreamer | Plateforme |
|----------|---------|-------------------|------------|
| 1 | `jetson` | `nvv4l2decoder` | NVIDIA Jetson (L4T) |
| 2 | `vaapi_new` | `vah264dec` | Intel iGPU (GStreamer ≥ 1.20) |
| 3 | `vaapi_legacy` | `vaapidecode` | Intel iGPU (`gstreamer1.0-vaapi`) |
| 4 | `software` | `avdec_h264` | CPU pur (fallback universel) |

Pour forcer un backend spécifique (debug) :
```python
cam = CameraManager(cam_ids=[...])
cam.backend = 'software'   # forcer le fallback CPU
```
