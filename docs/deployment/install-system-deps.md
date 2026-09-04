# Dépendances système — GStreamer et PyGObject

`pygobject` (binding Python vers GLib/GStreamer) est une extension C qui doit être compilée
contre les headers système. Les paquets ci-dessous sont **obligatoires** avant `uv sync`.

> **Périmètre — à lire avant d'installer quoi que ce soit.**
> Ces paquets ne sont nécessaires que pour exécuter l'application **depuis les sources**
> (poste de développement, diagnostic sur cible). En **production, l'application tourne en
> conteneur** : GStreamer, PyGObject, CUDA et TensorRT sont fournis par l'image, et l'hôte
> n'a besoin que de Docker et du runtime NVIDIA.
> 👉 Procédure de déploiement sur machine de production :
> [install-prod-jetson-docker.md](install-prod-jetson-docker.md).

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

### Carte porteuse Seeed (reServer Industrial J4012) — geler les paquets firmware

Sur le boîtier de série, le module Orin NX est monté sur une carte porteuse **Seeed** et
flashé avec l'image `mfi_reserver-orin-industrial` (voir
[flash-jetson-reserver-j4012-jetpack72.md](flash-jetson-reserver-j4012-jetpack72.md)).
Son `COMPATIBLE_SPEC` porte le nom de la carte Seeed, absent de la liste des cartes
connues du payload updater NVIDIA :

```
COMPATIBLE_SPEC 3767-000-0000--1--reserver-industrial-orin-j401-
```

Le `postinst` de `nvidia-l4t-bootloader` ne pose pas que des fichiers : il **reflashe la
QSPI**. Toute opération apt qui met ce paquet à jour — `apt full-upgrade`, mais aussi un
`apt install nvidia-l4t-gstreamer` qui tire `nvidia-l4t-bsp` — échoue donc avec :

```
ERROR. 3767-000-0000--1--reserver-industrial-orin-j401- does not match any known boards.
dpkg: error processing package nvidia-l4t-bootloader (--configure)
```

et laisse **dpkg dans un état incohérent** qui bloque toutes les opérations apt suivantes
(y compris `unattended-upgrades`). Les lignes `Failed to find known boot media` et
`esp is not mounted to /boot/efi` du même message sont des symptômes du même échec de
détection de carte, pas un second problème.

> **Ne jamais forcer cette mise à jour.** Écrire le payload bootloader NVIDIA générique
> dans la QSPI d'une carte porteuse Seeed (device tree / pinmux différents) peut rendre le
> boîtier non amorçable. Le firmware de cette carte se met à jour **uniquement** par la
> procédure Seeed en Force Recovery (image `mfi_*`), jamais par apt.

#### Prévention — à faire avant toute opération apt sur le boîtier

```bash
sudo apt-mark hold nvidia-l4t-bootloader nvidia-l4t-bsp

# Plus robuste qu'un hold (résiste à un unhold accidentel) :
sudo tee /etc/apt/preferences.d/10-nvidia-l4t-freeze <<'EOF'
Package: nvidia-l4t-bootloader nvidia-l4t-bsp nvidia-l4t-xusb-firmware
Pin: release *
Pin-Priority: -1
EOF
```

Vérifier aussi que `unattended-upgrades` ne cible pas l'origine NVIDIA :

```bash
grep -A10 Allowed-Origins /etc/apt/apt.conf.d/50unattended-upgrades
```

Rappel : sur cible, on n'applique **jamais** un `apt full-upgrade` / `dist-upgrade`, mais
uniquement `apt-get install --only-upgrade <paquets ciblés>` depuis le dépôt local
([maj-l4t-hors-ligne.md](maj-l4t-hors-ligne.md), §5.2).

#### Réparation — si dpkg est déjà bloqué

`chmod -x` sur le `postinst` ne suffit pas (dpkg exécute quand même le script). Il faut le
remplacer temporairement par un stub :

```bash
# 0. sauvegarde du script d'origine
sudo cp -a /var/lib/dpkg/info/nvidia-l4t-bootloader.postinst \
           /root/nvidia-l4t-bootloader.postinst.orig

# 1. stub neutre
printf '#!/bin/sh\nexit 0\n' \
  | sudo tee /var/lib/dpkg/info/nvidia-l4t-bootloader.postinst >/dev/null
sudo chmod 755 /var/lib/dpkg/info/nvidia-l4t-bootloader.postinst

# 2. finaliser l'état dpkg (aucune écriture en QSPI)
sudo dpkg --configure -a

# 3. restaurer le script d'origine — le paquet est configuré, il ne sera pas rejoué
sudo cp -a /root/nvidia-l4t-bootloader.postinst.orig \
           /var/lib/dpkg/info/nvidia-l4t-bootloader.postinst

# 4. contrôles
dpkg -l nvidia-l4t-bootloader nvidia-l4t-bsp   # attendu : "hi" (hold + installed OK)
sudo apt-get check
```

Après cette manipulation, le rootfs porte la nouvelle révision alors que la **QSPI reste
sur l'ancienne** (`sudo nvbootctrl dump-slots-info`, `cat /etc/nv_tegra_release`). L'écart
de révision mineure est sans effet fonctionnel connu, mais il doit être **consigné au
registre des mises à jour** ([maj-l4t-hors-ligne.md](maj-l4t-hors-ligne.md), §7) : sans
cela, un boîtier de rechange reflashé depuis l'image d'origine n'aura pas le même état
firmware que celui-ci, ce qui rompt l'identité de parc exigée par `CS-1141-01`.

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
