"""Audit service: append-only writes, chain verification, queries.

:meth:`AuditService.record` takes a transaction advisory lock before reading the
predecessor hash, so concurrent appends serialize and the chain has no
``prev_hash`` races. :meth:`AuditService.verify_chain` recomputes the chain from
genesis, catching both tampered fields and removed/inserted rows. The module-level
:func:`record` hook is the standard entry point for other modules.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import REVERTABLE_BUDGET_ACTIONS, AuditAction
from app.modules.audit.hashing import canonical_payload, compute_hash
from app.modules.audit.models import AuditEntry
from app.shared.paging import Page

# Fixed advisory-lock key: serializes chain appends across processes.
_CHAIN_LOCK_KEY = 0x4155_4449_5400  # "AUDIT\0"


def data_uuid_strings(data: object) -> set[str]:
    """Collect all UUID-shaped string values (recursively) from a ``data`` payload.

    Used to resolve entity ids embedded in ``data`` to display names. Keys are
    ignored — only values count."""
    found: set[str] = set()

    def walk(v: object) -> None:
        if isinstance(v, str):
            try:
                uuid.UUID(v)
            except ValueError:
                return
            found.add(v)
        elif isinstance(v, dict):
            for x in v.values():  # pyright: ignore[reportUnknownVariableType]
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:  # pyright: ignore[reportUnknownVariableType]
                walk(x)

    walk(data)
    return found


@dataclass(frozen=True, slots=True)
class ChainVerification:
    """Result of :meth:`AuditService.verify_chain`."""

    valid: bool
    checked: int
    broken_at: int | None = None
    reason: str | None = None


class AuditService:
    """Audit service bound to an ``AsyncSession``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        actor: str | None,
        action: AuditAction | str,
        target_type: str | None = None,
        target_id: str | None = None,
        data: dict[str, Any] | None = None,
        at: datetime | None = None,
    ) -> AuditEntry:
        """Append an entry to the chain (no commit — caller's transaction).

        ``data`` must not contain raw PII values (id references/metadata only) —
        this is the caller's responsibility."""
        action_value = str(action)
        payload = data or {}
        stamp = at or datetime.now(UTC)

        # Serialize appends so `prev_hash` stays consistent. The key is a fixed
        # int constant (no user input), so embedding it directly is safe.
        await self.session.execute(text(f"SELECT pg_advisory_xact_lock({_CHAIN_LOCK_KEY})"))
        prev_hash = (
            await self.session.execute(
                select(AuditEntry.hash).order_by(AuditEntry.id.desc()).limit(1)
            )
        ).scalar_one_or_none()

        canonical = canonical_payload(
            actor=actor,
            action=action_value,
            target_type=target_type,
            target_id=target_id,
            at=stamp,
            data=payload,
        )
        entry = AuditEntry(
            actor=actor,
            action=action_value,
            target_type=target_type,
            target_id=target_id,
            at=stamp,
            data=payload,
            prev_hash=prev_hash,
            hash=compute_hash(prev_hash, canonical),
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def revertable_flags(
        self, entries: Sequence[AuditEntry]
    ) -> dict[int, bool]:
        """Determine per entry whether it is revertable from the log.

        Cheap, mostly static property for the list view — no per-row head/stale
        checks (the actual revert enforces those with 409). Config changes without
        a predecessor are not revertable; budget updates need the captured prior
        state. A batch lookup resolves the config-snapshot predecessor check."""
        flags: dict[int, bool] = {}
        revision_ids: dict[int, str] = {}
        for e in entries:
            data = e.data or {}
            rid = data.get("revisionId")
            if rid:
                revision_ids[e.id] = str(rid)
                flags[e.id] = False  # becomes True only after predecessor confirmation
            elif e.action == AuditAction.STATUS_CHANGE:
                flags[e.id] = bool(data.get("fromStateId") and data.get("toStateId"))
            elif e.action in REVERTABLE_BUDGET_ACTIONS:
                if e.action in (
                    AuditAction.BUDGET_NODE_UPDATE,
                    AuditAction.BUDGET_EXPENSE_UPDATE,
                ):
                    flags[e.id] = bool(data.get("before"))
                elif e.action == AuditAction.BUDGET_ALLOCATION_SET:
                    flags[e.id] = "previousAllocated" in data
                else:
                    flags[e.id] = True
            else:
                flags[e.id] = False
        if revision_ids:
            from app.modules.config_revision.models import ConfigRevision

            uuid_map: dict[uuid.UUID, int] = {}
            for eid, rid in revision_ids.items():
                try:
                    uuid_map[uuid.UUID(rid)] = eid
                except ValueError:
                    continue  # defensive: revisionId is normally always a UUID
            if uuid_map:
                rows = (
                    await self.session.execute(
                        select(
                            ConfigRevision.id, ConfigRevision.prev_revision_id
                        ).where(ConfigRevision.id.in_(uuid_map.keys()))
                    )
                ).all()
                for rev_id, prev_id in rows:
                    eid = uuid_map.get(rev_id)
                    if eid is not None:
                        flags[eid] = prev_id is not None
        return flags

    async def verify_chain(self) -> ChainVerification:
        """Recompute the chain from genesis; the first break is reported (fail-closed).

        Streams row by row (server-side cursor) instead of loading the whole
        chain into memory, so very long logs stay verifiable."""
        prev_hash: bytes | None = None
        checked = 0
        stream = await self.session.stream_scalars(
            select(AuditEntry).order_by(AuditEntry.id.asc())
        )
        async for entry in stream:
            if entry.prev_hash != prev_hash:
                return ChainVerification(
                    valid=False,
                    checked=checked,
                    broken_at=entry.id,
                    reason="prev_hash_mismatch",
                )
            canonical = canonical_payload(
                actor=entry.actor,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                at=entry.at,
                data=entry.data,
            )
            if compute_hash(entry.prev_hash, canonical) != entry.hash:
                return ChainVerification(
                    valid=False,
                    checked=checked,
                    broken_at=entry.id,
                    reason="hash_mismatch",
                )
            prev_hash = entry.hash
            checked += 1
        return ChainVerification(valid=True, checked=checked)

    async def query(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[AuditEntry]:
        """Filtered, descending (newest first) paged audit view."""
        stmt: Select[tuple[AuditEntry]] = select(AuditEntry)
        if action is not None:
            stmt = stmt.where(AuditEntry.action == action)
        if actor is not None:
            stmt = stmt.where(AuditEntry.actor == actor)
        if target_type is not None:
            stmt = stmt.where(AuditEntry.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(AuditEntry.target_id == target_id)
        if since is not None:
            stmt = stmt.where(AuditEntry.at >= since)
        if until is not None:
            stmt = stmt.where(AuditEntry.at <= until)

        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(AuditEntry.id.desc()).limit(limit).offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return Page(items=list(rows), total=total, limit=limit, offset=offset)

    async def query_cursor(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        before: int | None = None,
        limit: int = 50,
    ) -> tuple[list[AuditEntry], bool]:
        """Keyset-paged audit view (``id`` desc); returns (items, has_more).

        ``before`` is the keyset cursor (entries with ``id < before``); reading
        ``limit + 1`` rows determines ``has_more`` without a separate COUNT.

        Deliberately NO gremium filter — ``audit.read`` is a global, platform-wide
        read view. If scoped auditing is ever needed, both this query and the
        resolvers must be restricted to the caller's ``GremiumMembership`` set."""
        stmt: Select[tuple[AuditEntry]] = select(AuditEntry)
        if action is not None:
            stmt = stmt.where(AuditEntry.action == action)
        if actor is not None:
            stmt = stmt.where(AuditEntry.actor == actor)
        if since is not None:
            stmt = stmt.where(AuditEntry.at >= since)
        if until is not None:
            stmt = stmt.where(AuditEntry.at <= until)
        if before is not None:
            stmt = stmt.where(AuditEntry.id < before)

        rows = (
            (
                await self.session.execute(
                    stmt.order_by(AuditEntry.id.desc()).limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        has_more = len(rows) > limit
        return list(rows[:limit]), has_more

    async def resolve_actor_names(
        self, subs: Sequence[str | None]
    ) -> dict[str, str | None]:
        """Resolve ``sub`` to a display name (``display_name`` preferred, else ``email``).

        Batch lookup over the ``principal`` table; unknown/None subs are absent
        from the map."""
        from app.modules.auth.models import Principal

        wanted = {s for s in subs if s}
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(Principal.sub, Principal.display_name, Principal.email).where(
                    Principal.sub.in_(wanted)
                )
            )
        ).all()
        return {sub: (display_name or email) for sub, display_name, email in rows}

    async def resolve_target_labels(
        self, targets: Sequence[tuple[str | None, str | None]]
    ) -> dict[tuple[str, str], str]:
        """Resolve ``(target_type, target_id)`` to a human-readable label (batch).

        Best effort: only types with a name source are resolved; deleted targets
        or non-UUID ids are absent from the map. No PII beyond the read view —
        everything here is reachable via admin views for ``audit.read`` holders."""
        by_type: dict[str, set[uuid.UUID]] = {}
        for target_type, target_id in targets:
            if not target_type or not target_id:
                continue
            try:
                by_type.setdefault(target_type, set()).add(uuid.UUID(target_id))
            except ValueError:
                continue  # e.g. export filenames — target_id is itself the label

        labels: dict[tuple[str, str], str] = {}

        async def fill(
            target_type: str, stmt: Select[tuple[uuid.UUID, Any]]
        ) -> None:
            for row_id, label in (await self.session.execute(stmt)).all():
                if label:
                    labels[(target_type, str(row_id))] = label

        def i18n_label(m: object) -> str | None:
            if not isinstance(m, dict) or not m:
                return None
            return m.get("de") or next(iter(m.values()), None)

        if ids := by_type.get("application"):
            from app.modules.applications.models import Application

            rows = (
                await self.session.execute(
                    select(Application.id, Application.data).where(
                        Application.id.in_(ids)
                    )
                )
            ).all()
            for row_id, data in rows:
                title = (data or {}).get("title")
                if isinstance(title, str) and title.strip():
                    labels[("application", str(row_id))] = title.strip()
        if ids := by_type.get("gremium"):
            from app.modules.admin.models import Gremium

            await fill(
                "gremium", select(Gremium.id, Gremium.name).where(Gremium.id.in_(ids))
            )
        if ids := by_type.get("application_type"):
            from app.modules.admin.models import ApplicationType

            rows = (
                await self.session.execute(
                    select(ApplicationType.id, ApplicationType.name_i18n).where(
                        ApplicationType.id.in_(ids)
                    )
                )
            ).all()
            for row_id, name_i18n in rows:
                if label := i18n_label(name_i18n):
                    labels[("application_type", str(row_id))] = label
        if ids := by_type.get("role"):
            from app.modules.auth.models import Role

            rows = (
                await self.session.execute(
                    select(Role.id, Role.name_i18n, Role.key).where(Role.id.in_(ids))
                )
            ).all()
            for row_id, name_i18n, key in rows:
                if label := i18n_label(name_i18n) or key:
                    labels[("role", str(row_id))] = label
        if ids := by_type.get("principal"):
            from app.modules.auth.models import Principal

            rows = (
                await self.session.execute(
                    select(
                        Principal.id, Principal.display_name, Principal.email
                    ).where(Principal.id.in_(ids))
                )
            ).all()
            for row_id, display_name, email in rows:
                if label := display_name or email:
                    labels[("principal", str(row_id))] = label
        if ids := by_type.get("webhook"):
            from app.modules.admin.models import Webhook

            await fill(
                "webhook", select(Webhook.id, Webhook.name).where(Webhook.id.in_(ids))
            )
        if ids := by_type.get("vote"):
            from app.modules.voting.models import Vote

            await fill("vote", select(Vote.id, Vote.question).where(Vote.id.in_(ids)))
        if ids := by_type.get("attachment"):
            from app.modules.files.models import Attachment

            await fill(
                "attachment",
                select(Attachment.id, Attachment.filename).where(
                    Attachment.id.in_(ids)
                ),
            )
        return labels

    async def resolve_data_ids(
        self, data_dicts: Sequence[dict[str, Any] | None]
    ) -> dict[str, str]:
        """Resolve UUIDs in ``data`` payloads to display names (batch).

        ``data`` keys are untyped, so all UUID-shaped values are collected
        recursively and resolved per table via ``id IN (...)`` — UUIDs are
        globally unique, so no collisions. Unresolvable/deleted ids are absent
        from the map. No extra PII exposure beyond the admin views.
        """
        candidates: set[uuid.UUID] = set()
        for d in data_dicts:
            for s in data_uuid_strings(d):
                candidates.add(uuid.UUID(s))
        if not candidates:
            return {}

        labels: dict[str, str] = {}

        def i18n_label(m: object) -> str | None:
            if not isinstance(m, dict) or not m:
                return None
            return m.get("de") or next(iter(m.values()), None)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]

        async def fill(stmt: Select[tuple[uuid.UUID, Any]]) -> None:
            for row_id, label in (await self.session.execute(stmt)).all():
                if label and str(row_id) not in labels:
                    labels[str(row_id)] = label

        from app.modules.admin.models import ApplicationType, Gremium, Webhook
        from app.modules.applications.models import Application
        from app.modules.auth.models import Principal, Role
        from app.modules.budget.tree_models import Budget, FiscalYear
        from app.modules.files.models import Attachment
        from app.modules.livevote.models import Meeting
        from app.modules.voting.models import Vote

        # Application: the title lives in the JSONB ``data`` (no label column).
        for row_id, data in (
            await self.session.execute(
                select(Application.id, Application.data).where(
                    Application.id.in_(candidates)
                )
            )
        ).all():
            title = (data or {}).get("title")
            if isinstance(title, str) and title.strip():
                labels[str(row_id)] = title.strip()

        await fill(select(Gremium.id, Gremium.name).where(Gremium.id.in_(candidates)))
        await fill(select(Budget.id, Budget.name).where(Budget.id.in_(candidates)))
        await fill(select(Meeting.id, Meeting.title).where(Meeting.id.in_(candidates)))
        await fill(select(Webhook.id, Webhook.name).where(Webhook.id.in_(candidates)))
        await fill(select(Vote.id, Vote.question).where(Vote.id.in_(candidates)))
        await fill(
            select(Attachment.id, Attachment.filename).where(
                Attachment.id.in_(candidates)
            )
        )

        # Multi-column / derived labels (order irrelevant — ``fill`` never overwrites).
        for row_id, display_name, email in (
            await self.session.execute(
                select(Principal.id, Principal.display_name, Principal.email).where(
                    Principal.id.in_(candidates)
                )
            )
        ).all():
            if (label := display_name or email) and str(row_id) not in labels:
                labels[str(row_id)] = label
        for row_id, name_i18n, key in (
            await self.session.execute(
                select(Role.id, Role.name_i18n, Role.key).where(
                    Role.id.in_(candidates)
                )
            )
        ).all():
            if (label := i18n_label(name_i18n) or key) and str(row_id) not in labels:
                labels[str(row_id)] = label
        for row_id, name_i18n in (
            await self.session.execute(
                select(ApplicationType.id, ApplicationType.name_i18n).where(
                    ApplicationType.id.in_(candidates)
                )
            )
        ).all():
            if (label := i18n_label(name_i18n)) and str(row_id) not in labels:
                labels[str(row_id)] = label
        for row_id, year in (
            await self.session.execute(
                select(FiscalYear.id, FiscalYear.year).where(
                    FiscalYear.id.in_(candidates)
                )
            )
        ).all():
            if str(row_id) not in labels:
                labels[str(row_id)] = str(year)
        return labels

    async def list_actors(self) -> list[tuple[str, str | None]]:
        """List distinct log actors (``sub``) with resolved display names."""
        subs = (
            (
                await self.session.execute(
                    select(AuditEntry.actor)
                    .where(AuditEntry.actor.is_not(None))
                    .distinct()
                    .order_by(AuditEntry.actor)
                )
            )
            .scalars()
            .all()
        )
        actor_subs = [s for s in subs if s is not None]
        names = await self.resolve_actor_names(actor_subs)
        return [(sub, names.get(sub)) for sub in actor_subs]


async def record(
    session: AsyncSession,
    *,
    actor: str | None,
    action: AuditAction | str,
    target_type: str | None = None,
    target_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> AuditEntry:
    """Service hook for other modules: write one audit entry (no commit)."""
    return await AuditService(session).record(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        data=data,
    )
