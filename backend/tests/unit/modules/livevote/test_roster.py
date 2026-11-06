"""Unit tests for the planned start and the roster clause of a meeting."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.modules.livevote.roster import (
    meeting_roster_filter,
    planned_start_utc,
    roster_filter,
)

TZ = "Europe/Berlin"


def _meeting(**kw: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "gremium_id": uuid4(),
        "status": "closed",
        "date": date(2026, 7, 15),
        "start_time": time(18, 10),
        "started_at": None,
        "closed_at": None,
    }
    base.update(kw)
    return cast(Any, SimpleNamespace(**base))


def test_planned_start_is_local_time_in_utc() -> None:
    assert planned_start_utc(_meeting(), TZ) == datetime(2026, 7, 15, 16, 10, tzinfo=UTC)
    assert planned_start_utc(_meeting(date=None), TZ) is None
    midnight = planned_start_utc(_meeting(start_time=None), TZ)
    assert midnight == datetime(2026, 7, 14, 22, 0, tzinfo=UTC)


def _sql(clause: Any) -> str:
    return str(clause.compile(dialect=postgresql.dialect()))


def test_roster_filter_unions_members_and_records() -> None:
    sql = _sql(meeting_roster_filter(_meeting()))
    assert "gremium_membership" in sql
    assert "meeting_attendance" in sql
    assert " OR " in sql


def test_roster_filter_without_meeting_reads_memberships_only() -> None:
    sql = _sql(roster_filter(uuid4()))
    assert "gremium_membership" in sql
    assert "meeting_attendance" not in sql
