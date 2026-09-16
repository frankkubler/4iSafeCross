"""La version de l'application a une source unique par contexte, jamais config.ini.

Conteneur : ENV APP_VERSION gravée au build (tag Git). Sources : [project] version
de pyproject.toml. Auparavant, config.ini portait une clé APP_VERSION dupliquée —
or ce fichier est un bind-mount du site, figé au premier déploiement : l'IHM
affichait l'ancienne version après une mise à jour d'image (CS-1141-01).
"""
import configparser
import os

import pytest

from utils.constants import (APP_VERSION, _project_version_from_text,
                             _version_from_pyproject)

RACINE = os.path.dirname(os.path.abspath(__file__))


def _version_declaree():
    with open(os.path.join(RACINE, 'pyproject.toml'), encoding='utf-8') as f:
        return _project_version_from_text(f.read())


def test_la_version_vient_de_pyproject():
    assert _version_from_pyproject() == _version_declaree()


def test_app_version_suit_l_environnement_ou_pyproject():
    env = os.environ.get('APP_VERSION')
    assert APP_VERSION == (env or _version_declaree())
    assert APP_VERSION, "jamais vide : 'dev' au pire"


def test_config_ini_ne_porte_plus_la_version():
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(RACINE, 'config', 'config.ini'), encoding='utf-8')
    assert 'APP_VERSION' not in cfg['APP'], "la version ne doit plus être dupliquée dans config.ini"


# ── Repli sans tomllib (Python 3.10, requires-python >= 3.10) ────────────────

def test_repli_sans_tomllib_lit_la_section_project():
    assert _project_version_from_text('[project]\nname = "x"\nversion = "1.2.3"\n') == "1.2.3"
    assert _project_version_from_text("[project]\nversion = '4.5.6'\n") == "4.5.6"
    assert _project_version_from_text('[project]\nversion   =   "7.8.9"\n') == "7.8.9"


def test_repli_ignore_la_version_d_un_autre_tableau():
    texte = '[project]\nname = "x"\n\n[tool.autre]\nversion = "0.0.1"\n'
    assert _project_version_from_text(texte) is None, "un [tool.*] versionné n'est pas la version du projet"

    texte = '[tool.autre]\nversion = "0.0.1"\n\n[project]\nversion = "2.0.0"\n'
    assert _project_version_from_text(texte) == "2.0.0"


def test_repli_sur_fichier_vide_ou_sans_project():
    assert _project_version_from_text("") is None
    assert _project_version_from_text('[tool.ruff]\nline-length = 100\n') is None


def test_le_repli_donne_le_meme_resultat_que_tomllib():
    with open(os.path.join(RACINE, 'pyproject.toml'), encoding='utf-8') as f:
        texte = f.read()
    tomllib = pytest.importorskip("tomllib")
    assert _project_version_from_text(texte) == tomllib.loads(texte)["project"]["version"]
