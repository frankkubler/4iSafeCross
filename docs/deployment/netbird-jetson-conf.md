<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# peux-tu écrire un md pour que je puisse me rappeler cela le services retenu et les alias

```markdown
# NetBird ACL Fix — 4isafecross (Jetson ARM64)

## Contexte

- **Machine** : `4isafecross` (Jetson, kernel `5.15.148-tegra`, ARM64)
- **Problème** : NetBird fonctionne en mode `Userspace` (WireGuard kernel non disponible sur Tegra).
  En mode Userspace, la chaîne `NETBIRD-ACL-INPUT` est vidée à chaque `netbird down/up`,
  bloquant les connexions entrantes malgré une policy correcte dans le dashboard.
- **Objectif** : Autoriser uniquement `4itec012` (100.124.169.202) à accéder à `4isafecross` (100.124.134.187).

---

## Dashboard NetBird

| Groupe         | Peer       | IP               |
|----------------|------------|------------------|
| grp-4itec012   | 4itec012   | 100.124.169.202  |
| grp-4isafecross| 4isafecross| 100.124.134.187  |

**Policy** : `safecross-restricted`
- Source : `grp-4itec012`
- Direction : ↔ bidirectionnel
- Destination : `grp-4isafecross`
- Protocol : ALL / Ports : ALL

---

## Service systemd retenu

Fichier : `/etc/systemd/system/netbird-acl-fix.service`

```ini
[Unit]
Description=NetBird ACL fix - allow 4itec012
After=netbird.service
Requires=netbird.service

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 5
ExecStart=/sbin/iptables -I NETBIRD-ACL-INPUT -s 100.124.169.202 -j ACCEPT
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```


### Commandes d'installation

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now netbird-acl-fix.service
```


### Vérification

```bash
sudo systemctl status netbird-acl-fix.service
sudo iptables -L NETBIRD-ACL-INPUT -n -v
# Doit afficher : ACCEPT  all  --  100.124.169.202  0.0.0.0/0
```


---

## Alias (~/.bashrc)

```bash
alias netbird-up="sudo netbird up && sleep 6 && sudo systemctl restart netbird-acl-fix.service"
alias netbird-down="sudo netbird down"
```

```bash
source ~/.bashrc
```


### Usage

```bash
netbird-down   # Déconnecte NetBird proprement
netbird-up     # Reconnecte NetBird + réinjecte la règle ACL automatiquement
```


---

## Comportement

| Événement | ACL réinjectée automatiquement ? |
| :-- | :-- |
| Reboot machine | ✅ (via systemd au boot) |
| `netbird-down/up` | ✅ (via alias) |
| `sudo netbird down/up` | ❌ relancer manuellement : |

```bash
sudo systemctl restart netbird-acl-fix.service
```

```
```

