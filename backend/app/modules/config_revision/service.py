"""Config-revision service: append-only snapshot chain plus diff.

:meth:`record` appends a snapshot and writes the linked audit entry
(``data.revisionId`` — id reference only). A per-entity transaction advisory
lock is taken before reading the head, so concurrent appends serialize and
``version``/``prev`` stay consistent. No commit — the caller's transaction
commits atomically with the config mutation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.diff import DataDiff, compute_diff
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.config_revision.models import ConfigRevision

# Stable ``entity_type`` keys (= audit ``target_type``).
ENTITY_FORM = "form"
ENTITY_FLOW = "flow"
ENTITY_SITE_CONFIG = "site_config"

# Global (type-independent) entities share this ``entity_id``.
GLOBAL_ID = "global"


def _lock_key(entity_type: str, entity_id: str) -> int:
    """Stable 64-bit advisory-lock key per entity (process-/host-stable).

    Concurrent backends need the same key for the same entity, so no ``hash()``
    (randomized per process) — a deterministic BLAKE2b digest embedded as a
    signed bigint. Pure integer constant in SQL, injection-safe without a bind.
    """
    digest = hashlib.blake2b(
        f"{entity_type}:{entity_id}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big", signed=True)


def _flatten(entity_type: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Flatten a snapshot into an ``{identity: value}`` map for the field diff.

    Maps the natural snapshot shape (field list / FlowGraph / branding dict) to
    stable identity keys so :func:`compute_diff` yields per-field
    added/removed/changed instead of an opaque list comparison.
    """
    if entity_type == ENTITY_FORM:
        flat: dict[str, Any] = {}
        for field in snapshot.get("fields", []) or []:
            if isinstance(field, dict) and field.get("key"):
                flat[f"field:{field['key']}"] = field
        if snapshot.get("description") is not None:
            flat["meta:description"] = snapshot["description"]
        return flat
    if entity_type == ENTITY_FLOW:
        flat = {}
        for state in snapshot.get("states", []) or []:
            if isinstance(state, dict) and state.get("key"):
                flat[f"state:{state['key']}"] = state
        for tr in snapshot.get("transitions", []) or []:
            if isinstance(tr, dict):
                ident = f"{tr.get('from')}->{tr.get('to')}"
                if tr.get("branch"):
                    ident += f":{tr['branch']}"
                flat[f"transition:{ident}"] = tr
        if snapshot.get("layout"):
            flat["meta:layout"] = snapshot["layout"]
        return flat
    if entity_type == ENTITY_SITE_CONFIG:
        # Branding is already a flat (nested) top-level map.
        return dict(snapshot)
    return dict(snapshot)


class ConfigRevisionService:
    """Revision service bound to an ``AsyncSession``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def head(self, entity_type: str, entity_id: str) -> ConfigRevision | None:
        """Return the newest snapshot of an entity, or ``None``."""
        return await self.session.scalar(
            select(ConfigRevision)
            .where(
                ConfigRevision.entity_type == entity_type,
                ConfigRevision.entity_id == entity_id,
            )
            .order_by(ConfigRevision.version.desc())
            .limit(1)
        )

    async def get(self, revision_id: UUID | str) -> ConfigRevision | None:
        if isinstance(revision_id, str):
            try:
                revision_id = UUID(revision_id)
            except ValueError:
                return None
        return await self.session.get(ConfigRevision, revision_id)

    async def list_for(
        self, entity_type: str, entity_id: str
    ) -> list[ConfigRevision]:
        """List all snapshots of an entity (newest first)."""
        return list(
            (
                await self.session.scalars(
                    select(ConfigRevision)
                    .where(
                        ConfigRevision.entity_type == entity_type,
                        ConfigRevision.entity_id == entity_id,
                    )
                    .order_by(ConfigRevision.version.desc())
                )
            ).all()
        )

    async def record(
        self,
        *,
        entity_type: str,
        entity_id: str,
        snapshot: dict[str, Any],
        actor: str,
        action: AuditAction = AuditAction.CONFIG_CHANGE,
        extra_data: dict[str, Any] | None = None,
    ) -> ConfigRevision:
        """Append a snapshot and write the linked audit entry (no commit).

        ``snapshot`` must contain config only (no principal PII). The audit entry
        carries ``data.revisionId`` (id reference) plus ``extra_data``.
        """
        # Serialize appends per entity (version/prev consistent). The key is a
        # deterministic int constant (no user input), embedded directly, no bind.
        await self.session.execute(
            text(f"SELECT pg_advisory_xact_lock({_lock_key(entity_type, entity_id)})")
        )
        prev = await self.head(entity_type, entity_id)
        revision = ConfigRevision(
            entity_type=entity_type,
            entity_id=entity_id,
            version=(prev.version + 1) if prev is not None else 1,
            snapshot=snapshot,
            prev_revision_id=prev.id if prev is not None else None,
            created_by=actor,
        )
        self.session.add(revision)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=actor,
            action=action,
            target_type=entity_type,
            target_id=entity_id,
            data={
                "revisionId": str(revision.id),
                "version": revision.version,
                **(extra_data or {}),
            },
        )
        return revision

    async def diff(self, revision: ConfigRevision) -> DataDiff:
        """Field diff of this snapshot against its predecessor (empty for the first state)."""
        prev_snapshot: dict[str, Any] = {}
        if revision.prev_revision_id is not None:
            prev = await self.session.get(ConfigRevision, revision.prev_revision_id)
            if prev is not None:
                prev_snapshot = prev.snapshot or {}
        return compute_diff(
            _flatten(revision.entity_type, prev_snapshot),
            _flatten(revision.entity_type, revision.snapshot or {}),
        )

    async def resolve_versions(
        self, revisions: Sequence[ConfigRevision]
    ) -> dict[UUID, int]:
        """Map ``revision_id`` to ``version`` (for the sidebar diff labels)."""
        return {r.id: r.version for r in revisions}
