#!/usr/bin/env bash
# Test manuel du garde-fou licence (JSON + last_seen_time + HMAC)
# Usage:
#   SAFECROSS_LICENSE=config/4isafecross.lic ./scripts/test-license-guard.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LIC_PATH="${SAFECROSS_LICENSE:-config/4isafecross.lic}"
STATE_FILE="config/license_state.json"
KEY_FILE="config/license_state.key"
export LIC_PATH

if [[ ! -f "$LIC_PATH" ]]; then
  echo "ERREUR: licence introuvable: $LIC_PATH"
  exit 1
fi

BACKUP_DIR="$(mktemp -d)"
cleanup() {
  if [[ -f "$BACKUP_DIR/license_state.json" ]]; then
    cp "$BACKUP_DIR/license_state.json" "$STATE_FILE"
  else
    rm -f "$STATE_FILE"
  fi

  if [[ -f "$BACKUP_DIR/license_state.key" ]]; then
    cp "$BACKUP_DIR/license_state.key" "$KEY_FILE"
  else
    rm -f "$KEY_FILE"
  fi

  rm -rf "$BACKUP_DIR"
}
trap cleanup EXIT

if [[ -f "$STATE_FILE" ]]; then
  cp "$STATE_FILE" "$BACKUP_DIR/license_state.json"
fi
if [[ -f "$KEY_FILE" ]]; then
  cp "$KEY_FILE" "$BACKUP_DIR/license_state.key"
fi

echo "[1/4] Baseline: verification valide et creation/mise a jour du state"
python - <<'PY'
import os
from utils.license_validator import load_and_verify_license
load_and_verify_license(os.environ["LIC_PATH"], required_features=["presence"])
print("OK baseline")
PY

echo "[2/4] Test HMAC invalide: attendu -> ECHEC"
python - <<'PY'
import json
from pathlib import Path
state_file = Path("config/license_state.json")
state = json.loads(state_file.read_text(encoding="utf-8"))
state["hmac"] = "invalid-hmac"
state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
print("State modifie avec hmac invalide")
PY

if python - <<'PY'
import os
from utils.license_validator import load_and_verify_license
load_and_verify_license(os.environ["LIC_PATH"], required_features=["presence"])
print("UNEXPECTED: verification a reussi")
PY
then
  echo "ERREUR: le test HMAC invalide aurait du echouer"
  exit 1
else
  echo "OK: HMAC invalide detecte"
fi

echo "[3/4] Re-initialisation state propre"
python - <<'PY'
import os
from utils.license_validator import load_and_verify_license
load_and_verify_license(os.environ["LIC_PATH"], required_features=["presence"])
print("State re-initialise")
PY

echo "[4/4] Test rollback horloge simule: attendu -> ECHEC"
python - <<'PY'
import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

state_file = Path("config/license_state.json")
key_file = Path("config/license_state.key")
state = json.loads(state_file.read_text(encoding="utf-8"))
key = key_file.read_bytes()

future_ms = int(time.time() * 1000) + (2 * 3600 * 1000)
state["timestamp"] = future_ms
state["last_seen_time"] = future_ms
payload = {
    "version": int(state["version"]),
    "machine_id": str(state["machine_id"]),
    "timestamp": int(state["timestamp"]),
    "last_seen_time": int(state["last_seen_time"]),
}
raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
state["hmac"] = base64.urlsafe_b64encode(
    hmac.new(key, raw, hashlib.sha256).digest()
).decode("ascii")
state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
print("State modifie avec last_seen_time futur + hmac valide")
PY

if python - <<'PY'
import os
from utils.license_validator import load_and_verify_license
load_and_verify_license(os.environ["LIC_PATH"], required_features=["presence"])
print("UNEXPECTED: verification a reussi")
PY
then
  echo "ERREUR: le test rollback aurait du echouer"
  exit 1
else
  echo "OK: rollback detecte"
fi

echo "Tests termines. Les fichiers de state initiaux ont ete restaures."