"""The report of the forced status changes (specs 001651, 001652).

The admin page "Erzwungene Status" counts the forced status changes of a period per
reason and per path (from state, to state), the largest count first, and lists the
applications behind a count. A path that admins force often is a way that the flow
does not have, so the count shows which transition to add.

A path groups by the keys of its two states, because a running application can sit on
an older version of the flow, whose state rows are different rows with the same key.
The label is the label of the newest state row with that key in the period.

A forced change from before the reason list has no reason key and counts as `none`
("Ohne Grund"). The period is a range of dates in Europe/Berlin, both days included.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.applications.models import Application, StatusEvent
from app.modules.flow.models import State
from app.shared.errors import ValidationProblem
from app.shared.i18n import I18nMap
from app.shared.schemas import FrozenCamelModel

BERLIN = ZoneInfo("Europe/Berlin")
#: The default period: the last 90 days.
DEFAULT_DAYS = 90
#: The key of a forced change without a reason.
NO_REASON = "none"
#: The most events that the list behind a count returns.
MAX_EVENTS = 500


class ReasonCount(FrozenCamelModel, frozen=True):
    """The count of one reason."""

    reason: str
    count: int


class PathCount(FrozenCamelModel, frozen=True):
    """The count of one path (from state, to state)."""

    from_key: str | None = Field(default=None, alias="fromKey")
    from_label: I18nMap | None = Field(default=None, alias="fromLabel")
    to_key: str = Field(alias="toKey")
    to_label: I18nMap | None = Field(default=None, alias="toLabel")
    count: int


class ForcedReportOut(FrozenCamelModel, frozen=True):
    """The counts of the forced status changes in a period."""

    date_from: date = Field(alias="from")
    date_to: date = Field(alias="to")
    total: int
    by_reason: list[ReasonCount] = Field(alias="byReason")
    by_path: list[PathCount] = Field(alias="byPath")


class ForcedEventOut(FrozenCamelModel, frozen=True):
    """One forced status change behind a count."""

    application_id: UUID = Field(alias="applicationId")
    title: str | None = None
    at: datetime
    reason: str
    note: str | None = None
    from_label: I18nMap | None = Field(default=None, alias="fromLabel")
    to_label: I18nMap | None = Field(default=None, alias="toLabel")


@dataclass(frozen=True, slots=True)
class _Row:
    """One forced event with its states, as the query reads it."""

    application_id: UUID
    title: str | None
    at: datetime
    reason: str
    note: str | None
    from_key: str | None
    from_label: I18nMap | None
    to_key: str
    to_label: I18nMap | None


def period(date_from: date | None, date_to: date | None, today: date) -> tuple[date, date]:
    """Resolve the period: the given days, else the last 90 days up to today (pure).

    Raises:
        ValidationProblem: The start lies after the end (422 `period_invalid`).
    """
    end = date_to or today
    start = date_from or end - timedelta(days=DEFAULT_DAYS)
    if start > end:
        msg = "The start of the period lies after its end."
        raise ValidationProblem(msg, code="period_invalid", errors=[{"field": "from", "msg": msg}])
    return start, end


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Return the instants of the period: the start of `start`, the end of `end`."""
    return (
        datetime.combine(start, time.min, BERLIN),
        datetime.combine(end + timedelta(days=1), time.min, BERLIN),
    )


async def _rows(session: AsyncSession, start: date, end: date) -> list[_Row]:
    """Read the forced events of the period with their states, the newest first."""
    lo, hi = _bounds(start, end)
    from_state = aliased(State)
    to_state = aliased(State)
    found = (
        await session.execute(
            select(
                StatusEvent.application_id,
                Application.data,
                StatusEvent.at,
                StatusEvent.force_reason,
                StatusEvent.note,
                from_state.key,
                from_state.label_i18n,
                to_state.key,
                to_state.label_i18n,
            )
            .join(Application, Application.id == StatusEvent.application_id)
            .outerjoin(from_state, from_state.id == StatusEvent.from_state_id)
            .join(to_state, to_state.id == StatusEvent.to_state_id)
            .where(StatusEvent.forced.is_(True), StatusEvent.at >= lo, StatusEvent.at < hi)
            .order_by(StatusEvent.at.desc())
        )
    ).all()
    return [
        _Row(
            application_id=app_id,
            title=_title(data),
            at=at,
            reason=reason or NO_REASON,
            note=note,
            from_key=from_key,
            from_label=from_label,
            to_key=to_key,
            to_label=to_label,
        )
        for app_id, data, at, reason, note, from_key, from_label, to_key, to_label in found
    ]


def _title(data: dict[str, Any] | None) -> str | None:
    """Read the title of an application from its data."""
    value = (data or {}).get("title")
    return value.strip() if isinstance(value, str) and value.strip() else None


def summarize(rows: list[_Row], start: date, end: date) -> ForcedReportOut:
    """Count the rows per reason and per path, the largest count first (pure).

    The rows come the newest first, so the first row of a path gives its labels.
    """
    reasons = Counter(r.reason for r in rows)
    paths = Counter((r.from_key, r.to_key) for r in rows)
    first = {(r.from_key, r.to_key): r for r in reversed(rows)}
    return ForcedReportOut.model_validate(
        {
            "from": start,
            "to": end,
            "total": len(rows),
            "byReason": [
                ReasonCount(reason=k, count=n)
                for k, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
            "byPath": [
                PathCount(
                    fromKey=k[0],
                    fromLabel=first[k].from_label,
                    toKey=k[1],
                    toLabel=first[k].to_label,
                    count=n,
                )
                for k, n in sorted(paths.items(), key=lambda kv: (-kv[1], kv[0][0] or "", kv[0][1]))
            ],
        }
    )


async def forced_report(session: AsyncSession, start: date, end: date) -> ForcedReportOut:
    """Count the forced status changes of a period."""
    return summarize(await _rows(session, start, end), start, end)


async def forced_events(
    session: AsyncSession,
    start: date,
    end: date,
    *,
    reason: str | None = None,
    from_key: str | None = None,
    to_key: str | None = None,
) -> list[ForcedEventOut]:
    """List the forced status changes behind a count, the newest first.

    `reason` narrows to one reason, `from_key` and `to_key` to one path. An empty
    `from_key` matches an event without a left state.
    """
    rows = [
        r
        for r in await _rows(session, start, end)
        if (reason is None or r.reason == reason)
        and (to_key is None or (r.to_key == to_key and (r.from_key or "") == (from_key or "")))
    ]
    return [
        ForcedEventOut(
            applicationId=r.application_id,
            title=r.title,
            at=r.at,
            reason=r.reason,
            note=r.note,
            fromLabel=r.from_label,
            toLabel=r.to_label,
        )
        for r in rows[:MAX_EVENTS]
    ]
