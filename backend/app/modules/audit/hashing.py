"""Kanonische Serialisierung + Hash-Kette des Audit-Logs (security.md §4).

``hash = sha256(prev_hash || canonical_json(entry_ohne_hash))``. Reine, deterministische
Funktionen ohne DB/IO — der Hash ist allein aus den Feldwerten reproduzierbar (Risiko
laut Spec: stabile Key-Reihenfolge → ``sort_keys`` + kompakte Separatoren).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any


def canonical_payload(
    *,
    actor: str | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    at: datetime,
    data: dict[str, Any],
) -> bytes:
    """Audit-Felder (ohne ``id``/``hash``/``prev_hash``) → kanonische UTF-8-Bytes.

    ``sort_keys`` + kompakte Separatoren garantieren reproduzierbare Bytes unabhängig
    von der Einfüge-Reihenfolge der Keys (auch im verschachtelten ``data``-JSONB).
    ``at`` wird **nach UTC normalisiert** und als ISO-8601-String fixiert — der Hash
    bleibt so unabhängig von der Server-Zeitzone reproduzierbar (naive Werte werden als
    UTC interpretiert). Nicht JSON-native Werte in ``data`` lösen bewusst ``TypeError``
    aus (fail-closed statt stillem ``str()``)."""
    at_utc = (at if at.tzinfo is not None else at.replace(tzinfo=UTC)).astimezone(UTC)
    payload = {
        "action": action,
        "actor": actor,
        "at": at_utc.isoformat(),
        "data": data,
        "target_id": target_id,
        "target_type": target_type,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_hash(prev_hash: bytes | None, canonical: bytes) -> bytes:
    """``sha256(prev_hash || canonical)`` als Roh-Digest (32 Byte).

    Genesis-Eintrag (kein Vorgänger) nutzt ``prev_hash = b""`` → die Kette ist trotzdem
    eindeutig an ihren Anfang gebunden."""
    return hashlib.sha256((prev_hash or b"") + canonical).digest()
