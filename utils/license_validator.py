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
        "features":   ["presence", "absence", "cls", "full"] # liste des fonctionnalités autorisées
    }

La clé publique (PUBLIC_KEY_PEM ci-dessous) doit correspondre à la paire de clés
utilisée par le gestionnaire de licences.
Pour l'obtenir :  cat ~/.4icheck_licenses/public_key.pem
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import date, datetime, timezone
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
_STATE_FILE = Path(__file__).parent.parent / "config" / "license_state.json"
_STATE_KEY_FILE = Path(__file__).parent.parent / "config" / "license_state.key"

_STATE_SCHEMA_VERSION = 1
_CLOCK_ROLLBACK_TOLERANCE_SEC = 5


def _get_public_key_pem_bytes() -> bytes:
    """Retourne la clé publique PEM brute (fichier prioritaire, sinon constante)."""
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes()
    return PUBLIC_KEY_PEM.strip().encode()


def _load_public_key():
    """Charge la clé publique depuis le fichier config/ ou depuis la constante PEM."""
    pem = _get_public_key_pem_bytes()
    return serialization.load_pem_public_key(pem, backend=default_backend())


def _canonicalize_state_payload(payload: dict) -> bytes:
    """Sérialise un payload de façon déterministe pour le calcul du HMAC."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_or_create_state_key() -> bytes:
    """Lit la clé HMAC locale ou la crée au premier lancement."""
    if _STATE_KEY_FILE.exists():
        return _STATE_KEY_FILE.read_bytes()

    _STATE_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    _STATE_KEY_FILE.write_bytes(key)

    try:
        os.chmod(_STATE_KEY_FILE, 0o600)
    except OSError:
        logger.warning("Impossible de restreindre les permissions de %s", _STATE_KEY_FILE)

    return key


def _compute_state_hmac(payload_without_hmac: dict) -> str:
    """Calcule un HMAC SHA-256 (base64url) du state local de licence."""
    key = _read_or_create_state_key()
    mac = hmac.new(key, _canonicalize_state_payload(payload_without_hmac), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode("ascii")


def _load_state() -> Optional[dict]:
    """Charge le state local JSON si présent, sinon retourne None."""
    if not _STATE_FILE.exists():
        return None

    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Fichier state de licence invalide: {exc}") from exc


def _save_state(state: dict) -> None:
    """Écrit le state local de façon atomique pour éviter les corruptions."""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = _STATE_FILE.with_suffix(".json.tmp")
    tmp_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_file.replace(_STATE_FILE)


def _verify_and_update_local_clock_state(machine_id: str) -> None:
    """
    Vérifie l'intégrité du state local et détecte un rollback d'horloge.

    En cas de succès, met à jour `timestamp` et `last_seen_time` à l'instant courant.
    """
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    tolerance_ms = _CLOCK_ROLLBACK_TOLERANCE_SEC * 1000

    state = _load_state()
    if state is not None:
        try:
            version = int(state["version"])
            saved_machine_id = str(state["machine_id"])
            saved_last_seen = int(state["last_seen_time"])
            saved_timestamp = int(state["timestamp"])
            saved_hmac = str(state["hmac"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"State de licence incomplet ou invalide: {exc}") from exc

        if version != _STATE_SCHEMA_VERSION:
            raise ValueError(
                f"Version de state de licence non supportée: {version} "
                f"(attendu: {_STATE_SCHEMA_VERSION})"
            )

        expected_hmac = _compute_state_hmac(
            {
                "version": version,
                "machine_id": saved_machine_id,
                "timestamp": saved_timestamp,
                "last_seen_time": saved_last_seen,
            }
        )
        if not hmac.compare_digest(saved_hmac, expected_hmac):
            raise ValueError("State de licence falsifié: HMAC invalide")

        if saved_machine_id != machine_id:
            raise ValueError(
                "State de licence incompatible avec cette machine "
                f"('{saved_machine_id}' != '{machine_id}')"
            )

        if now_ms + tolerance_ms < saved_last_seen:
            delta_sec = (saved_last_seen - now_ms) // 1000
            raise ValueError(
                "Rollback d'horloge détecté: "
                f"heure locale en retard de {delta_sec} seconde(s)"
            )

    new_payload = {
        "version": _STATE_SCHEMA_VERSION,
        "machine_id": machine_id,
        "timestamp": now_ms,
        "last_seen_time": now_ms,
    }
    new_state = {
        **new_payload,
        "hmac": _compute_state_hmac(new_payload),
    }
    _save_state(new_state)


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
    check_clock_rollback: bool = True,
) -> dict:
    """
    Vérifie une licence LicenceCheck.

    Args:
        lic_content:       Contenu brut de la licence (chaîne base64url.base64url).
        required_features: Liste des fonctionnalités requises, ex. ["presence"].
                           None = pas de vérification des features.
        check_machine_id:  Si True, vérifie que machine_id correspond à la machine actuelle.
        check_clock_rollback: Si True, active la protection locale anti-retour d'horloge.

    Returns:
        Le payload dict si la licence est valide.

    Raises:
        ValueError:  Licence invalide (format, signature, expirée, machine,
                 feature, rollback d'horloge, state local falsifié).
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
    current_mid = get_machine_id()

    if check_machine_id:
        if payload.get("machine_id") != current_mid:
            raise ValueError(
                f"Cette licence est destinée à la machine '{payload.get('machine_id')}', "
                f"machine actuelle : '{current_mid}'"
            )

    # ── 6. Anti-retour d'horloge locale (JSON + last_seen_time + HMAC) ─────
    if check_clock_rollback:
        _verify_and_update_local_clock_state(current_mid)

    # ── 7. Fonctionnalités ────────────────────────────────────────────────────
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
    check_clock_rollback: bool = True,
) -> dict:
    """
    Charge un fichier .lic et le vérifie.

    Args:
        lic_path:          Chemin vers le fichier de licence (contient le token brut).
        required_features: Voir verify_license().
        check_machine_id:  Voir verify_license().
        check_clock_rollback: Voir verify_license().

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
    return verify_license(
        lic_content,
        required_features,
        check_machine_id,
        check_clock_rollback,
    )
