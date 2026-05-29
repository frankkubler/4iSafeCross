"""
Validation des licences LicenceCheck.

Format de licence (généré par 4icheck_license_manager) :
    base64url(payload_json) . base64url(signature_RSA_PKCS1v15_SHA256)

Payload JSON :
    {
        "client":     "Nom du client",
        "machine_id": "identifiant machine",
        "issued":     "YYYY-MM-DD",
        "expires":    "YYYY-MM-DD",
        "features":   ["presence", "absence", "cls"]
    }

La clé publique (PUBLIC_KEY_PEM ci-dessous) doit correspondre à la paire de clés
utilisée par le gestionnaire de licences.
Pour l'obtenir :  cat ~/.4icheck_licenses/public_key.pem
"""

import base64
import json
import logging
import subprocess
import uuid
from datetime import date
from pathlib import Path
from typing import Optional, Union

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)

# ── Clé publique ──────────────────────────────────────────────────────────────
# Coller ici le contenu de ~/.4icheck_licenses/public_key.pem
# (clé publique uniquement — jamais la clé privée dans le dépôt)
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
REMPLACER_PAR_VOTRE_CLE_PUBLIQUE
-----END PUBLIC KEY-----"""

# Chemin alternatif : fichier public_key.pem déployé à côté de l'application
_KEY_FILE = Path(__file__).parent.parent / "config" / "public_key.pem"


def _load_public_key():
    """Charge la clé publique depuis le fichier config/ ou depuis la constante PEM."""
    if _KEY_FILE.exists():
        pem = _KEY_FILE.read_bytes()
    else:
        pem = PUBLIC_KEY_PEM.strip().encode()
    return serialization.load_pem_public_key(pem, backend=default_backend())


def get_machine_id() -> str:
    """
    Retourne un identifiant stable de la machine.

    Ordre de priorité :
      1. /etc/machine-id  (Linux systemd — le plus stable)
      2. UUID basé sur l'adresse MAC (fallback cross-platform)

    Cette valeur doit être celle saisie dans le champ « Machine ID »
    lors de la génération de la licence dans 4icheck_license_manager.
    """
    machine_id_file = Path("/etc/machine-id")
    if machine_id_file.exists():
        mid = machine_id_file.read_text().strip()
        if mid:
            return mid
    # Fallback : adresse MAC via uuid
    return str(uuid.UUID(int=uuid.getnode()))


def verify_license(
    lic_content: str,
    required_features: Optional[list[str]] = None,
    check_machine_id: bool = True,
) -> dict:
    """
    Vérifie une licence LicenceCheck.

    Args:
        lic_content:       Contenu brut de la licence (chaîne base64url.base64url).
        required_features: Liste des fonctionnalités requises, ex. ["presence"].
                           None = pas de vérification des features.
        check_machine_id:  Si True, vérifie que machine_id correspond à la machine actuelle.

    Returns:
        Le payload dict si la licence est valide.

    Raises:
        ValueError:  Licence invalide (format, signature, expirée, machine, feature).
    """
    # ── 1. Décodage ──────────────────────────────────────────────────────────
    parts = lic_content.strip().split(".")
    if len(parts) != 2:
        raise ValueError("Format de licence invalide (attendu : payload.signature)")

    try:
        payload_bytes = base64.urlsafe_b64decode(parts[0] + "==")
        sig_bytes = base64.urlsafe_b64decode(parts[1] + "==")
    except Exception as exc:
        raise ValueError(f"Décodage base64 échoué : {exc}") from exc

    # ── 2. Vérification de la signature RSA ──────────────────────────────────
    try:
        pub_key = _load_public_key()
        pub_key.verify(sig_bytes, payload_bytes, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise ValueError("Signature de licence invalide — licence falsifiée ou clé incorrecte")
    except Exception as exc:
        raise ValueError(f"Erreur lors de la vérification de la signature : {exc}") from exc

    # ── 3. Parsing du payload ─────────────────────────────────────────────────
    try:
        payload = json.loads(payload_bytes.decode())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Payload JSON invalide : {exc}") from exc

    # ── 4. Date d'expiration ──────────────────────────────────────────────────
    try:
        expires = date.fromisoformat(payload["expires"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Champ 'expires' manquant ou invalide : {exc}") from exc

    if date.today() > expires:
        raise ValueError(
            f"Licence expirée le {payload['expires']} "
            f"(il y a {(date.today() - expires).days} jour(s))"
        )

    # ── 5. Machine ID ─────────────────────────────────────────────────────────
    if check_machine_id:
        current_mid = get_machine_id()
        if payload.get("machine_id") != current_mid:
            raise ValueError(
                f"Cette licence est destinée à la machine '{payload.get('machine_id')}', "
                f"machine actuelle : '{current_mid}'"
            )

    # ── 6. Fonctionnalités ────────────────────────────────────────────────────
    if required_features:
        licensed_features = set(payload.get("features", []))
        missing = set(required_features) - licensed_features
        if missing:
            raise ValueError(
                f"Fonctionnalité(s) non autorisée(s) par la licence : {', '.join(sorted(missing))}"
            )

    logger.info(
        "✅ Licence valide — client : %s, expire : %s, features : %s",
        payload.get("client"),
        payload.get("expires"),
        payload.get("features"),
    )
    return payload


def load_and_verify_license(
    lic_path: Union[str, Path],
    required_features: Optional[list[str]] = None,
    check_machine_id: bool = True,
) -> dict:
    """
    Charge un fichier .lic et le vérifie.

    Args:
        lic_path:          Chemin vers le fichier de licence (contient le token brut).
        required_features: Voir verify_license().
        check_machine_id:  Voir verify_license().

    Returns:
        Le payload dict si la licence est valide.

    Raises:
        FileNotFoundError: Fichier introuvable.
        ValueError:        Licence invalide.
    """
    lic_path = Path(lic_path)
    if not lic_path.exists():
        raise FileNotFoundError(f"Fichier de licence introuvable : {lic_path}")

    lic_content = lic_path.read_text().strip()
    return verify_license(lic_content, required_features, check_machine_id)
