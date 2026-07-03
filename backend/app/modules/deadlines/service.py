"""Deadline service: scan + lock + idempotency markers.

Pure DB layer for the arq cron (:mod:`worker.deadlines`); the actual effect
(fire transition, close vote, send reminder) lives in the worker.

Concurrency: the ``lock_*`` methods select a single row with ``FOR UPDATE SKIP
LOCKED`` — a second worker sees ``None`` and skips, so nothing runs twice. The
persistent marker (``action_on_pass=NULL`` / ``reminded_at``) prevents repeats
across worker restarts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deadlines.models import Deadline, DeadlinePolicy
from app.modules.voting.models import Vote

# Cap per cron tick, oldest first: a large backlog drains over several ticks
# instead of one tick overrunning the 1-minute cadence. Correctness is unaffected
# (SKIP LOCKED + idempotency markers) — ungrabbed rows stay due for the next tick.
DEFAULT_SCAN_LIMIT = 200


class DeadlineService:
    """Deadline operations bound to an ``AsyncSession``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ create
    async def create(
        self,
        *,
        kind: str,
        due_at: datetime,
        application_id: UUID | None = None,
        type_id: UUID | None = None,
        action_on_pass: dict | None = None,
    ) -> Deadline:
        """Create and persist a deadline (programmatic API, no HTTP endpoint)."""
        deadline = Deadline(
            kind=kind,
            due_at=due_at,
            application_id=application_id,
            type_id=type_id,
            action_on_pass=action_on_pass,
        )
        self.session.add(deadline)
        await self.session.flush()
        await self.session.commit()
        return deadline

    # ------------------------------------------------------------------- scans
    async def due_action_deadline_ids(
        self, now: datetime, *, limit: int = DEFAULT_SCAN_LIMIT
    ) -> list[UUID]:
        """List due auto-deadline ids (``due_at<=now`` and ``action_on_pass`` set),
        capped at ``limit`` oldest-first."""
        rows = (
            await self.session.execute(
                select(Deadline.id)
                .where(
                    Deadline.action_on_pass.isnot(None),
                    Deadline.due_at <= now,
                )
                .order_by(Deadline.due_at)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def due_reminder_ids(
        self, now: datetime, lead: timedelta, *, limit: int = DEFAULT_SCAN_LIMIT
    ) -> list[UUID]:
        """List ids of upcoming (or already passed) deadlines not yet reminded.

        Deliberately no lower bound (``due_at > now``): if the worker was down
        longer than the lead window, a two-sided condition would never match the
        row again — the reminder would never be sent and the row would leak in the
        partial index. This way exactly one (possibly late) reminder is sent and
        ``reminded_at`` removes the row from the scan. Capped at ``limit``."""
        rows = (
            await self.session.execute(
                select(Deadline.id)
                .where(
                    Deadline.reminded_at.is_(None),
                    Deadline.due_at <= now + lead,
                )
                .order_by(Deadline.due_at)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def due_open_vote_ids(
        self, now: datetime, *, limit: int = DEFAULT_SCAN_LIMIT
    ) -> list[UUID]:
        """List ids of open votes whose window has passed, capped at ``limit``."""
        rows = (
            await self.session.execute(
                select(Vote.id)
                .where(
                    Vote.status == "open",
                    Vote.closes_at.isnot(None),
                    Vote.closes_at <= now,
                )
                .order_by(Vote.closes_at)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    # ------------------------------------------------------------------- locks
    async def lock_action_deadline(
        self, deadline_id: UUID, now: datetime
    ) -> Deadline | None:
        """Lock a due auto-deadline (``SKIP LOCKED``); ``None`` if held by another
        worker or already consumed."""
        return (
            await self.session.execute(
                select(Deadline)
                .where(
                    Deadline.id == deadline_id,
                    Deadline.action_on_pass.isnot(None),
                    Deadline.due_at <= now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()

    async def lock_reminder(
        self, deadline_id: UUID, now: datetime, lead: timedelta
    ) -> Deadline | None:
        """Lock a not-yet-reminded deadline (``SKIP LOCKED``). Mirrors
        :meth:`due_reminder_ids`: no lower bound so late reminders go out once."""
        return (
            await self.session.execute(
                select(Deadline)
                .where(
                    Deadline.id == deadline_id,
                    Deadline.reminded_at.is_(None),
                    Deadline.due_at <= now + lead,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()

    async def lock_open_vote(self, vote_id: UUID, now: datetime) -> Vote | None:
        """Lock an open, expired vote (``SKIP LOCKED``)."""
        return (
            await self.session.execute(
                select(Vote)
                .where(
                    Vote.id == vote_id,
                    Vote.status == "open",
                    Vote.closes_at.isnot(None),
                    Vote.closes_at <= now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()

    # ----------------------------------------------------------------- markers
    async def consume_action(self, deadline: Deadline) -> None:
        """Mark an auto-deadline as fired (``action_on_pass=NULL``) and commit.

        Removes the row from the partial scan index — no re-firing."""
        deadline.action_on_pass = None
        await self.session.commit()

    async def mark_reminded(self, deadline: Deadline, now: datetime) -> None:
        """Mark the reminder as sent (``reminded_at=now``) and commit."""
        deadline.reminded_at = now
        await self.session.commit()


async def flow_deadline_passed(session: AsyncSession, application_id: UUID) -> bool:
    """Return whether a (possibly already consumed) flow deadline is due.

    Flow deadlines always belong to the application's current state — the flow
    engine clears them on every state change (``schedule_state_deadline``), so a
    due row means the *current* state's deadline has passed. Shared by
    ``FlowService._deadline_passed`` and the task-mail recipient resolution.
    """
    row = await session.scalar(
        select(Deadline.id)
        .where(
            Deadline.application_id == application_id,
            Deadline.kind == "flow_deadline",
            Deadline.due_at <= datetime.now(UTC),
        )
        .limit(1)
    )
    return row is not None


def resolve_due_at(
    policy: DeadlinePolicy,
    *,
    submitted_at: datetime | None = None,
    changed_at: datetime | None = None,
) -> datetime | None:
    """Derive a concrete due date from a policy + application timestamps (pure).

    Missing reference value (e.g. no ``submitted_at``) yields ``None``."""
    if policy.kind == "absolute":
        return policy.absolute_at
    days = policy.offset_days or 0
    if policy.kind == "relative_submitted":
        return submitted_at + timedelta(days=days) if submitted_at else None
    if policy.kind == "relative_changed":
        return changed_at + timedelta(days=days) if changed_at else None
    return None


class DeadlinePolicyError(Exception):
    """Violated policy invariant (e.g. duplicate key); mapped to 409/422."""


class DeadlinePolicyService:
    """CRUD for the named deadline policies (admin-maintained registry)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[DeadlinePolicy]:
        rows = (
            await self.session.execute(
                select(DeadlinePolicy).order_by(DeadlinePolicy.key)
            )
        ).scalars().all()
        return list(rows)

    async def get(self, policy_id: UUID) -> DeadlinePolicy | None:
        return await self.session.get(DeadlinePolicy, policy_id)

    async def get_by_key(self, key: str) -> DeadlinePolicy | None:
        return (
            await self.session.execute(
                select(DeadlinePolicy).where(DeadlinePolicy.key == key)
            )
        ).scalar_one_or_none()

    async def create(
        self,
        *,
        key: str,
        label: dict,
        kind: str,
        absolute_at: datetime | None,
        offset_days: int | None,
    ) -> DeadlinePolicy:
        if await self.get_by_key(key):
            raise DeadlinePolicyError(f"deadline policy key already exists: {key!r}")
        policy = DeadlinePolicy(
            key=key,
            label=label,
            kind=kind,
            absolute_at=absolute_at if kind == "absolute" else None,
            offset_days=offset_days if kind != "absolute" else None,
        )
        self.session.add(policy)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(policy)
        return policy

    async def update(
        self,
        policy: DeadlinePolicy,
        *,
        label: dict | None = None,
        kind: str | None = None,
        absolute_at: datetime | None = None,
        offset_days: int | None = None,
    ) -> DeadlinePolicy:
        if label is not None:
            policy.label = label
        if kind is not None:
            policy.kind = kind
        # Set the value field matching the (possibly new) kind; clear the other.
        effective_kind = kind if kind is not None else policy.kind
        if effective_kind == "absolute":
            if absolute_at is not None:
                policy.absolute_at = absolute_at
            policy.offset_days = None
        else:
            if offset_days is not None:
                policy.offset_days = offset_days
            policy.absolute_at = None
        await self.session.commit()
        await self.session.refresh(policy)
        return policy

    async def delete(self, policy: DeadlinePolicy) -> None:
        await self.session.delete(policy)
        await self.session.commit()


def transition_ref(action_on_pass: dict | None) -> UUID | None:
    """Read the transition UUID from ``action_on_pass``.

    Defensive: missing/invalid value yields ``None`` (caller skips the row)."""
    if not action_on_pass:
        return None
    raw = action_on_pass.get("transitionId") or action_on_pass.get("transition_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None
