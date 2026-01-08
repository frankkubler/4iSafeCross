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

# Trouver tous les fichiers .py a compiler
def find_python_files(directories):
    """Trouve tous les fichiers .py dans les repertoires specifies"""
    python_files = []
    for directory in directories:
        if os.path.exists(directory):
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if file.endswith('.py') and not file.startswith('__'):
                        filepath = os.path.join(root, file)
                        python_files.append(filepath)
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
        
        extensions.append(
            Extension(
                module_name,
                [filepath],
                # Options de compilation pour optimisation
                extra_compile_args=['-O3', '-march=armv8-a'],
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
