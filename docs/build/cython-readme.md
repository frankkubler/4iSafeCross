# Protection du code avec Cython

## Vue d'ensemble

Le code Python est compilé en **binaires natifs ARM64** avec Cython, rendant le code source inaccessible.

## Comment ça fonctionne

```
Python (.py) → Cython → C code → GCC → Binary (.so)
```

### Exemple

**Avant (app.py)** :
```python
def process_data(data):
    return [x * 2 for x in data]
```

**Après compilation** :
- `src/handlers/camera.so` (binaire ARM64)
- Pas de fichiers .py dans l'image finale
- Code source irrécupérable

## Configuration

### setup_cython.py

Configure la compilation de tous les fichiers dans `src/` et `utils/` :

```python
SOURCE_DIRS = ["src", "utils"]  # Directories a compiler
```

### Options de compilation

```python
compiler_directives={
    'boundscheck': False,      # +10% performance
    'wraparound': False,       # +5% performance
    'cdivision': True,         # Division C (plus rapide)
}
```

## Build local (test)

```bash
# Installer Cython
pip install cython

# Compiler
python setup_cython.py build_ext --inplace

# Verifier les .so generes
ls src/**/*.so
# src/handlers/camera.cpython-310-aarch64-linux-gnu.so

# Tester
python app.py
```

## Sécurité

### ✅ Ce que Cython protège
- Code source inaccessible (binaire natif)
- Décompilation quasi-impossible
- Même protection que du C compilé
- Pas de bytecode Python

### ⚠️ Ce que Cython ne protège PAS
- Debugging runtime (mais très difficile)
- Strings hardcodées visibles avec `strings`
- Analyse dynamique avancée

### 🔒 Protection complète recommandée
1. **Cython** : Code compilé en binaire
2. **Docker privé** : Registry avec authentification
3. **Image signée** : Détection de modification
4. **Variables d'env** : Config sensible hors de l'image

## Performance

### Gains typiques

| Type de code | Gain performance |
|--------------|------------------|
| **I/O bound** (Flask, API) | 0-5% |
| **Boucles Python** | 10-30% |
| **Calculs intensifs** | 50-500% |

### Votre application (Flask + Aiogram)

Gain attendu : **~5-10%** (principalement I/O)

## Comparaison avec Nuitka

| Critère | Cython | Nuitka |
|---------|--------|--------|
| **Protection** | 🔒🔒🔒🔒 Binaire .so | 🔒🔒🔒🔒🔒 Binaire ELF |
| **Build time** | ~5 min | ~2-3h |
| **Performance** | 100-110% | 100-110% |
| **Taille** | Plus petit | Plus gros |
| **Complexité** | Simple | Simple |

## Extraction du binaire

Un attaquant avec accès au Jetson peut extraire les .so :

```bash
docker save 4isafecross > image.tar
tar -xf image.tar
# Trouve les .so mais pas le code Python source
```

**Mais** : Les .so sont des binaires compilés, impossible de retrouver le code Python original.

## Fichiers protégés

Le script compile automatiquement :
- ✅ `src/**/*.py` → `src/**/*.so`
- ✅ `utils/**/*.py` → `utils/**/*.so`
- ⚠️ `app.py` : Point d'entrée (peut être compilé aussi si besoin)
- ❌ `config/` : Fichiers de config (non compilés)

## Désactiver la compilation (debug)

Dans le Dockerfile, commenter la ligne de compilation :

```dockerfile
# RUN python3 setup_cython.py build_ext --inplace
```

Le code Python restera en clair (pour développement).

## Documentation officielle

- Cython : https://cython.readthedocs.io/
- Performance tips : https://cython.readthedocs.io/en/latest/src/userguide/numpy_tutorial.html
