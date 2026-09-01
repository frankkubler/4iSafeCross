# Flash JetPack 7.2 sur reServer Industrial J4012

> **Source** : [wiki.seeedstudio.com/reServer_Industrial_Getting_Started](https://wiki.seeedstudio.com/reServer_Industrial_Getting_Started/)
> **Matériel cible** : reServer Industrial J4012 (Jetson Orin NX 16 GB)
> **JetPack** : **7.2** — L4T **r39.2** — rootfs **Ubuntu 24.04**
> **CUDA** : 13.2 · **runtime conteneur** : `nvcr.io/nvidia/cuda:13.2.1-runtime-ubuntu24.04` (`Dockerfile:253`)

---

## Version cible et homologation (`CS-1141-01`)

Le projet cible **une seule** version de firmware pour tout le parc de boîtiers
de référence *reServer Industrial J4012* : **JetPack 7.2 / L4T r39.2**. C'est la
version contre laquelle l'image ARM64 est construite (`Dockerfile:82,249` :
CUDA 13.2.1, dépôts apt L4T `jetson/common` et `jetson/som` en `r39.2`).

> ⚠️ **JetPack 6.2 / L4T 36.4.3 est abandonné** pour ce projet. Toute
> documentation antérieure y faisant référence est obsolète.

**À compléter par le référent technique Stellantis avant la recette FOR_509 :**

| Élément | Valeur | Renseigné par | Date |
|---|---|---|---|
| Version JetPack homologuée | JetPack 7.2 (L4T r39.2) | _réf. technique_ | _____ |
| Origine du BSP | ☐ image Seeed reServer · ☐ NVIDIA Jetson Linux r39.2 + overlay carte | _____ | _____ |
| Empreinte (sha256) de l'image de flash retenue | _____ | 4itec | _____ |
| Parc concerné (n° de série / site) | _____ | 4itec | _____ |
| Canal de mise à jour de sécurité | voir [maj-l4t-hors-ligne.md](maj-l4t-hors-ligne.md) | 4itec | _____ |

L'identité du firmware sur tout le parc d'une même référence est une exigence
`§1.1.4.1` : **flasher exactement la même image** (même empreinte) sur chaque
boîtier, et consigner l'empreinte + la date dans le dossier de recette.

---

## Vue d'ensemble du matériel

![reServer Industrial J4012 — vue complète](https://files.seeedstudio.com/wiki/reServer-Industrial/2.jpg)

![reServer Industrial J4012 — carte mère](https://files.seeedstudio.com/wiki/reServer-Industrial/3.jpg)

---

## Prérequis

### Matériel

| Élément | Détail |
|---|---|
| reServer Industrial J4012 | Module Orin NX 16 GB |
| Alimentation fournie | 24 V / 5 A + cordon secteur |
| PC hôte Ubuntu | **Ubuntu 22.04** (hôte de flash / SDK Manager) — natif ou VMware, **pas WSL**. *À confirmer selon le BSP r39.2 : certains BSP JP7 exigent un hôte Ubuntu 24.04.* |
| Câble USB Type-C | Câble de transmission de données (pas uniquement charge) |
| Écran externe | Connexion HDMI pour la config initiale post-flash |
| Clavier + souris | Pour la config initiale |

### Logiciel hôte

```bash
# Vérifier que le paquet lsusb est disponible
sudo apt update && sudo apt install -y usbutils
```

> ⚠️ Si vous utilisez une machine virtuelle (VMware), assurez-vous que le
> périphérique USB Jetson est bien **redirigé vers la VM** (VM → Removable
> Devices → NVidia Corp → Connect).

---

## Étape 1 — Récupérer l'image système JetPack 7.2

Deux origines possibles ; **le référent technique tranche laquelle est
homologuée** (cf. tableau ci-dessus). Dans les deux cas, conserver l'archive et
son empreinte `sha256` : c'est elle qui sera reflashée pour un rollback ou un
remplacement de boîtier.

| Origine | Contenu | Remarque |
|---|---|---|
| **Image Seeed reServer** (méthode 1 — image complète `mfi_*`) | L4T r39.2 + CUDA 13.2 + cuDNN + TensorRT + pilotes périphériques Seeed | À télécharger depuis le [wiki Seeed](https://wiki.seeedstudio.com/reServer_Industrial_Getting_Started/#different-methods-of-flashing) — **vérifier que la variante JetPack 7.2 est publiée** ; sinon utiliser l'autre origine. |
| **NVIDIA Jetson Linux r39.2** + overlay carte Seeed (méthode 2) | BSP L4T officiel + `Tegra_Linux_Sample_Root_Filesystem` + device tree / overlay reServer J4012 | Nécessite l'overlay carte fourni par Seeed pour le J4012. Empreinte à figer après assemblage. |

```bash
# Vérifier l'empreinte de l'archive AVANT extraction et la consigner
sha256sum <archive_jetpack72>.tar.gz

tar -xvf <archive_jetpack72>.tar.gz
```

Le dossier extrait (image Seeed) s'appelle `mfi_reserver-orin-industrial/`.

---

## Étape 2 — Passer en mode Force Recovery

*(Mécanique carte, inchangée entre JetPack 6.x et 7.x.)*

1. **Connecter** le câble USB Type-C entre le port **DEVICE** du reServer et
   le PC hôte.

2. **Insérer une épingle** dans le trou marqué **REC** pour maintenir le bouton
   de récupération enfoncé.

3. **Tout en maintenant REC**, connecter le bloc terminal 2 broches
   d'alimentation sur le connecteur du boîtier (serrer les 2 vis), puis
   brancher l'adaptateur secteur pour **mettre sous tension**.

4. **Relâcher** le bouton REC après la mise sous tension.

![Connexion USB Type-C et bouton REC pour le mode Force Recovery](https://files.seeedstudio.com/wiki/reServer-Industrial/4.jpg)

> ℹ️ Le board doit être **mis sous tension pendant que REC est maintenu**,
> sinon il ne passera pas en mode recovery.

### Vérification sur le PC hôte

```bash
lsusb
```

La sortie doit contenir l'une des lignes suivantes selon le module :

| Module | ID USB |
|---|---|
| **Orin NX 16 GB** (J4012) | `0955:7323 NVidia Corp` |
| Orin NX 8 GB | `0955:7423 NVidia Corp` |
| Orin Nano 8 GB | `0955:7523 NVidia Corp` |
| Orin Nano 4 GB | `0955:7623 NVidia Corp` |

Si la ligne n'apparaît pas, recommencer l'étape 2.

---

## Étape 3 — Flasher l'image

```bash
cd mfi_reserver-orin-industrial     # (image Seeed) ; sinon dossier Linux_for_Tegra/

sudo ./tools/kernel_flash/l4t_initrd_flash.sh \
  --flash-only \
  --massflash 1 \
  --network usb0 \
  --showlogs
```

Le flash prend plusieurs minutes. En cas de succès, la console affiche :

```
Flash is successful
```

> ⚠️ Ne pas débrancher ni éteindre le board pendant le flash.
>
> Le flash `l4t_initrd_flash` provisionne les **deux slots rootfs A/B** ainsi que
> les slots de bootloader (QSPI). Cette redondance est la base du rollback —
> voir [maj-l4t-hors-ligne.md](maj-l4t-hors-ligne.md).

---

## Étape 4 — Configuration initiale

1. Connecter un écran via le port **HDMI** du reServer.
2. Le board redémarre automatiquement après le flash.
3. Suivre l'assistant de configuration Ubuntu 24.04 (langue, utilisateur, réseau…).
4. Après la configuration, le système est opérationnel sous **JetPack 7.2**.

---

## Vérification post-flash

```bash
# Version L4T
cat /etc/nv_tegra_release
# Attendu : # R39 (release), REVISION: 2.x   (JetPack 7.2)

# Paquets JetPack
dpkg -l | grep -E 'nvidia-l4t-core|nvidia-jetpack'

# CUDA
nvcc --version
# Attendu : release 13.2  (fourni avec JetPack 7.2)

# Rootfs
lsb_release -a
# Attendu : Ubuntu 24.04

# Slot rootfs actif (utile pour le rollback)
sudo nvbootctrl dump-slots-info
```

**Consigner** la sortie de `cat /etc/nv_tegra_release` et l'empreinte de l'image
dans le dossier de recette, pour chaque boîtier.

---

## Après le flash

1. Dépendances système GStreamer : [install-system-deps.md](install-system-deps.md).
2. Accès maintenance (VNC chiffré) + IHM HTTPS : [scripts-deploiement.md](scripts-deploiement.md).
3. Déploiement de l'image applicative : `scripts/deploy-jetson.sh` (mise au point)
   ou chargement hors ligne (`docker load`) en RUN — voir
   [scripts-deploiement.md](scripts-deploiement.md).
4. **Canal de mise à jour L4T hors ligne + rollback** :
   [maj-l4t-hors-ligne.md](maj-l4t-hors-ligne.md) (`CS-1141-02`, `CS-123-03`).

---

## Références

- [Wiki Seeed — reServer Industrial Getting Started](https://wiki.seeedstudio.com/reServer_Industrial_Getting_Started/)
- [Wiki Seeed — Hardware Interface Usage](https://wiki.seeedstudio.com/reserver_industrial_hardware_interface_usage/)
- [Datasheet reServer Industrial (PDF)](https://files.seeedstudio.com/wiki/reServer-Industrial/reServer-Industrial-Datasheet.pdf)
- [NVIDIA Jetson Linux (L4T) — Release Notes](https://developer.nvidia.com/embedded/jetson-linux)
- [NVIDIA Jetson — Security Bulletins](https://docs.nvidia.com/jetson/archives/security-bulletins/)
