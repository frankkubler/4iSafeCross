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
ROOT_FILES = ["app.py"]

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
    
    for filepath in python_files:
        # Convertir le chemin en nom de module
        # Ex: src/handlers/camera.py -> src.handlers.camera
        module_name = filepath.replace('/', '.').replace('.py', '')
        
        import os

        TARGET_ARCH = os.environ.get("TARGET_ARCH", "amd64")

        if TARGET_ARCH == "arm64":
            ARCH_FLAGS = ["-march=armv8-a"]
        else:
            ARCH_FLAGS = ["-march=x86-64-v2"]

        extensions.append(
            Extension(
                module_name,
                [filepath],
                # Options de compilation pour optimisation
                extra_compile_args=['-O3'] + ARCH_FLAGS,
                language='c'
            )
        )
    
    return extensions

# Configuration
extensions = create_extensions()

setup(
    name="4isafecross-compiled",
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            'language_level': "3",           # Python 3
            'annotation_typing': False,      # Ne pas interpreter les annotations comme types Cython
                                             # (requis pour les unions PEP 604 : X | None, Python 3.10+)
            'embedsignature': False,         # Ne pas inclure la signature (protection)
            'always_allow_keywords': True,   # Support kwargs
            'boundscheck': False,            # Desactiver verif bounds (performance)
            'wraparound': False,             # Desactiver indices negatifs (performance)
            'initializedcheck': False,       # Performance
            'nonecheck': False,              # Performance
            'cdivision': True,               # Division C (plus rapide)
        },
        # Options de build
        build_dir='build',
        annotate=False  # Ne pas generer les fichiers HTML d'annotation
    ),
)
