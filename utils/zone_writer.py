"""
Module d'écriture des zones de détection dans le fichier zones.ini.

Fournit les fonctions pour sauvegarder les polygones de zones
dans le format attendu par load_zones_by_camera_from_ini().
"""

import os
import re
import logging

logger = logging.getLogger(__name__)


def save_zones_to_ini(ini_path, cam_id, zones):
    """Sauvegarde les zones d'une caméra dans le fichier zones.ini.

    Supprime toutes les sections *_cam{cam_id} existantes et les remplace
    par les nouvelles zones fournies. Les sections des autres caméras
    sont conservées intactes.

    Args:
        ini_path: Chemin vers le fichier zones.ini.
        cam_id: Identifiant numérique de la caméra (ex: 0, 1).
        zones: Liste de dictionnaires avec les clés :
            - name (str): Nom de la zone (ex: "zone1_cam0").
            - polygon (list): Liste de [x, y] ou (x, y).
            - color (list/tuple): Couleur RGB [R, G, B].

    Raises:
        IOError: Si le fichier ne peut pas être écrit.
        ValueError: Si les données de zones sont invalides.
    """
    cam_suffix = f"_cam{cam_id}"

    # Lire le fichier existant et parser les sections manuellement
    # (configparser ne préserve pas les commentaires)
    existing_sections = _parse_ini_sections(ini_path)

    # Filtrer les sections qui n'appartiennent PAS à cette caméra
    other_sections = [
        s for s in existing_sections
        if not s["header"].endswith(cam_suffix)
    ]

    # Construire les nouvelles sections pour cette caméra
    new_sections = []
    for i, zone in enumerate(zones):
        name = zone.get("name", f"zone{i + 1}_cam{cam_id}")
        polygon = zone.get("polygon", [])
        color = zone.get("color", [255, 0, 0])

        if len(polygon) < 3:
            logger.warning(f"Zone '{name}' ignorée : polygone avec moins de 3 points")
            continue

        # Formater le polygone : (x1, y1), (x2, y2), ...
        poly_str = ", ".join(
            f"({int(pt[0])}, {int(pt[1])})" for pt in polygon
        )
        # Formater la couleur : R,G,B
        color_str = ",".join(str(int(c)) for c in color)

        relays = zone.get("relays", [])
        entries = [
            ("polygon", poly_str),
            ("color", color_str),
        ]
        if relays:
            entries.append(("relays", ",".join(str(r) for r in relays)))

        section = {
            "header": name,
            "entries": entries,
        }
        new_sections.append(section)

    # Combiner : autres caméras + nouvelles zones de cette caméra
    all_sections = other_sections + new_sections

    # Écrire le fichier
    _write_ini_sections(ini_path, all_sections)

    logger.info(
        f"Zones sauvegardées pour cam{cam_id} : "
        f"{len(new_sections)} zones écrites dans {ini_path}"
    )


def _parse_ini_sections(ini_path):
    """Parse un fichier INI en préservant la structure par section.

    Args:
        ini_path: Chemin du fichier INI.

    Returns:
        Liste de dictionnaires {"header": str, "entries": [(key, value), ...]}.
    """
    sections = []
    if not os.path.exists(ini_path):
        return sections

    current_section = None
    with open(ini_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            # Ignorer les lignes vides et commentaires hors section
            if not stripped or stripped.startswith("#"):
                continue

            # Nouvelle section
            section_match = re.match(r"^\[(.+)\]$", stripped)
            if section_match:
                if current_section is not None:
                    sections.append(current_section)
                current_section = {
                    "header": section_match.group(1),
                    "entries": [],
                }
                continue

            # Entrée clé = valeur
            if current_section is not None and "=" in stripped:
                key, _, value = stripped.partition("=")
                current_section["entries"].append(
                    (key.strip(), value.strip())
                )

    if current_section is not None:
        sections.append(current_section)

    return sections


def _write_ini_sections(ini_path, sections):
    """Écrit les sections dans un fichier INI.

    Args:
        ini_path: Chemin du fichier INI.
        sections: Liste de {"header": str, "entries": [(key, value), ...]}.
    """
    os.makedirs(os.path.dirname(ini_path) or ".", exist_ok=True)

    with open(ini_path, "w", encoding="utf-8") as f:
        for i, section in enumerate(sections):
            if i > 0:
                f.write("\n")
            f.write(f"[{section['header']}]\n")
            for key, value in section["entries"]:
                f.write(f"{key} = {value}\n")
