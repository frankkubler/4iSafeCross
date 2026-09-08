# 4isafecross — Accès distant du reServer J4012

Procédure de mise en place du lien réseau et des accès distants entre le PC de bureau et le Jetson Orin NX, pour la mise en service puis la maintenance.

## Contexte

| | PC de bureau | reServer J4012 |
|---|---|---|
| Hôte | `4itec012` | `4isafecross-2` |
| Système | Ubuntu 26.04 LTS | Ubuntu 24.04 — JetPack 7.2 / L4T 39.2 |
| Utilisateur | `frank-kubler` | `user-4itec` |
| Interface du lien | port Ethernet libre | `enP7p5s0` (eth1) |
| Adresse | `192.168.3.100/24` | `192.168.3.122/24` |

Le Jetson est destiné à fonctionner **sans écran ni clavier**. Il n'a pas d'accès Internet propre : il sort par le Wi-Fi du PC de bureau, qui fait passerelle.

Deux voies d'accès distant coexistent, sur **la même session graphique** :

- **RustDesk** pendant la mise en service, via clé 4G — traverse le CGNAT sans port entrant.
- **TigerVNC en tunnel SSH** en maintenance, quand la machine est joignable sur le réseau local.

---

## 1. Liaison Ethernet directe et partage de connexion

Câble Ethernet droit entre les deux machines. Pas besoin de câble croisé, l'auto-MDI/X s'en charge.

### Côté PC — partage de la connexion Wi-Fi

Le panneau Réseau de GNOME masque les champs d'adresse dès qu'on choisit le mode partagé. Il faut passer par l'éditeur complet :

```bash
sudo apt install network-manager-gnome
nm-connection-editor
```

Sur la connexion filaire :

- Onglet **Ethernet** → *Périphérique* : le port relié au Jetson.
- Onglet **Paramètres IPv4** → *Méthode* : **Partagé avec d'autres ordinateurs**.
- **Ajouter** dans le tableau d'adresses : `192.168.3.100` / `255.255.255.0`, passerelle vide.
- Onglet **Paramètres IPv6** → *Méthode* : **Désactivé**.

Le mode partagé monte automatiquement le masquerading et un dnsmasq (DHCP + relais DNS) sur l'interface. Rien d'autre à configurer.

> **Vérifier que le Wi-Fi n'est pas lui aussi en 192.168.3.0/24** (`ip -4 addr show`), sinon le routage part en vrille.

> **Si ufw est actif** : sa politique FORWARD par défaut est DROP et bloque le NAT. Mettre `DEFAULT_FORWARD_POLICY="ACCEPT"` dans `/etc/default/ufw` puis `sudo ufw reload`.

### Côté Jetson — adresse fixe

Configuré avec le panneau Réseau GNOME standard, sans outil supplémentaire :

| Champ | Valeur |
|---|---|
| Méthode IPv4 | Manuel |
| Adresse | `192.168.3.122` |
| Masque | `255.255.255.0` |
| Passerelle | `192.168.3.100` |
| DNS | `192.168.3.100` *(le dnsmasq du PC fait relais)* |
| IPv6 | Désactivé |

### Vérification

```bash
# depuis le Jetson
ip route                      # default via 192.168.3.100
ping -c3 192.168.3.100        # lien physique
ping -c3 1.1.1.1              # routage + NAT
ping -c3 gitlab.4itec.fr      # résolution DNS
```

Un `iperf3` confirme au passage qu'on est bien à 1 Gb/s — utile pour les poids de modèles et les images Docker.

### Réglage complémentaire

Le champ *métrique* n'existe pas dans l'interface graphique. Si eth0 du Jetson est un jour rebranché sur le réseau de l'atelier, deux routes par défaut entreront en concurrence :

```bash
sudo nmcli con mod <nom-connexion> ipv4.route-metric 200
```

---

## 2. TigerVNC + XFCE

### Pourquoi pas GNOME

`gnome-session` refuse de démarrer dans un Xvnc sur Jetson, pour deux raisons cumulées : une seule `graphical-session.target` par utilisateur (conflit avec la session locale), et `gnome-shell` qui exige un rendu GL accéléré, sans repli logiciel utilisable dans la pile NVIDIA. Symptôme dans `~/.vnc/<hôte>:<n>.log` :

```
Session startup via '/etc/X11/Xtigervnc-session' ... cleanly exited too early (< 3 seconds)!
```

XFCE se contente du rendu logiciel et ne se bat pas avec systemd --user.

### Pourquoi pas x11vnc

x11vnc reflète l'écran physique. Sans moniteur branché, GDM démarre sans EDID et se retrouve sans mode d'affichage valide. Le bureau virtuel Xvnc est l'architecture correcte pour une machine sans tête.

### Installation

```bash
sudo apt install tigervnc-standalone-server tigervnc-common xfce4 xfce4-terminal
vncpasswd    # SANS sudo — le fichier doit atterrir dans ~user-4itec/.vnc/passwd
```

### Configuration

`~/.vnc/config` :

```
geometry=1920x1080
depth=24
localhost=yes
```

`localhost=yes` est le point de sécurité central : Xvnc n'écoute que sur `127.0.0.1`, rien n'est joignable depuis le réseau. **Ne pas déclarer de `session=`** — c'est `xstartup` qui prend le relais.

`~/.vnc/xstartup` :

```sh
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4
```

```bash
chmod +x ~/.vnc/xstartup
```

### Démarrage automatique

```bash
echo ':2=user-4itec' | sudo tee -a /etc/tigervnc/vncserver.users
sudo systemctl enable --now tigervncserver@:2
sudo systemctl set-default multi-user.target
```

L'unité s'appelle **`tigervncserver@`** sur Debian/Ubuntu — `vncserver@` est le nom Fedora/RHEL et n'existe pas ici.

Passer en `multi-user.target` supprime GDM : sur un Orin NX dédié à l'inférence, une session GNOME qui tourne pour personne consomme RAM et GPU pour rien. CUDA, TensorRT et les caméras n'ont jamais eu besoin de X.

### Vérification

```bash
ss -ltnp | grep 5902     # doit montrer 127.0.0.1:5902 UNIQUEMENT
```

En cas d'échec, le message utile n'est pas dans `journalctl` mais dans `~/.vnc/<hôte>:2.log`. Pour tester la chaîne X seule, hors environnement de bureau :

```bash
tigervncserver -kill :2
tigervncserver -xstartup /usr/bin/xterm :2
```

---

## 3. RustDesk

GDM n'est pas nécessaire : RustDesk capture un serveur X, et le Xvnc en fournit un. On reste donc en `multi-user.target`.

### Serveur de rendez-vous

Le serveur public par défaut est à éviter pour un contexte Stellantis. Héberger `hbbs`/`hbbr` en Docker sur le homelab et renseigner *ID Server* + *Key* dans les paramètres réseau du client. Le chiffrement est de bout en bout par paire de clés — le relais ne voit passer que du chiffré.

### Raccordement à la session XFCE

**Rien à faire.** L'installation du binaire suffit : le paquet pose son unité systemd, et RustDesk s'accroche directement à la session XFCE de Xvnc. Aucun override, aucune variable `DISPLAY` à déclarer.

Cela fonctionne parce que le `:2` est le **seul** serveur X de la machine une fois GDM retiré. Si une session locale devait un jour réapparaître sur `:1`, il faudrait alors désigner explicitement le display à capturer via un `/etc/systemd/system/rustdesk.service.d/override.conf` portant `Environment=DISPLAY=:2`.

Seul point à valider : que RustDesk retrouve bien le display **après un redémarrage complet**, personne n'étant connecté. Si le service part avant `tigervncserver@:2`, ajouter dans un override :

```
[Unit]
After=tigervncserver@:2.service
```

### Accès permanent

```bash
rustdesk --password <motdepasse>
```

Mot de passe fixe et non code à usage unique : sans écran, personne ne pourra lire le code.

### Réglages XFCE pour le distant

Paramètres → *Peaufinage des fenêtres* → décocher le compositeur.
Paramètres → *Économiseur d'écran* → désactiver le verrouillage.

Sur une machine sans clavier physique, un écran verrouillé est un piège.

### Consommation 4G

Une session 1080p, c'est plusieurs centaines de Mo par heure. Baisser la qualité dans le client et supprimer le fond d'écran.

---

## 4. Accès depuis le PC de bureau

`~/.ssh/config` :

```
Host j4012
    HostName 192.168.3.122
    User user-4itec
    IdentityFile ~/.ssh/<clé>
    IdentitiesOnly yes
    LocalForward 5902 localhost:5902
    LocalForward 8080 localhost:8080
```

Ouvrir le tunnel, puis le viewer dans un second terminal :

```bash
ssh -N j4012
xtigervncviewer -PreferredEncoding=Tight -CompressLevel=6 localhost:5902
```

Le mot de passe demandé est celui de `vncpasswd`, pas celui du compte Unix.

Le forward `8080` rapatrie l'interface web de 4isafecross sur `http://localhost:8080` — à consulter depuis le navigateur du PC plutôt que depuis un navigateur installé sur le Jetson. L'interface est fluide au lieu de ramer sur llvmpipe, on n'occupe pas 1,5 Go des 16 du Orin, et un flux vidéo annoté transite en MJPEG compressé plutôt qu'en pixels VNC réencodés — un ordre de grandeur d'écart sur la bande passante, déterminant derrière une clé 4G.

---

## Pièges rencontrés

| Symptôme | Cause | Correctif |
|---|---|---|
| `vncserver@:1.service does not exist` | Nom d'unité Fedora/RHEL | `tigervncserver@:2` |
| Service actif 204 ms puis « Deactivated » | GNOME refuse de démarrer dans Xvnc | XFCE via `xstartup` |
| `A X11 server is already running for display :1` | Session GDM locale occupant `:1` | Utiliser `:2`, puis `multi-user.target` |
| `Too many authentication failures` | L'agent SSH propose toutes les clés, le serveur coupe à la 6ᵉ | `IdentitiesOnly yes` dans `~/.ssh/config` |
| `~/.Xauthority does not exist` | Cookie géré par GDM dans `/run/user/1000/` | Sans objet une fois GDM retiré |
| Avertissements `xkbcomp` en masse | Keysyms inconnus du clavier | Bruit sans conséquence, à ignorer |

---

## Points ouverts

**Durcissement SSH avant livraison** — `PasswordAuthentication no`, authentification par clé uniquement, `AllowUsers user-4itec`. Déposer la clé publique dans `~/.ssh/authorized_keys` **tant que le clavier physique est encore branché**.

**Conserver RustDesk après la mise en service**, service désactivé (`systemctl disable rustdesk`) mais installé : c'est le seul recours si le VLAN change ou si SSH est filtré. Réactivable à distance tant que SSH répond.

**Alternative NetBird** — l'agent traverse le CGNAT de la 4G comme le réseau de l'atelier, en WireGuard chiffré, et permet un `ssh -N j4012` sur l'IP mesh quel que soit le point de branchement. Supprimerait le besoin de maintenir deux dispositifs en parallèle, sous réserve que le réseau Stellantis laisse sortir le trafic vers le coordinateur.

**Affichage vidéo en production** — ne pas passer par X. Servir les images annotées en MJPEG ou WebRTC sur un port HTTP et consulter depuis le navigateur du PC : plus fluide, traverse le tunnel SSH sans problème, affranchit complètement de la question du bureau distant.
