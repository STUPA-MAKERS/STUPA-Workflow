"""API-Schemata des audit-Moduls (T-23, api.md ``/admin/audit``).

Nur Lese-Sichten. ``hash``/``prevHash`` als Hex ausgegeben (Integritätsnachweis,
keine PII). ``data`` enthält per Vertrag nur id-Referenzen/Metadaten (security.md §4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.audit.models import AuditEntry


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class AuditEntryOut(_CamelModel):
    """Ein Audit-Eintrag (Lesesicht)."""

    id: int
    at: datetime
    actor: str | None
    # Klarname des Akteurs (display_name/email, vom Router aufgelöst); None bei
    # System-/anonymen Vorgängen oder unbekanntem ``sub``.
    actor_name: str | None = Field(default=None, alias="actorName")
    action: str
    target_type: str | None = Field(alias="targetType")
    target_id: str | None = Field(alias="targetId")
    data: dict[str, Any]
    hash: str
    prev_hash: str | None = Field(alias="prevHash")

    @classmethod
    def from_entry(
        cls, entry: AuditEntry, actor_name: str | None = None
    ) -> AuditEntryOut:
        """ORM-Zeile → Out-Schema (bytea-Hashes hex-kodiert)."""
        return cls(
            id=entry.id,
            at=entry.at,
            actor=entry.actor,
            actorName=actor_name,
            action=entry.action,
            targetType=entry.target_type,
            targetId=entry.target_id,
            data=entry.data,
            hash=entry.hash.hex(),
            prevHash=entry.prev_hash.hex() if entry.prev_hash is not None else None,
        )


class AuditPageOut(_CamelModel):
    """Cursor-gepagte Audit-Sicht (Keyset auf ``id`` desc, neueste zuerst).

    ``nextCursor`` = ``id`` für den nächsten Aufruf (Query ``before``), oder ``None``
    am Ende. ``hasMore`` spiegelt dasselbe wider.
    """

    items: list[AuditEntryOut]
    next_cursor: int | None = Field(default=None, alias="nextCursor")
    has_more: bool = Field(default=False, alias="hasMore")


class AuditActorOut(_CamelModel):
    """Akteur-Auswahl (für den Actor-Filter): ``sub`` + aufgelöster Klarname."""

    sub: str
    name: str | None = None


class ChainVerificationOut(_CamelModel):
    """Ergebnis der Ketten-Verifikation (``/admin/audit/verify``)."""

    valid: bool
    checked: int
    broken_at: int | None = Field(default=None, alias="brokenAt")
    reason: str | None = None
