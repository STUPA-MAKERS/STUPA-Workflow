"""Audit service: append-only writes, chain verification, queries.

`AuditService.record` takes a transaction advisory lock before it reads the
predecessor hash. Concurrent appends therefore serialize and the chain has no
``prev_hash`` race. `AuditService.verify_chain` recomputes the chain from genesis.
It catches both a tampered field and a removed or inserted row.
`AuditService.verify_and_store` runs the same check and stores the result in
``audit_verification``. The prune keeps the first failed check of each
break and the newest check of each trigger. `AuditService.run_manual_verification` is the
manual entry point. It refuses a run while another run is in progress, and a second
manual run inside the cooldown. The module-level `record` hook is the standard entry
point for other modules.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Row, Select, delete, func, select, text
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.hashing import canonical_payload, compute_hash
from app.modules.audit.models import (
    MANUAL_VERIFICATION_COOLDOWN,
    VERIFICATION_KEEP,
    AuditEntry,
    AuditVerification,
    ChainBreak,
    VerificationTrigger,
)
from app.shared.errors import ConflictError, RateLimitedError
from app.shared.paging import Page

logger = logging.getLogger("app.audit")

#: Fixed advisory-lock key (``"AUDIT\0"``). It serializes chain appends across
#: processes. It is a constant, not user input, so SQL interpolation of it is safe.
_CHAIN_LOCK_KEY = 0x4155_4449_5400
#: Fixed advisory-lock key (``"AUDIV\1"``). It lets only one chain check run at a time.
_VERIFY_LOCK_KEY = 0x4155_4449_5601


def _entry_hash(entry: AuditEntry) -> bytes:
    """Recompute the hash of a stored entry from its fields and its ``prev_hash``."""
    canonical = canonical_payload(
        actor=entry.actor,
        action=entry.action,
        target_type=entry.target_type,
        target_id=entry.target_id,
        at=entry.at,
        data=entry.data,
    )
    return compute_hash(entry.prev_hash, canonical)


def _link_break(prev_hash: bytes | None, entry: AuditEntry) -> ChainBreak | None:
    """Tell why ``entry`` does not continue the chain after ``prev_hash``.

    A different ``prev_hash`` means a removed or an inserted row. A different
    recomputed hash means a changed field. The ``prev_hash`` check comes first and
    the hash is recomputed only for a linked row, because ``canonical_payload`` raises
    on a ``data`` value that JSON cannot represent.

    Returns:
        The reason of the break, or ``None`` when the entry is intact.
    """
    return (
        "prev_hash_mismatch"
        if entry.prev_hash != prev_hash
        else None if _entry_hash(entry) == entry.hash else "hash_mismatch"
    )


def _entry_filters(
    *,
    action: str | None = None,
    actor: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before: int | None = None,
) -> tuple[ColumnElement[bool], ...]:
    """Build the WHERE clauses of the set filters of an audit query, in a fixed order.

    A filter that is ``None`` adds no clause. Each clause is built only for a set
    filter, because SQLAlchemy refuses an order comparison with ``None``.
    """
    clauses = (
        AuditEntry.action == action if action is not None else None,
        AuditEntry.actor == actor if actor is not None else None,
        AuditEntry.target_type == target_type if target_type is not None else None,
        AuditEntry.target_id == target_id if target_id is not None else None,
        AuditEntry.at >= since if since is not None else None,
        AuditEntry.at <= until if until is not None else None,
        AuditEntry.id < before if before is not None else None,
    )
    return tuple(clause for clause in clauses if clause is not None)


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
        """Bind the service to a database session."""
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
        responsible for keeping raw PII values out of it. A transaction-scoped
        advisory lock serializes the appends, so ``prev_hash`` stays consistent.
        """
        action_value = str(action)
        payload = data or {}
        stamp = at or datetime.now(UTC)

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

    async def _rows_for(
        self, ids: Collection[object], stmt: Select[*tuple[Any, ...]]
    ) -> Sequence[Row[*tuple[Any, ...]]]:
        """Run ``stmt`` and return its rows. Without ``ids`` no query runs."""
        return (await self.session.execute(stmt)).all() if ids else ()

    async def verify_chain(self) -> ChainVerification:
        """Recompute the chain from genesis and report the first break.

        The check is fail-closed. The method streams row by row with a server-side
        cursor instead of loading the whole chain into memory. A very long log stays
        verifiable. ``populate_existing`` makes it read the rows as the database holds
        them, never a copy that the identity map of this session still caches. The
        fold over the stream stays a loop that carries the previous hash and the count,
        because a comprehension would load the whole chain into memory.
        """
        prev_hash: bytes | None = None
        checked = 0
        stream = await self.session.stream_scalars(
            select(AuditEntry)
            .order_by(AuditEntry.id.asc())
            .execution_options(populate_existing=True)
        )
        async for entry in stream:
            reason = _link_break(prev_hash, entry)
            if reason is not None:
                return ChainVerification(
                    valid=False, checked=checked, broken_at=entry.id, reason=reason
                )
            prev_hash = entry.hash
            checked += 1
        return ChainVerification(valid=True, checked=checked)

    async def verify_and_store(
        self,
        *,
        trigger: VerificationTrigger,
        triggered_by: str | None = None,
        keep: int = VERIFICATION_KEEP,
    ) -> AuditVerification:
        """Verify the whole chain, store the result and commit.

        The method first waits for the check lock, so only one check runs at a
        time. It writes one ``audit_verification`` row with the start, the end and
        the result of `verify_chain`. It then prunes the stored checks (see
        `prune_verifications`). It logs the duration, because the check reads the
        whole ``audit_entry`` table and its run time grows with the log.

        Args:
            trigger: ``cron``, ``manual`` or ``restore``.
            triggered_by: The principal ``sub`` that started the check. ``None``
                for the cron.
            keep: The number of stored checks to keep.

        Returns:
            The stored row.
        """
        await self.session.execute(text(f"SELECT pg_advisory_xact_lock({_VERIFY_LOCK_KEY})"))
        return await self._verify_and_store_locked(
            trigger=trigger, triggered_by=triggered_by, keep=keep
        )

    async def run_manual_verification(
        self,
        *,
        triggered_by: str,
        cooldown: timedelta = MANUAL_VERIFICATION_COOLDOWN,
    ) -> AuditVerification:
        """Run a manual chain check (``trigger = manual``) and store the result.

        The check reads the whole log inside the API request. The method therefore
        refuses a run that it cannot do now. It does not wait for the check lock. A
        refusal rolls back at once, so the lock goes free before the request session
        closes.

        Raises:
            ConflictError: Another check (cron, restore or manual) is in progress.
            RateLimitedError: A manual check started less than ``cooldown`` ago.
        """
        locked = (
            await self.session.execute(
                text(f"SELECT pg_try_advisory_xact_lock({_VERIFY_LOCK_KEY})")
            )
        ).scalar_one()
        if not locked:
            await self.session.rollback()
            raise ConflictError(
                "an audit chain check is in progress", code="audit_verify_running"
            )
        last_manual = (
            await self.session.execute(
                select(func.max(AuditVerification.started_at)).where(
                    AuditVerification.trigger == "manual"
                )
            )
        ).scalar_one_or_none()
        wait = (
            last_manual + cooldown - datetime.now(UTC)
            if last_manual is not None
            else timedelta(0)
        )
        if wait > timedelta(0):
            await self.session.rollback()
            raise RateLimitedError(
                "a manual audit chain check ran a short time ago",
                retry_after=int(wait.total_seconds()) + 1,
                code="audit_verify_cooldown",
            )
        return await self._verify_and_store_locked(
            trigger="manual", triggered_by=triggered_by, keep=VERIFICATION_KEEP
        )

    async def _verify_and_store_locked(
        self,
        *,
        trigger: VerificationTrigger,
        triggered_by: str | None,
        keep: int,
    ) -> AuditVerification:
        """Do the work of `verify_and_store`. The caller holds the check lock."""
        started_at = datetime.now(UTC)
        clock = time.monotonic()
        result = await self.verify_chain()
        duration_ms = int((time.monotonic() - clock) * 1000)
        row = AuditVerification(
            started_at=started_at,
            finished_at=datetime.now(UTC),
            valid=result.valid,
            checked=result.checked,
            broken_at=result.broken_at,
            reason=result.reason,
            trigger=trigger,
            triggered_by=triggered_by,
        )
        self.session.add(row)
        await self.session.flush()
        await self.prune_verifications(keep=keep)
        await self.session.commit()
        log = logger.info if result.valid else logger.error
        log(
            "audit chain check: trigger=%s valid=%s checked=%d broken_at=%s "
            "reason=%s duration_ms=%d",
            trigger,
            result.valid,
            result.checked,
            result.broken_at,
            result.reason,
            duration_ms,
        )
        return row

    async def prune_verifications(self, *, keep: int = VERIFICATION_KEEP) -> None:
        """Delete the old checks. No commit.

        The prune keeps the newest ``keep`` rows. Past them, it keeps:

        - the first failed check of each break, that is the oldest row of each
          distinct ``(broken_at, reason)``. A failed check is evidence of
          tampering. A series of new checks must not push it out of the store.
          The later checks of the same break repeat that evidence, so the prune
          deletes them like valid rows. Because ``audit_entry`` is append-only,
          a break stays until a restore. Thus the table stays bounded also when
          every check fails.
        - the newest check of each trigger. Many manual checks thus do not push
          out the last cron or restore result.
        """
        newest = (
            select(AuditVerification.id)
            .order_by(AuditVerification.started_at.desc(), AuditVerification.id.desc())
            .limit(keep)
        )
        newest_per_trigger = (
            select(AuditVerification.id)
            .ext(distinct_on(AuditVerification.trigger))
            .order_by(
                AuditVerification.trigger,
                AuditVerification.started_at.desc(),
                AuditVerification.id.desc(),
            )
        )
        first_per_break = (
            select(AuditVerification.id)
            .where(AuditVerification.valid.is_(False))
            .ext(distinct_on(AuditVerification.broken_at, AuditVerification.reason))
            .order_by(
                AuditVerification.broken_at,
                AuditVerification.reason,
                AuditVerification.started_at.asc(),
                AuditVerification.id.asc(),
            )
        )
        await self.session.execute(
            delete(AuditVerification)
            .where(
                AuditVerification.id.not_in(newest),
                AuditVerification.id.not_in(newest_per_trigger),
                AuditVerification.id.not_in(first_per_break),
            )
            .execution_options(synchronize_session=False)
        )

    async def latest_verification(self) -> AuditVerification | None:
        """Return the newest stored chain check, or ``None`` before the first one."""
        return (
            await self.session.execute(
                select(AuditVerification)
                .order_by(
                    AuditVerification.started_at.desc(), AuditVerification.id.desc()
                )
                .limit(1)
            )
        ).scalar_one_or_none()

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
        stmt: Select[AuditEntry] = select(AuditEntry).where(
            *_entry_filters(
                action=action,
                actor=actor,
                target_type=target_type,
                target_id=target_id,
                since=since,
                until=until,
            )
        )
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
        stmt: Select[AuditEntry] = select(AuditEntry).where(
            *_entry_filters(action=action, actor=actor, since=since, until=until, before=before)
        )

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
        ``principal`` table in one batch. A ``sub`` of a merged account gives the
        name of the account it was merged into: the log keeps the old ``sub``. An
        unknown sub and a None sub are absent from the map.
        """
        from app.modules.auth.identity import refs_by_sub

        return {sub: ref.name for sub, ref in (await refs_by_sub(self.session, subs)).items()}

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
