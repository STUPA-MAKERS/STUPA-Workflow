"""API schemas for the audit module (read-only views).

``hash``/``prevHash`` are emitted as hex; ``data`` carries only id
references/metadata by contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.audit.models import AuditEntry


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fields populatable by name."""

    model_config = ConfigDict(populate_by_name=True)


class AuditEntryOut(_CamelModel):
    """One audit entry (read view)."""

    id: int
    at: datetime
    actor: str | None
    # Actor display name (resolved by the router); None for system/anonymous
    # operations or an unknown ``sub``.
    actor_name: str | None = Field(default=None, alias="actorName")
    action: str
    target_type: str | None = Field(alias="targetType")
    target_id: str | None = Field(alias="targetId")
    # Human-readable target label, batch-resolved by the router; None if the
    # target is deleted/unknown.
    target_label: str | None = Field(default=None, alias="targetLabel")
    data: dict[str, Any]
    # UUID-string -> display name for entity references embedded in ``data``,
    # batch-resolved by the router; only resolvable ids are included.
    resolved_ids: dict[str, str] = Field(default_factory=dict, alias="resolvedIds")
    # Revertable from the audit log (determined by the router); the backend stays
    # authoritative on the actual revert call (409 when stale).
    revertable: bool = False
    hash: str
    prev_hash: str | None = Field(alias="prevHash")

    @classmethod
    def from_entry(
        cls,
        entry: AuditEntry,
        actor_name: str | None = None,
        target_label: str | None = None,
        resolved_ids: dict[str, str] | None = None,
        revertable: bool = False,
    ) -> AuditEntryOut:
        """Map an ORM row to the out schema (bytea hashes hex-encoded)."""
        return cls(
            id=entry.id,
            at=entry.at,
            actor=entry.actor,
            actorName=actor_name,
            action=entry.action,
            targetType=entry.target_type,
            targetId=entry.target_id,
            targetLabel=target_label,
            data=entry.data,
            resolvedIds=resolved_ids or {},
            revertable=revertable,
            hash=entry.hash.hex(),
            prevHash=entry.prev_hash.hex() if entry.prev_hash is not None else None,
        )


class AuditPageOut(_CamelModel):
    """Cursor-paged audit view (keyset on ``id`` desc, newest first).

    ``nextCursor`` is the ``id`` for the next call (query ``before``), or ``None``
    at the end.
    """

    items: list[AuditEntryOut]
    next_cursor: int | None = Field(default=None, alias="nextCursor")
    has_more: bool = Field(default=False, alias="hasMore")


class AuditActorOut(_CamelModel):
    """Actor option for the actor filter: ``sub`` plus resolved display name."""

    sub: str
    name: str | None = None


class ChainVerificationOut(_CamelModel):
    """Result of chain verification (``/admin/audit/verify``)."""

    valid: bool
    checked: int
    broken_at: int | None = Field(default=None, alias="brokenAt")
    reason: str | None = None


class AuditRevertOut(_CamelModel):
    """Result of an audit-log revert (``POST /admin/audit/{id}/revert``)."""

    reverted_audit_id: int = Field(alias="revertedAuditId")
    entity_type: str = Field(alias="entityType")
    entity_id: str = Field(alias="entityId")
