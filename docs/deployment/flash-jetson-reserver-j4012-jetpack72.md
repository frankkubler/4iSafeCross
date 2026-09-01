# Flash JetPack 6.2 sur reServer Industrial J4012

> **Source** : [wiki.seeedstudio.com/reServer_Industrial_Getting_Started](https://wiki.seeedstudio.com/reServer_Industrial_Getting_Started/)  
> **Matériel cible** : reServer Industrial J4012 (Jetson Orin NX 16 GB)  
> **JetPack** : 6.2 — L4T **36.4.3**

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
| PC hôte Ubuntu | Ubuntu 20.04 ou 22.04 (natif ou VMware — **pas WSL**) |
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

## Étape 1 — Télécharger l'image système

Rendez-vous sur la page wiki Seeed Studio et téléchargez l'image correspondant
au J4012 / JetPack 6.2 :

| Carte | JetPack | L4T | Lien |
|---|---|---|---|
| reServer Industrial J4012 | **6.2** | **36.4.3** | [Download — wiki Seeed](https://wiki.seeedstudio.com/reServer_Industrial_Getting_Started/#different-methods-of-flashing) |

> L'archive (méthode 1 — image complète) pèse environ **14 Go** et contient
> JetPack, CUDA, cuDNN, TensorRT et tous les pilotes périphériques Seeed.  
> La méthode 2 (L4T officiel NVIDIA + pilotes séparés) pèse ~3 Go.

Extraire l'archive :

```bash
tar -xvf <nom_du_fichier>.tar.gz
```

Le dossier extrait s'appellera `mfi_reserver-orin-industrial/`.

---

## Étape 2 — Passer en mode Force Recovery

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
cd mfi_reserver-orin-industrial

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

![Sortie console indiquant un flash réussi](https://files.seeedstudio.com/wiki/reComputer-Industrial/99.png)

> ⚠️ Ne pas débrancher ni éteindre le board pendant le flash.

---

## Étape 4 — Configuration initiale

1. Connecter un écran via le port **HDMI** du reServer.
2. Le board redémarre automatiquement après le flash.
3. Suivre l'assistant de configuration Ubuntu (langue, utilisateur, réseau…).

   ![Assistant de configuration Ubuntu — étape 1](https://files.seeedstudio.com/wiki/reComputer-Industrial/104.png)

   ![Assistant de configuration Ubuntu — étape 2](https://files.seeedstudio.com/wiki/reComputer-Industrial/105.png)

4. Après la configuration, le système est opérationnel sous JetPack 6.2.

   ![Système prêt à l'emploi sous JetPack 6.2](https://files.seeedstudio.com/wiki/reComputer-Industrial/106.png)

---

## Vérification post-flash

```bash
# Vérifier la version L4T
cat /etc/nv_tegra_release
# Attendu : R36 (release), REVISION: 4.3

# Vérifier JetPack
dpkg -l | grep jetpack

# Vérifier CUDA
nvcc --version
# Attendu : CUDA 12.x (fourni avec JetPack 6.2)
```

---

## Références

- [Wiki Seeed — reServer Industrial Getting Started](https://wiki.seeedstudio.com/reServer_Industrial_Getting_Started/)
- [Wiki Seeed — Hardware Interface Usage](https://wiki.seeedstudio.com/reserver_industrial_hardware_interface_usage/)
- [Datasheet reServer Industrial (PDF)](https://files.seeedstudio.com/wiki/reServer-Industrial/reServer-Industrial-Datasheet.pdf)
- [NVIDIA L4T 36.4.3 Release Notes](https://developer.nvidia.com/embedded/jetson-linux)
