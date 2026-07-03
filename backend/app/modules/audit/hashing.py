"""Canonical serialization and hash chain for the audit log.

``hash = sha256(prev_hash || canonical_json(entry_without_hash))``. Pure,
deterministic functions without DB/IO — the hash is reproducible from field
values alone (stable key order via ``sort_keys`` + compact separators).
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
    """Serialize audit fields (without ``id``/``hash``/``prev_hash``) to canonical UTF-8 bytes.

    ``at`` is normalized to UTC ISO-8601 so the hash is independent of the server
    timezone (naive values are treated as UTC). Non-JSON-native values in ``data``
    deliberately raise ``TypeError`` (fail-closed instead of a silent ``str()``)."""
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
    """Compute ``sha256(prev_hash || canonical)`` as a raw 32-byte digest.

    The genesis entry (no predecessor) uses ``prev_hash = b""``."""
    return hashlib.sha256((prev_hash or b"") + canonical).digest()
