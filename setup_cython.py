"""
Setup script pour compiler le code Python en binaires avec Cython
Compile tous les fichiers .py en modules .so (binaires ARM64)
"""

from setuptools import setup, Extension
from Cython.Build import cythonize
import os
from pathlib import Path

# Directories a compiler
SOURCE_DIRS = ["src", "utils"]

# Fichiers racine a compiler individuellement
# (run.py reste en clair : simple lanceur waitress sans logique metier)
ROOT_FILES = []

EXCLUDE_FILES = ["constants.py"]


def find_python_files(directories):
    python_files = []
    for directory in directories:
        if os.path.exists(directory):
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if file.endswith('.py') and not file.startswith('__') and file not in EXCLUDE_FILES:
                        filepath = os.path.join(root, file)
                        python_files.append(filepath)
    for f in ROOT_FILES:
        if os.path.exists(f):
            python_files.append(f)
    return python_files


# Creer les extensions Cython
def create_extensions():
    """Cree les extensions Cython pour chaque fichier Python"""
    extensions = []
    python_files = find_python_files(SOURCE_DIRS)

    TARGET_ARCH = os.environ.get("TARGET_ARCH", "amd64")

    # ARM64 : le build CI tourne sous QEMU (binfmt), ou gcc et son linker
    # segfaultent aleatoirement (setup.py -> "failed with exit code -11") sur
    # les gros fichiers C generes par Cython. -O2 au lieu de -O3 et -g0 (pas
    # d'infos de debug) reduisent nettement le travail et l'empreinte memoire
    # du compilateur, donc la probabilite de crash. Le gain de -O3 est de
    # toute facon negligeable ici : le code genere est presque uniquement des
    # appels a l'API CPython.
    if TARGET_ARCH == "arm64":
        ARCH_FLAGS = ["-march=armv8-a", "-O2", "-g0"]
    else:
        ARCH_FLAGS = ["-march=x86-64-v2", "-O3", "-g0"]

    for filepath in python_files:
        # Convertir le chemin en nom de module
        # Ex: src/handlers/camera.py -> src.handlers.camera
        module_name = filepath.replace('/', '.').replace('.py', '')

        extensions.append(
            Extension(
                module_name,
                [filepath],
                extra_compile_args=ARCH_FLAGS,
                language='c'
            )
        )

    return extensions


# Configuration
extensions = create_extensions()

setup(
    name="4isafecross-compiled",
    # package_dir est requis pour que build_ext --inplace place correctement
    # les .so sur setuptools >= 70 (Ubuntu 24.04 / Python 3.12).
    # Sans ce mapping, setuptools double le prefixe du package et tente
    # de copier src.foo.so dans src/src/ au lieu de src/.
    package_dir={
        'src': 'src',
        'utils': 'utils',
        '': '.',
    },
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            'language_level': "3",
            'annotation_typing': False,
            'embedsignature': False,
            'always_allow_keywords': True,
            # boundscheck/wraparound restent a True (defaut) : ces directives
            # n'accelerent que les tableaux types C (aucun dans ce code) et
            # compilent tout index negatif (ex: liste[-1]) en acces memoire
            # non verifie -> SIGSEGV avec Cython >= 3.2 (alert_manager:340,
            # utils.py get_service_status). Diagnostic: segfault sur
            # POST /api/zones en conteneur, pile native __Pyx_GetItemInt_Fast.
            'initializedcheck': False,
            'nonecheck': False,
            'cdivision': True,
        },
        build_dir='build',
        annotate=False
    ),
)
