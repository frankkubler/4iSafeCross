# Mise à jour L4T / JetPack hors ligne + rollback

> **Exigences couvertes** : `CS-1141-02` (procédure et outils de mise à jour du
> firmware/OS livrés pour la phase RUN), `CS-123-03` (équivalent du correctif
> mensuel sur l'OS dérogé), rattachées à `CS-1141-01` (version homologuée et
> identique sur tout le parc). Voir `CYBER_AUDIT.md`.

---

## 1. Contexte

Le boîtier fonctionne **autonome, sans connexion Internet** en exploitation
(`docs/deployment/scripts-deploiement.md`). Il n'a donc **aucun accès direct** aux
dépôts Ubuntu ou NVIDIA. Toute mise à jour du système d'exploitation, du BSP L4T
ou du firmware :

- se fait par **intervention physique** sur site (câble RJ45 point-à-point `eth2`,
  session VNC chiffrée) et **support amovible** ;
- utilise une **machine relais** 4itec connectée, pendant une fenêtre de
  connectivité **déclarée au Plant IT Leader** (même formalisme que la fenêtre 4G
  de mise au point, cf. `CS-145-xx`) ;
- est **consignée** au dossier de recette (date, paquets, empreintes, opérateur,
  résultat, rollback éventuel).

**La cible RUN ne télécharge jamais rien elle-même.** Le `.gitlab-ci.yml` et le
`Dockerfile` (dépôts `repo.download.nvidia.com`, `archive.ubuntu.com`) ne servent
qu'à **construire** l'image sur l'infrastructure 4itec ; ils ne sont pas utilisés
sur le boîtier.

---

## 2. Les trois couches à maintenir

| Couche | Contenu | Origine (build 4itec) | Mécanisme de MAJ sur cible |
|---|---|---|---|
| **A — Firmware / bootloader** | UEFI (TegraBoot), device tree, QSPI | BSP NVIDIA Jetson Linux r39.2 | Capsule UEFI A/B (`fwupd`) **ou** reflash QSPI en Force Recovery |
| **B — L4T + rootfs** | Kernel L4T, `nvidia-l4t-*`, CUDA 13.2 / cuDNN / TensorRT, Ubuntu 24.04 | `repo.download.nvidia.com/jetson/{common,som} r39.2` + `ports.ubuntu.com` (`noble`, `noble-security`, arm64) | apt hors ligne (dépôt local sur support amovible) **ou** reflash du slot rootfs |
| **C — Image applicative** | Conteneur `4isafecross:*-arm64` | Registry GitLab 4itec | `docker load` d'un `.tar` (déjà couvert — voir §6) |

`config/` et `db/` sont sur bind-mount `/data/4isafecross` : **préservés** par
toute MAJ de la couche C, et non touchés par A/B.

---

## 3. Version homologuée et identité du parc (`CS-1141-01`)

- Version cible unique : **JetPack 7.2 / L4T r39.2 / Ubuntu 24.04**.
- Chaque boîtier d'une même référence est flashé avec **la même image**
  (même empreinte `sha256`) — voir
  [flash-jetson-reserver-j4012-jetpack72.md](flash-jetson-reserver-j4012-jetpack72.md).
- L'image de flash d'origine et son empreinte sont **archivées par 4itec** : elles
  servent de référence de rollback et de provisioning d'un boîtier de rechange.
- Toute montée de version (7.2 → ultérieure) est **réhomologuée** par le référent
  technique avant application sur le parc, et appliquée à **tous** les boîtiers de
  la référence pour préserver l'identité `§1.1.4.1`.

---

## 4. Canal de mise à jour de sécurité (`CS-123-03`)

### 4.1 Sources et support

| Source | Suite / dépôt | Clé | Support |
|---|---|---|---|
| Ubuntu 24.04 LTS (arm64) | `noble`, `noble-updates`, `noble-security` sur `ports.ubuntu.com` | trousseau `ubuntu-keyring` | Maintenance standard jusqu'en **04/2029** ; ESM/Pro jusqu'en **2034** |
| NVIDIA L4T BSP | `jetson/common` + `jetson/som`, suite `r39.2` | `jetson-ota-public.asc` (`repo.download.nvidia.com`) | Suivi via **NVIDIA Jetson Security Bulletins** |
| CUDA / cuDNN / TensorRT | inclus dans le BSP / méta-paquet `nvidia-jetpack` | idem BSP | idem BSP |

### 4.2 Veille (équivalent du correctif mensuel)

- **Revue trimestrielle** (a minima) des bulletins :
  - NVIDIA Jetson : <https://docs.nvidia.com/jetson/archives/security-bulletins/>
  - Ubuntu Security Notices (USN) filtrés `noble` / arm64 : <https://ubuntu.com/security/notices>
- Pour chaque avis **applicable** (paquet réellement présent, vecteur réellement
  exposé compte tenu de l'air-gap), classer **Critique / Élevé / Moyen / Faible**.
- Les correctifs **Critique / Élevé applicables** sont appliqués lors de la
  **prochaine intervention planifiée** (fenêtre bornée), ou d'une intervention
  dédiée si la criticité l'exige.
- Les correctifs **Moyen / Faible** sont regroupés et appliqués à cadence
  trimestrielle.
- La revue et les décisions sont **tracées** (registre des MAJ, §7).

> L'air-gap réduit fortement l'exploitabilité des paquets réseau (ex. pile TCP,
> clients HTTP) mais **pas** celle des composants sur le chemin de démarrage /
> vérification de licence, ni des failles à accès local (le segment maintenance
> `eth2` est un vecteur). Ne pas se dispenser des correctifs sur cette base.

---

## 5. Procédure — mise à jour L4T / rootfs hors ligne (couche B)

### 5.1 Préparation (machine relais connectée, fenêtre déclarée)

1. **Cloner l'état des paquets** du boîtier : récupérer `dpkg -l` et
   `/etc/apt/sources.list*` du boîtier cible (via VNC / `scp` sur `eth2`).
2. Sur une machine **arm64** (ou un conteneur `--platform linux/arm64`) alignée
   sur la même version, préparer les `.deb` :

   ```bash
   # Dépôts identiques à ceux du boîtier
   #   deb https://ports.ubuntu.com/ubuntu-ports noble-security main universe
   #   deb https://repo.download.nvidia.com/jetson/common r39.2 main
   #   deb https://repo.download.nvidia.com/jetson/som    r39.2 main
   sudo apt-get update

   # Option A — cible un bulletin précis : lister les paquets concernés
   sudo apt-get install --download-only --reinstall \
        -o Dir::Cache::archives="$PWD/maj-l4t" \
        <paquet1> <paquet2> ...

   # Option B — tous les correctifs de sécurité disponibles
   sudo apt-get install --download-only \
        -o Dir::Cache::archives="$PWD/maj-l4t" \
        $(apt-get -s dist-upgrade | awk '/^Inst/ {print $2}')
   ```

3. Générer un **index de dépôt local** et l'empreinte de l'ensemble :

   ```bash
   cd maj-l4t
   dpkg-scanpackages . /dev/null | gzip -9c > Packages.gz
   sha256sum *.deb Packages.gz > SHA256SUMS
   ```

4. Copier `maj-l4t/` sur un **support amovible chiffré** (LUKS). Y joindre le
   bulletin de sécurité de référence et la liste des paquets.

### 5.2 Application (sur le boîtier, via VNC `eth2`)

```bash
# 1. Sauvegarde préalable — voir §6
# 2. Monter le support et vérifier les empreintes
cd /media/<support>/maj-l4t
sha256sum -c SHA256SUMS            # doit être 100 % OK

# 3. Déclarer un dépôt local TEMPORAIRE (signé par les clés déjà présentes)
echo "deb [trusted=no] file:/media/<support>/maj-l4t ./" \
  | sudo tee /etc/apt/sources.list.d/zz-maj-l4t-local.list
sudo apt-get update

# 4. Appliquer UNIQUEMENT les paquets voulus (jamais un dist-upgrade aveugle)
sudo apt-get install --only-upgrade <paquet1> <paquet2> ...

# 5. RETIRER le dépôt local
sudo rm /etc/apt/sources.list.d/zz-maj-l4t-local.list
sudo apt-get update
```

> Ne **jamais** utiliser `[trusted=yes]` ni `--allow-unauthenticated` : les
> paquets Ubuntu et NVIDIA restent signés par leurs clés d'origine, déjà
> présentes dans le trousseau du boîtier. `[trusted=no]` force la vérification.

### 5.3 Contrôles post-MAJ

```bash
cat /etc/nv_tegra_release        # version L4T inchangée (r39.2) sauf montée de version homologuée
uname -r                         # kernel attendu
sudo systemctl restart 4isafecross   # ou: docker compose -f docker-compose-arm64.yml up -d
curl -k https://127.0.0.1/health          # IHM : 200
curl http://127.0.0.1:5050/failsafe_status  # relais fail-safe : état attendu
```

Vérifier une acquisition caméra réelle (décodage NVDEC via `nvv4l2decoder`) et un
cycle d'alerte relais avant de refermer l'intervention.

---

## 6. Rollback

Choisir le niveau selon ce qui a été modifié. **Toujours** faire la sauvegarde
préalable AVANT la MAJ.

### 6.1 Couche C — image applicative (le plus fréquent)

```bash
# L'ancienne image a été conservée en .tar sur support amovible
docker load -i /media/<support>/4isafecross_<ancien_tag>-arm64.tar
docker stop 4isafecross && docker rm 4isafecross
# relancer avec l'ancien tag (docker-compose-arm64.yml ou scripts/deploy-jetson.sh)
```

`config/` et `db/` (`/data/4isafecross`) sont préservés — aucune perte d'état.

### 6.2 Couche B — rootfs / L4T

- **MAJ apt in-place** (§5) : rollback paquet par paquet en réinstallant les
  `.deb` de la version précédente (les conserver dans la sauvegarde §6.4) :

  ```bash
  sudo apt-get install --allow-downgrades ./<paquet>_<ancienne_version>_arm64.deb
  ```

- **Rollback fiable** si l'état apt est incohérent : **reflasher le slot rootfs**
  depuis l'image d'origine archivée (empreinte figée, §3), en Force Recovery
  (`l4t_initrd_flash.sh`, voir doc de flash). L'état applicatif est ré-amorcé
  depuis `/data/4isafecross` conservé.

### 6.3 Couche A — firmware / bootloader (A/B)

JetPack 7.x provisionne des **slots A/B** pour le rootfs et le bootloader, avec
**rollback protection** : un boot qui échoue `N` fois repart automatiquement sur
le slot précédent.

```bash
# État des slots
sudo nvbootctrl dump-slots-info

# Forcer le retour sur l'autre slot puis redémarrer
sudo nvbootctrl set-active-boot-slot <0|1>
sudo reboot
```

> Les commandes exactes de gestion de capsule UEFI / QSPI sur le BSP r39.2 sont à
> **valider sur cible** avec le référent lors de l'homologation (elles varient
> entre `nvbootctrl`, `fwupdmgr` et les scripts `l4t-bootloader-config`).

### 6.4 Sauvegarde préalable (obligatoire avant toute MAJ B/A)

```bash
# Inventaire des paquets + versions (permet le downgrade ciblé)
dpkg -l > /media/<support>/backup/dpkg-l_$(date +%F).txt
cp -a /etc/apt /media/<support>/backup/etc-apt_$(date +%F)

# .deb des paquets qui vont être mis à jour (pour downgrade)
#   -> les copier depuis /var/cache/apt/archives AVANT le apt-get install

# Image applicative courante
docker save 4isafecross:<tag_courant>-arm64 \
  -o /media/<support>/backup/4isafecross_<tag_courant>-arm64.tar

# (Optionnel, si volume suffisant) image disque complète du boîtier de référence,
# conservée par 4itec — sert aussi au provisioning d'un boîtier de rechange.
```

---

## 7. Registre des mises à jour (traçabilité — `CS-123-03`, `CS-R2-04`)

Une ligne par intervention, sur support amovible + dossier de recette :

| Date | Boîtier (n° série / site) | Couche | Paquets / image (avant → après) | Bulletin réf. | Empreintes avant/après | Opérateur | Résultat | Rollback |
|---|---|---|---|---|---|---|---|---|
| | | A/B/C | | NVIDIA / USN | sha256 | | OK / KO | oui/non + niveau |

---

## 8. Références

- [flash-jetson-reserver-j4012-jetpack72.md](flash-jetson-reserver-j4012-jetpack72.md) — flash initial, tableau d'homologation
- [scripts-deploiement.md](scripts-deploiement.md) — services, VNC chiffré, IHM HTTPS, `deploy-jetson.sh`
- [NVIDIA Jetson — Security Bulletins](https://docs.nvidia.com/jetson/archives/security-bulletins/)
- [Ubuntu Security Notices](https://ubuntu.com/security/notices)
- [NVIDIA Jetson Linux (L4T)](https://developer.nvidia.com/embedded/jetson-linux)
