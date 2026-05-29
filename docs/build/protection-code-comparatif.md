# Protection du code source — Comparatif Cython / Nuitka

## Contexte

L'application 4iSafeCross est déployée sur un Jetson Orin NX chez le client sous forme d'image Docker.
L'objectif est d'empêcher la lecture et la copie du code source (propriété intellectuelle) tout en maintenant
un pipeline CI/CD rapide et fiable.

## Méthode retenue : Cython avec `-OO`

Tous les fichiers `.py` de `src/` et `utils/` sont compilés en binaires natifs ARM64 (`.so`) via Cython.
Le flag `-OO` supprime les docstrings des binaires produits.

```dockerfile
RUN python3 -OO setup_cython.py build_ext --inplace
```

Les fichiers `.py` sources sont supprimés après compilation — seuls les `.so` sont présents dans l'image finale.

## Ce que `-OO` apporte

| Sans `-OO` | Avec `-OO` |
|---|---|
| Docstrings visibles via `strings` | Docstrings absentes du binaire |
| Fichier légèrement plus grand | Fichier légèrement plus petit |
| `help(fonction)` retourne la doc | `help(fonction)` retourne rien |

**Dans le contexte production sur Jetson**, les docstrings ne servent à personne sur la machine cible.
L'avantage est réel, l'inconvénient est nul.

## Tableau comparatif

| Critère | Cython `-OO` *(config actuelle)* | Nuitka free | Nuitka Commercial |
|---|---|---|---|
| **Code lisible** | ❌ non | ❌ non | ❌ non |
| **Décompilable** | ❌ non | ❌ non | ❌ non |
| **Noms de fonctions** (`strings`) | ⚠️ visibles | ⚠️ partiellement | ✅ masqués |
| **Docstrings** | ✅ supprimées (`-OO`) | ✅ supprimées | ✅ supprimées |
| **String literals** | ⚠️ visibles | ⚠️ visibles | ✅ chiffrées |
| **Logique algorithmique** | ✅ protégée | ✅ protégée | ✅ protégée |
| **Temps de build (QEMU x86→ARM64)** | ~2 min | ~30–60 min | ~30–60 min |
| **Temps de build (natif Jetson)** | ~30 s | ~5–8 min | ~5–8 min |
| **Compatibilité Python 3.10** | ⚠️ parser limité | ✅ native | ✅ native |
| **Taille des binaires** | normale | +20–50% | +20–50% |
| **Prix** | gratuit | gratuit | 250€/an |
| **Complexité Docker** | faible | élevée | élevée |

## Détail des critères

### Noms de fonctions visibles
La commande `strings fichier.so` permet d'extraire les chaînes de caractères d'un binaire.
Avec Cython, les noms de fonctions et de classes restent présents en tant que symboles C.
Nuitka free les réduit partiellement. Nuitka Commercial les masque complètement.

### String literals
Les chaînes hardcodées dans le code (URLs, messages, noms de clés) restent visibles dans
les binaires Cython et Nuitka free. Nuitka Commercial les chiffre — pertinent uniquement
si des secrets sont hardcodés dans le code.

### Logique algorithmique
Dans les trois cas, la logique du code (algorithmes, conditions, boucles) est compilée en
code machine ARM64 non lisible et non décompilable. C'est la protection essentielle.

### Compatibilité Python 3.10
Cython utilise son propre parser C qui ne supporte pas toutes les syntaxes Python 3.10+
(ex: unions PEP 604 `X | None`). Nuitka utilise l'AST Python natif — aucune limitation syntaxique.

### Compilation native sur Jetson vs QEMU

Les temps de build indiqués avec QEMU supposent une compilation croisée x86→ARM64 via émulation.
Si un GitLab Runner est installé directement sur le Jetson (executor `shell`), la compilation est native :
les temps tombent à ~30 s pour Cython et ~5–8 min pour Nuitka — sans QEMU, sans Docker.

```bash
# Installer un Runner sur le Jetson
curl -L "https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-linux-arm64" \
    -o /usr/local/bin/gitlab-runner
chmod +x /usr/local/bin/gitlab-runner
gitlab-runner register --executor shell --tag-list arm64,jetson
```

Dans `.gitlab-ci.yml`, cibler ce runner avec `tags: [jetson]`.

## Conclusion

**Cython `-OO` est le bon choix pour 4iSafeCross.**

La logique métier (détection, zones de sécurité, algorithmes) est entièrement protégée.
Nuitka Commercial n'apporterait qu'un chiffrement des string literals — utile uniquement
si des secrets (clés API, mots de passe) sont hardcodés dans le code source, ce qui
doit être évité de toute façon (utiliser des variables d'environnement).
