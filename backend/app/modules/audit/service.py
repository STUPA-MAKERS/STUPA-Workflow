"""Audit service: append-only writes, chain verification, queries.

`AuditService.record` takes a transaction advisory lock before it reads the
predecessor hash. Concurrent appends therefore serialize and the chain has no
``prev_hash`` race. `AuditService.verify_chain` recomputes the chain from genesis.
It catches both a tampered field and a removed or inserted row. The module-level
`record` hook is the standard entry point for other modules.
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

# Fixed advisory-lock key. It serializes chain appends across processes.
_CHAIN_LOCK_KEY = 0x4155_4449_5400  # "AUDIT\0"


def data_uuid_strings(data: object) -> set[str]:
    """Collect every UUID-shaped string value from a ``data`` payload, recursively.

    The caller resolves the entity ids inside ``data`` to display names with this
    set. The walk ignores keys and looks at values only.
    """
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
    """Result of `AuditService.verify_chain`."""

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
        """Append an entry to the chain.

        The method does not commit. It runs in the transaction of the caller. The
        ``data`` payload holds id references and metadata only. The caller is
        responsible for keeping raw PII values out of it.
        """
        action_value = str(action)
        payload = data or {}
        stamp = at or datetime.now(UTC)

        # Serialize appends so that `prev_hash` stays consistent. The key is a fixed
        # integer constant and not user input, so the direct interpolation is safe.
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
        """Determine for each entry whether the log can revert it.

        The check is cheap and mostly static, because the list view needs it for
        every row. It runs no per-row head or stale check. The actual revert call
        enforces those and answers 409. A config change without a predecessor is not
        revertable. A budget update needs the captured prior state. One batch lookup
        resolves the config-snapshot predecessor check.
        """
        flags: dict[int, bool] = {}
        revision_ids: dict[int, str] = {}
        for e in entries:
            data = e.data or {}
            rid = data.get("revisionId")
            if rid:
                revision_ids[e.id] = str(rid)
                flags[e.id] = False  # turns True only after the predecessor check
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
        """Recompute the chain from genesis and report the first break.

        The check is fail-closed. The method streams row by row with a server-side
        cursor instead of loading the whole chain into memory. A very long log stays
        verifiable.
        """
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
        """Read a filtered, offset-paged audit view, newest entry first."""
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
        """Read a keyset-paged audit view, ordered by ``id`` descending.

        ``before`` is the keyset cursor. The query returns entries with
        ``id < before``. It reads ``limit + 1`` rows to find ``has_more`` without a
        separate COUNT.

        This query has NO Gremium filter, on purpose. ``audit.read`` is a global,
        platform-wide read view. If the platform ever needs a scoped audit, restrict
        both this query and the resolvers to the ``GremiumMembership`` set of the
        caller.

        Returns:
            The page items and a flag that states whether more rows follow.
        """
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
        """Resolve each ``sub`` to a display name.

        The lookup prefers ``display_name`` and falls back to ``email``. It reads the
        ``principal`` table in one batch. An unknown sub and a None sub are absent
        from the map.
        """
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
        """Resolve each ``(target_type, target_id)`` pair to a readable label.

        The lookup runs in batches and is best effort. It resolves only a type that
        has a name source. A deleted target and a non-UUID id are absent from the
        map. The method adds no PII beyond the read view. A holder of ``audit.read``
        can reach all of it through the admin views.

        A config target keeps the id of the entity it configures. ``form`` therefore
        holds an ``application_type`` id and reads the same table. ``flow`` holds the
        literal id ``global`` and ``notification_settings`` holds ``1``. Both are
        singletons with no name column, so no lookup can resolve them.
        """
        by_type: dict[str, set[uuid.UUID]] = {}
        for target_type, target_id in targets:
            if not target_type or not target_id:
                continue
            try:
                by_type.setdefault(target_type, set()).add(uuid.UUID(target_id))
            except ValueError:
                continue  # for example an export filename: target_id is the label

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
        # ``form`` and ``application_type`` both hold an application-type id, so one
        # query serves both. A form config change writes the id of the type it belongs
        # to, and the type name is the only name a form has.
        form_ids = by_type.get("form", set())
        type_ids = by_type.get("application_type", set())
        if form_ids or type_ids:
            from app.modules.admin.models import ApplicationType

            rows = (
                await self.session.execute(
                    select(ApplicationType.id, ApplicationType.name_i18n).where(
                        ApplicationType.id.in_(form_ids | type_ids)
                    )
                )
            ).all()
            for row_id, name_i18n in rows:
                label = i18n_label(name_i18n)
                if not label:
                    continue
                if row_id in form_ids:
                    labels[("form", str(row_id))] = label
                if row_id in type_ids:
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
        if ids := by_type.get("cd_variant"):
            from app.modules.admin.models import CdVariant

            await fill(
                "cd_variant",
                select(CdVariant.id, CdVariant.name).where(CdVariant.id.in_(ids)),
            )
        if ids := by_type.get("site_config"):
            from app.modules.admin.models import SiteConfigVersion

            # A site-config version has no name column. The version number is the
            # only thing that tells two drafts apart, and it reads the same in
            # both UI locales.
            rows = (
                await self.session.execute(
                    select(SiteConfigVersion.id, SiteConfigVersion.version).where(
                        SiteConfigVersion.id.in_(ids)
                    )
                )
            ).all()
            for row_id, version in rows:
                labels[("site_config", str(row_id))] = f"Version {version}"
        return labels

    async def resolve_data_ids(
        self, data_dicts: Sequence[dict[str, Any] | None]
    ) -> dict[str, str]:
        """Resolve the UUIDs inside ``data`` payloads to display names, in batches.

        The keys of ``data`` are untyped. The method therefore collects every
        UUID-shaped value recursively and resolves it per table with an
        ``id IN (...)`` query. A UUID is globally unique, so the tables cannot
        collide. An id that the method cannot resolve, and an id of a deleted row,
        are absent from the map. The method exposes no extra PII beyond the admin
        views.
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

        # Application: the title lives in the JSONB ``data``. There is no label column.
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

        # Multi-column and derived labels. The order does not matter, because ``fill``
        # never overwrites an entry.
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
    """Write one audit entry for another module, without a commit."""
    return await AuditService(session).record(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        data=data,
    )
