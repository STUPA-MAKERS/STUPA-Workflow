"""Deadline service: scans, locks and idempotency markers.

This module is the pure DB layer for the arq cron in `worker.deadlines`. The
worker holds the effect: it fires a transition, closes a vote or sends a
reminder.

Concurrency: each `lock_*` method selects one row with `FOR UPDATE SKIP LOCKED`.
A second worker gets `None` and skips the row, so nothing runs twice. The
persistent marker (`action_on_pass=NULL` or `reminded_at`) stops a repeat across
worker restarts.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deadlines.models import Deadline, DeadlinePolicy
from app.modules.voting.models import Vote
from app.settings import get_settings

# Cap per cron tick, oldest row first. A large backlog then drains over several
# ticks, and one tick does not overrun the 1-minute cadence. This does not change
# correctness, because SKIP LOCKED and the idempotency markers protect the run.
# A row that no worker takes stays due for the next tick.
DEFAULT_SCAN_LIMIT = 200

_RELATIVE_KINDS = frozenset({"relative_submitted", "relative_changed"})


def _is_relative(kind: str) -> bool:
    """Return whether `kind` adds a day offset to an application timestamp."""
    return kind in _RELATIVE_KINDS


class DeadlineService:
    """Deadline operations bound to an `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        kind: str,
        due_at: datetime,
        application_id: UUID | None = None,
        type_id: UUID | None = None,
        action_on_pass: dict | None = None,
    ) -> Deadline:
        """Create and store a deadline.

        This is a programmatic API. No HTTP route creates a deadline.
        """
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

    async def due_action_deadline_ids(
        self, now: datetime, *, limit: int = DEFAULT_SCAN_LIMIT
    ) -> list[UUID]:
        """List the ids of the due auto-deadlines.

        A deadline is due when `due_at` is at or before `now` and
        `action_on_pass` is set. The scan returns the oldest rows first and
        stops at `limit` rows.
        """
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
        """List the ids of deadlines that still need a reminder.

        The scan covers deadlines inside the lead window and deadlines that
        passed already. It has no lower bound (`due_at > now`) on purpose. If
        the worker was down longer than the lead window, a two-sided condition
        would never match the row again. The reminder would never go out and the
        row would leak in the partial index. With one bound the worker sends
        exactly one reminder, possibly late. `reminded_at` then takes the row
        out of the scan. The scan stops at `limit` rows.
        """
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
        """List the ids of open votes whose window has passed, up to `limit` rows."""
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

    async def lock_action_deadline(
        self, deadline_id: UUID, now: datetime
    ) -> Deadline | None:
        """Lock a due auto-deadline with `SKIP LOCKED`.

        Returns:
            The locked deadline. It returns `None` when another worker holds the
            row, or when a worker consumed the row already.
        """
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
        """Lock a deadline that still needs a reminder, with `SKIP LOCKED`.

        The condition mirrors `due_reminder_ids`. It has no lower bound, so a
        late reminder still goes out one time.
        """
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
        """Lock an open vote that has expired, with `SKIP LOCKED`."""
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

    async def consume_action(self, deadline: Deadline) -> None:
        """Mark an auto-deadline as fired with `action_on_pass=NULL` and commit.

        This takes the row out of the partial scan index. The deadline cannot
        fire a second time.
        """
        deadline.action_on_pass = None
        await self.session.commit()

    async def mark_reminded(self, deadline: Deadline, now: datetime) -> None:
        """Mark the reminder as sent with `reminded_at=now` and commit."""
        deadline.reminded_at = now
        await self.session.commit()


async def flow_deadline_passed(session: AsyncSession, application_id: UUID) -> bool:
    """Return whether a flow deadline is due, even if it is consumed already.

    A flow deadline always belongs to the current state of the application. The
    flow engine clears the old rows on every state change, in
    `schedule_state_deadline`. A due row therefore means that the deadline of
    the *current* state has passed. `FlowService._deadline_passed` and the
    task-mail recipient resolution share this function.
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


_HHMM_RE = re.compile(r"^(\d{2}):(\d{2})$")


def _parse_hhmm(raw: str | None) -> tuple[int, int] | None:
    """Parse a `"HH:MM"` string into `(hour, minute)`, or `None` if it is invalid."""
    m = _HHMM_RE.match(raw or "")
    if m is None:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    return (hh, mm) if hh <= 23 and mm <= 59 else None


def _zone(name: str | None) -> ZoneInfo:
    """Resolve an IANA zone name and fall back to the configured local timezone.

    An unknown or invalid name is not expected here, because the schemas
    validate the name on write. Such a name falls back to the local timezone
    and then to UTC. This function thus never raises.
    """
    for candidate in (name, get_settings().local_timezone):
        if candidate:
            try:
                return ZoneInfo(candidate)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return ZoneInfo("UTC")


def _snap_to_at_time(policy: DeadlinePolicy, dt: datetime) -> datetime:
    """Snap `dt` to the `policy.at_time` wall clock in `policy.timezone`.

    The result is DST-correct. The function reads the date in the target zone,
    combines it with `at_time` there and converts the result back to UTC. If
    `at_time` is unset or malformed, the function returns `dt` unchanged. That
    is the historical raw-instant behavior.
    """
    hhmm = _parse_hhmm(policy.at_time)
    if hhmm is None:
        return dt
    tz = _zone(policy.timezone)
    local_date = dt.astimezone(tz).date()
    local = datetime(
        local_date.year, local_date.month, local_date.day, hhmm[0], hhmm[1], tzinfo=tz
    )
    return local.astimezone(UTC)


def _combine_local_date(policy: DeadlinePolicy, day: date) -> datetime:
    """Combine a calendar day with the wall-clock time of the policy.

    The function uses `policy.at_time` in `policy.timezone`. If `at_time` is
    unset, it uses local midnight. It returns the UTC instant.
    """
    hhmm = _parse_hhmm(policy.at_time) or (0, 0)
    tz = _zone(policy.timezone)
    return datetime(
        day.year, day.month, day.day, hhmm[0], hhmm[1], tzinfo=tz
    ).astimezone(UTC)


def _recurring_due(policy: DeadlinePolicy, now: datetime | None) -> datetime | None:
    """Return the earliest of `policy.dates` that lies strictly after `now`.

    This gives a rolling window. The function returns `None` when every date
    has passed, or when `now` or `dates` is missing.
    """
    if now is None or not policy.dates:
        return None
    upcoming: list[datetime] = []
    for raw in policy.dates:
        if not isinstance(raw, str):
            continue
        try:
            day = date.fromisoformat(raw[:10])
        except ValueError:
            continue
        due = _combine_local_date(policy, day)
        if due > now:
            upcoming.append(due)
    return min(upcoming) if upcoming else None


def resolve_due_at(
    policy: DeadlinePolicy,
    *,
    now: datetime | None = None,
    submitted_at: datetime | None = None,
    changed_at: datetime | None = None,
) -> datetime | None:
    """Derive a concrete due date from a policy and the application timestamps.

    The function is pure. If `at_time` and `timezone` are set, the result snaps
    to a local wall-clock time and stays DST-correct. A `recurring` policy
    returns the earliest of `dates` that is still ahead of `now`.

    Returns:
        The due date. It returns `None` when a reference value is missing, for
        example `submitted_at`, or when a `recurring` schedule has no date left.
    """
    if policy.kind == "recurring":
        return _recurring_due(policy, now)
    if policy.kind == "absolute":
        return _snap_to_at_time(policy, policy.absolute_at) if policy.absolute_at else None
    days = policy.offset_days or 0
    if policy.kind == "relative_submitted":
        anchor = submitted_at
    elif policy.kind == "relative_changed":
        anchor = changed_at
    else:
        return None
    return _snap_to_at_time(policy, anchor + timedelta(days=days)) if anchor else None


class DeadlinePolicyError(Exception):
    """A policy invariant fails, for example a duplicate key.

    The API maps this error to 409 or 422.
    """


class DeadlinePolicyService:
    """CRUD for the named deadline policies. An admin maintains this registry."""

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
        at_time: str | None = None,
        timezone: str | None = None,
        dates: list | None = None,
    ) -> DeadlinePolicy:
        if await self.get_by_key(key):
            raise DeadlinePolicyError(f"deadline policy key already exists: {key!r}")
        policy = DeadlinePolicy(
            key=key,
            label=label,
            kind=kind,
            absolute_at=absolute_at if kind == "absolute" else None,
            offset_days=offset_days if _is_relative(kind) else None,
            at_time=at_time,
            timezone=timezone,
            dates=list(dates) if kind == "recurring" and dates else None,
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
        at_time: str | None = None,
        timezone: str | None = None,
        dates: list | None = None,
    ) -> DeadlinePolicy:
        if label is not None:
            policy.label = label
        if kind is not None:
            policy.kind = kind
        # The editor submits the whole form. The code therefore replaces the
        # wall-clock anchor completely, and `None` clears it. It is not a sparse
        # patch.
        policy.at_time = at_time
        policy.timezone = timezone
        # Set the value field that matches the new kind and clear the others.
        effective_kind = kind if kind is not None else policy.kind
        if effective_kind == "absolute":
            if absolute_at is not None:
                policy.absolute_at = absolute_at
            policy.offset_days = None
            policy.dates = None
        elif effective_kind == "recurring":
            policy.dates = list(dates) if dates else None
            policy.absolute_at = None
            policy.offset_days = None
        else:
            if offset_days is not None:
                policy.offset_days = offset_days
            policy.absolute_at = None
            policy.dates = None
        await self.session.commit()
        await self.session.refresh(policy)
        return policy

    async def delete(self, policy: DeadlinePolicy) -> None:
        await self.session.delete(policy)
        await self.session.commit()


def transition_ref(action_on_pass: dict | None) -> UUID | None:
    """Read the transition UUID from `action_on_pass`.

    The function is defensive. A missing or invalid value gives `None`, and the
    caller then skips the row.
    """
    if not action_on_pass:
        return None
    raw = action_on_pass.get("transitionId") or action_on_pass.get("transition_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None
