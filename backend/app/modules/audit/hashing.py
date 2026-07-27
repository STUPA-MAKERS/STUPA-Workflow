"""Canonical serialization and hash chain for the audit log.

The chain rule is ``hash = sha256(prev_hash || canonical_json(entry_without_hash))``.
These functions are pure and deterministic and do no database or IO work. The hash
is reproducible from the field values alone, because ``sort_keys`` and compact
separators fix the key order.
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
    """Serialize the audit fields to canonical UTF-8 bytes.

    The payload leaves out ``id``, ``hash`` and ``prev_hash``. The function
    normalizes ``at`` to UTC ISO-8601, so the hash does not depend on the server
    time zone. A naive ``at`` value counts as UTC.

    Raises:
        TypeError: ``data`` holds a value that JSON cannot represent. The call
            fails closed on purpose instead of falling back to a silent ``str()``.
    """
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

    The genesis entry has no predecessor. It uses ``prev_hash = b""``.
    """
    return hashlib.sha256((prev_hash or b"") + canonical).digest()
