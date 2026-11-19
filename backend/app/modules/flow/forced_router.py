"""Admin routes of the report of the forced status changes (spec 001651).

Both routes need `audit.read`, because the report reads the forced changes of every
application and their notes, as the audit log does.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, require_principal
from app.modules.flow.forced_report import (
    BERLIN,
    ForcedEventOut,
    ForcedReportOut,
    forced_events,
    forced_report,
    period,
)
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["flow"], dependencies=[Depends(require_principal("audit.read"))])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_ERRORS: dict[int | str, dict[str, Any]] = dict.fromkeys((401, 403, 422), _PROBLEM)

FromQuery = Annotated[date | None, Query(alias="from")]
ToQuery = Annotated[date | None, Query(alias="to")]


def _today() -> date:
    return datetime.now(UTC).astimezone(BERLIN).date()


@router.get("/admin/forced-status", response_model=ForcedReportOut, responses=_ERRORS)
async def get_forced_report(
    db: DbSession, date_from: FromQuery = None, date_to: ToQuery = None
) -> ForcedReportOut:
    """Count the forced status changes per reason and per path; default: the last 90 days."""
    start, end = period(date_from, date_to, _today())
    return await forced_report(db, start, end)


@router.get(
    "/admin/forced-status/events", response_model=list[ForcedEventOut], responses=_ERRORS
)
async def get_forced_events(
    db: DbSession,
    date_from: FromQuery = None,
    date_to: ToQuery = None,
    reason: Annotated[str | None, Query(max_length=40)] = None,
    from_key: Annotated[str | None, Query(alias="fromKey", max_length=200)] = None,
    to_key: Annotated[str | None, Query(alias="toKey", max_length=200)] = None,
) -> list[ForcedEventOut]:
    """List the forced status changes behind a count of the report, the newest first."""
    start, end = period(date_from, date_to, _today())
    return await forced_events(
        db, start, end, reason=reason, from_key=from_key, to_key=to_key
    )
