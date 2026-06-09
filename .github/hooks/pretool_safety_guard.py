#!/usr/bin/env python3
"""PreToolUse hook to require confirmation for risky operations in 4iSafeCross."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

PROTECTED_PATH_MARKERS = [
    "models/",
    "db/",
    "dataset/",
    "config/",
    "scripts/",
    "/docs/security/",
    ".env",
]


def emit_decision(decision: str, reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def load_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
        return {"_payload": value}
    except json.JSONDecodeError:
        return {"_raw": raw}


def flatten_strings(node: Any) -> list[str]:
    out: list[str] = []
    stack: list[Any] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            out.append(cur)
        elif isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return out


def detect_dangerous_terminal_command(text_blob: str) -> bool:
    patterns = [
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+checkout\s+--\b",
        r"\bgit\s+clean\s+-fd\b",
        r"\brm\s+-rf\s+(/|\.|~|\$|\*)",
        r"\bsudo\s+rm\s+-rf\b",
        r"\bmkfs\b",
        r"\bdd\s+if=",
    ]
    return any(re.search(p, text_blob, flags=re.IGNORECASE) for p in patterns)


def targets_protected_paths(text_blob: str) -> bool:
    lowered = text_blob.lower()
    normalized = lowered.replace("\\", "/")
    return any(marker in normalized for marker in PROTECTED_PATH_MARKERS)


def likely_destructive_edit(text_blob: str) -> bool:
    lowered = text_blob.lower()
    destructive_tokens = [
        "*** delete file:",
        'edittype": "delete"',
        "delete",
        "remove",
        "unlink",
        "truncate",
    ]
    return any(token in lowered for token in destructive_tokens)


def main() -> int:
    payload = load_payload()
    all_text = "\n".join(flatten_strings(payload))

    if detect_dangerous_terminal_command(all_text):
        emit_decision(
            "ask",
            "Commande potentiellement destructive detectee: confirmation utilisateur requise.",
        )
        return 0

    if targets_protected_paths(all_text) and likely_destructive_edit(all_text):
        emit_decision(
            "ask",
            "Operation destructive sur dossier/fichier sensible detectee: confirmation utilisateur requise.",
        )
        return 0

    emit_decision("allow", "Aucun risque critique detecte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
