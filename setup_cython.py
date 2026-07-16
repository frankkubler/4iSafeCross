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

    if TARGET_ARCH == "arm64":
        ARCH_FLAGS = ["-march=armv8-a"]
    else:
        ARCH_FLAGS = ["-march=x86-64-v2"]

    for filepath in python_files:
        # Convertir le chemin en nom de module
        # Ex: src/handlers/camera.py -> src.handlers.camera
        module_name = filepath.replace('/', '.').replace('.py', '')

        extensions.append(
            Extension(
                module_name,
                [filepath],
                extra_compile_args=['-O3'] + ARCH_FLAGS,
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
            'boundscheck': False,
            'wraparound': False,
            'initializedcheck': False,
            'nonecheck': False,
            'cdivision': True,
        },
        build_dir='build',
        annotate=False
    ),
)
