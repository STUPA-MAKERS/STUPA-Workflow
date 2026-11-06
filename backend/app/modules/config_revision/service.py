"""Config-revision service: the append-only snapshot chain plus the diff.

``record`` appends a snapshot and writes the linked audit entry. The audit entry
holds ``data.revisionId`` as an id reference only. The service takes a transaction
advisory lock per entity before it reads the head. Concurrent appends therefore
serialize, and ``version`` and ``prev`` stay consistent. The service never commits.
The transaction of the caller commits atomically with the config mutation.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.diff import DataDiff, compute_diff
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.config_revision.models import ConfigRevision

#: Stable ``entity_type`` keys (= audit ``target_type``).
ENTITY_FORM = "form"
ENTITY_FLOW = "flow"
ENTITY_SITE_CONFIG = "site_config"

#: Entities that do not belong to one type share this ``entity_id``.
GLOBAL_ID = "global"


def _lock_key(entity_type: str, entity_id: str) -> int:
    """Build a stable 64-bit advisory-lock key for one entity.

    The key stays the same across processes and hosts. Concurrent backends need the
    same key for the same entity. The function therefore does not use ``hash()``,
    which Python randomizes per process. It uses a deterministic BLAKE2b digest read
    as a signed bigint. The result is a plain integer constant in SQL. It is
    injection-safe without a bind parameter.
    """
    digest = hashlib.blake2b(
        f"{entity_type}:{entity_id}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big", signed=True)


def _as_uuid(raw: UUID | str) -> UUID | None:
    """Return ``raw`` as a UUID, or None for a malformed string."""
    if not isinstance(raw, str):
        return raw
    try:
        return UUID(raw)
    except ValueError:
        return None


def _form_entries(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Map a form snapshot to one entry per keyed field plus the description."""
    fields = {
        f"field:{field['key']}": field
        for field in snapshot.get("fields", []) or []
        if isinstance(field, dict) and field.get("key")
    }
    description = snapshot.get("description")
    return fields if description is None else {**fields, "meta:description": description}


def _transition_ident(transition: dict[str, Any]) -> str:
    """Return the identity of a transition: ``from->to``, plus ``:branch`` when it has one."""
    base = f"{transition.get('from')}->{transition.get('to')}"
    return f"{base}:{transition['branch']}" if transition.get("branch") else base


def _flow_entries(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Map a flow snapshot to one entry per keyed state and transition plus the layout."""
    states = {
        f"state:{state['key']}": state
        for state in snapshot.get("states", []) or []
        if isinstance(state, dict) and state.get("key")
    }
    transitions = {
        f"transition:{_transition_ident(tr)}": tr
        for tr in snapshot.get("transitions", []) or []
        if isinstance(tr, dict)
    }
    layout = snapshot.get("layout")
    meta = {"meta:layout": layout} if layout else {}
    return {**states, **transitions, **meta}


def _flatten(entity_type: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Flatten a snapshot into an ``{identity: value}`` map for the field diff.

    The function maps the natural snapshot shape to stable identity keys. That shape
    is a field list, a ``FlowGraph`` or a branding dict. ``compute_diff`` can then
    report added, removed and changed per field instead of comparing opaque lists.
    A site config (branding dict) and an unknown entity are already flat.
    """
    match entity_type:
        case "form":
            return _form_entries(snapshot)
        case "flow":
            return _flow_entries(snapshot)
        case _:
            return dict(snapshot)


class ConfigRevisionService:
    """Revision service bound to an ``AsyncSession``."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a database session."""
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
        """Return a revision by id, or None for an unknown or malformed id."""
        key = _as_uuid(revision_id)
        return None if key is None else await self.session.get(ConfigRevision, key)

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
        """Append a snapshot and write the linked audit entry.

        The method does not commit. The audit entry carries ``data.revisionId`` as an
        id reference, plus ``extra_data``. ``snapshot`` must hold config only and no
        principal PII. ``actor`` is the OIDC ``sub`` to record.

        An advisory lock per entity serializes the appends, so version and prev stay
        consistent. The lock key is a deterministic integer with no user input, so it
        goes into the SQL text without a bind parameter.
        """
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
        """Diff this snapshot against its predecessor, empty for the first state."""
        prev = (
            await self.session.get(ConfigRevision, revision.prev_revision_id)
            if revision.prev_revision_id is not None
            else None
        )
        prev_snapshot: dict[str, Any] = (prev.snapshot or {}) if prev is not None else {}
        return compute_diff(
            _flatten(revision.entity_type, prev_snapshot),
            _flatten(revision.entity_type, revision.snapshot or {}),
        )
