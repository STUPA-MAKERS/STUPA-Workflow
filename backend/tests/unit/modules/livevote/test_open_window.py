"""The open window of a meeting and its settings.

A planned meeting opens at the earliest ``open_lead_minutes`` before its planned
start. Before ``confirm_lead_minutes`` the open needs ``confirmEarly``. A meeting
without a date, and a live or closed meeting, has no window. The settings service
validates the order of the two values and writes a ``config_change`` entry.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.modules.livevote import open_window as mod
from app.modules.livevote.models import Meeting, MeetingSettings
from app.modules.livevote.open_window import (
    MeetingSettingsService,
    OpenWindow,
    check_open,
    load_meeting_settings,
    open_window,
)
from app.shared.errors import ConflictError, ValidationProblem

TZ = "Europe/Berlin"


def _meeting(status: str = "planned", day: date | None = date(2026, 10, 20)) -> Meeting:
    m = Meeting(gremium_id=uuid4(), title="GV")
    m.status = status
    m.date = day
    m.start_time = time(18, 0)
    return m


def _settings(open_lead: int = 60, confirm_lead: int = 10) -> MeetingSettings:
    return MeetingSettings(id=1, open_lead_minutes=open_lead, confirm_lead_minutes=confirm_lead)


class _Session:
    def __init__(self, row: MeetingSettings | None = None) -> None:
        self.row = row
        self.added: list[Any] = []
        self.commits = 0

    async def get(self, _model: Any, _ident: Any) -> MeetingSettings | None:
        return self.row

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        self.row = obj

    async def flush(self) -> None: ...

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj: Any) -> None: ...


def test_window_counts_back_from_the_local_start() -> None:
    """Count the window back from the local start.

    18:00 in Berlin in October (CEST) is 16:00 UTC.
    """
    window = open_window(_meeting(), _settings(), TZ)
    assert window == OpenWindow(
        opens_at=datetime(2026, 10, 20, 15, 0, tzinfo=UTC),
        confirm_until=datetime(2026, 10, 20, 15, 50, tzinfo=UTC),
    )


def test_window_without_start_time_starts_at_midnight() -> None:
    m = _meeting()
    m.start_time = None
    window = open_window(m, _settings(30, 0), TZ)
    assert window is not None
    assert window.confirm_until == datetime(2026, 10, 19, 22, 0, tzinfo=UTC)
    assert window.opens_at == window.confirm_until - timedelta(minutes=30)


@pytest.mark.parametrize(
    "meeting", [_meeting("live"), _meeting("closed"), _meeting(day=None)]
)
def test_no_window(meeting: Meeting) -> None:
    assert open_window(meeting, _settings(), TZ) is None


def test_check_open() -> None:
    w = OpenWindow(
        opens_at=datetime(2026, 10, 20, 15, 0, tzinfo=UTC),
        confirm_until=datetime(2026, 10, 20, 15, 50, tzinfo=UTC),
    )
    check_open(None, now=datetime(2000, 1, 1, tzinfo=UTC), confirmed=False)
    with pytest.raises(ConflictError) as ei:
        check_open(w, now=w.opens_at - timedelta(seconds=1), confirmed=True)
    assert ei.value.code == "meeting_too_early"
    with pytest.raises(ConflictError) as ei:
        check_open(w, now=w.opens_at, confirmed=False)
    assert ei.value.code == "early_open_unconfirmed"
    check_open(w, now=w.opens_at, confirmed=True)
    check_open(w, now=w.confirm_until, confirmed=False)
    check_open(w, now=w.confirm_until + timedelta(days=1), confirmed=False)


async def test_load_falls_back_to_the_defaults() -> None:
    row = await load_meeting_settings(_Session())  # type: ignore[arg-type]
    assert (row.open_lead_minutes, row.confirm_lead_minutes) == (60, 10)
    stored = _settings(90, 15)
    assert await load_meeting_settings(_Session(stored)) is stored  # type: ignore[arg-type]


async def test_update_creates_the_row_and_audits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def _record(_session: Any, **kw: Any) -> None:
        calls.append(kw)

    monkeypatch.setattr(mod, "audit_record", _record)
    session = _Session()
    row = await MeetingSettingsService(session).update(  # type: ignore[arg-type]
        open_lead_minutes=120, confirm_lead_minutes=30, actor="adm"
    )
    assert (row.open_lead_minutes, row.confirm_lead_minutes) == (120, 30)
    assert row.updated_by == "adm"
    assert session.added == [row]
    assert session.commits == 1
    [entry] = calls
    assert entry["target_type"] == "meeting_settings"
    assert entry["data"] == {
        "openLeadMinutes": {"from": 60, "to": 120},
        "confirmLeadMinutes": {"from": 10, "to": 30},
    }


async def test_update_refuses_a_confirm_point_before_the_open() -> None:
    session = _Session(_settings())
    with pytest.raises(ValidationProblem):
        await MeetingSettingsService(session).update(  # type: ignore[arg-type]
            open_lead_minutes=10, confirm_lead_minutes=20, actor="adm"
        )
    assert session.commits == 0
    assert session.row is not None
    assert session.row.open_lead_minutes == 60
