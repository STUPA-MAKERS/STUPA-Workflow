"""Unit tests for the periods of the Geschäftsordnung (specs 000917 to 000923)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pydantic import ValidationError

from app.main import create_app
from app.modules.admin.schemas import MeetingPeriods
from app.modules.gremien_overview.attendance_export import (
    AttendanceExport,
    ExportRow,
    export_workbook,
)
from app.modules.livevote.mails import get_meeting_mailer
from app.modules.livevote.router import (
    get_agenda_service,
    get_attendance_service,
    get_meeting_service,
    get_voting_service,
)
from app.modules.meetings.absence import AbsenceNotice
from app.modules.meetings.attendance_service import (
    AttendanceService,
    _open_window,
    late_excuse_until,
)
from app.modules.meetings.periods import kept_late_excuse_days, term_end, term_start
from app.shared.errors import ConflictError, ForbiddenError
from tests._support.flow_fakes import FakeSession, result
from tests.unit.modules.livevote.test_livevote_cov import (
    _FakeAgendaService,
    _FakeAttendanceService,
    _FakeMeetingService,
    _FakeVotingService,
    _login,
    _meeting_out,
)

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def fakes() -> dict[str, Any]:
    return {"meeting": _FakeMeetingService(), "attendance": _FakeAttendanceService()}


@pytest.fixture
def app(fakes: dict[str, Any]) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_meeting_service] = lambda: fakes["meeting"]
    application.dependency_overrides[get_attendance_service] = lambda: fakes["attendance"]
    application.dependency_overrides[get_agenda_service] = _FakeAgendaService
    application.dependency_overrides[get_voting_service] = _FakeVotingService
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize(
    ("today", "month", "start"),
    [
        (date(2026, 11, 14), 10, date(2026, 10, 1)),
        (date(2026, 3, 1), 10, date(2025, 10, 1)),
        (date(2026, 10, 1), 10, date(2026, 10, 1)),
        (date(2026, 3, 1), 1, date(2026, 1, 1)),
    ],
)
def test_term_runs_one_year_from_the_start_month(today: date, month: int, start: date) -> None:
    assert term_start(today, month) == start
    assert term_end(start) == date(start.year + 1, start.month, 1)


def test_absence_notice_tells_the_limit_from_the_warning() -> None:
    pid = uuid4()
    assert AbsenceNotice(pid, "A", 2, 3).reached is False
    assert AbsenceNotice(pid, "A", 3, 3).reached is True


def test_export_workbook_puts_members_and_substitutes_in_own_columns() -> None:
    export = AttendanceExport(
        gremium_name="STUPA",
        first=date(2026, 4, 1),
        last=date(2026, 9, 30),
        meetings=4,
        rows=(
            ExportRow(name="Ada", email="ada@x", kind="member", count=3),
            ExportRow(name="Ben", email="ben@x", kind="substitute", count=1),
        ),
    )
    sheet = load_workbook(BytesIO(export_workbook(export))).active
    assert sheet is not None
    rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    ada = next(row for row in rows if row[0] == "Ada")
    ben = next(row for row in rows if row[0] == "Ben")
    assert (ada[3], ben[4]) == (3, 1)
    assert any("01.04.2026 bis 30.09.2026" in str(cell) for row in rows for cell in row)


def _meeting(status: str = "closed", closed_at: datetime | None = NOW) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        gremium_id=uuid4(),
        status=status,
        date=None,
        start_time=None,
        started_at=None,
        closed_at=closed_at,
    )


def test_late_excuse_window_needs_a_closed_meeting() -> None:
    assert late_excuse_until(_meeting("live", None), 7) is None
    assert late_excuse_until(_meeting("closed", None), 7) is None
    assert late_excuse_until(_meeting(), 7) == NOW + timedelta(days=7)


def test_a_meeting_keeps_its_late_excuse_period() -> None:
    """§F/administration/admin/000942: the kept value wins over the setting."""
    assert kept_late_excuse_days(14, 2) == 14
    assert kept_late_excuse_days(None, 2) == 2
    assert kept_late_excuse_days(None, None) == 7


async def test_excuse_late_reads_the_period_of_the_meeting_not_the_setting() -> None:
    """The setting went down to 1 day after the meeting was made with 7 days."""
    meeting = _meeting()
    meeting.late_excuse_days = 7
    row = SimpleNamespace(status="absent", source="lead", note=None)
    session = _session(meeting, result(row), scalars=[uuid4()])
    service = AttendanceService(session)  # type: ignore[arg-type]
    assert await service._late_excuse_days(meeting) == 7
    late = NOW + timedelta(days=7, seconds=1)
    with pytest.raises(ConflictError) as error:
        await service.excuse_late(meeting.id, "me", "ill", now=late)
    assert error.value.code == "late_excuse_expired"


@pytest.mark.parametrize(
    "key", ["inviteDaysOrdinary", "inviteDaysExtraordinary", "lateExcuseDays", "circularMinDays"]
)
def test_a_period_of_0_days_is_refused(key: str) -> None:
    """§F/administration/admin/000942: each of these periods is 1 day or more."""
    values = {
        "inviteDaysOrdinary": 7,
        "inviteDaysExtraordinary": 3,
        "protocolDraftDays": 0,
        "lateExcuseDays": 7,
        "absenceLimit": 3,
        "circularMinDays": 3,
        "termStartMonth": 10,
    }
    assert MeetingPeriods.model_validate(values).protocol_draft_days == 0
    with pytest.raises(ValidationError):
        MeetingPeriods.model_validate({**values, key: 0})


def test_open_window_is_for_the_own_absence_only() -> None:
    until = NOW + timedelta(days=7)
    absent: Any = SimpleNamespace(status="absent")
    excused: Any = SimpleNamespace(status="excused")
    assert _open_window(absent, until, NOW, is_self=True) == until
    assert _open_window(absent, until, NOW, is_self=False) is None
    assert _open_window(None, until, NOW, is_self=True) is None
    assert _open_window(excused, until, NOW, is_self=True) is None
    assert _open_window(absent, None, NOW, is_self=True) is None
    assert _open_window(absent, until, until + timedelta(seconds=1), is_self=True) is None


def _session(meeting: Any, *results: Any, scalars: list[Any]) -> FakeSession:
    session = FakeSession([result(meeting), *results])
    session.scalar_results = scalars
    return session


async def test_excuse_late_needs_a_closed_meeting() -> None:
    meeting = _meeting("live", None)
    session = _session(meeting, scalars=[7])
    with pytest.raises(ConflictError) as error:
        await AttendanceService(session).excuse_late(meeting.id, "me", "ill", now=NOW)  # type: ignore[arg-type]
    assert error.value.code == "meeting_not_closed"


async def test_excuse_late_needs_an_account() -> None:
    meeting = _meeting()
    session = _session(meeting, scalars=[7, None])
    with pytest.raises(ForbiddenError):
        await AttendanceService(session).excuse_late(meeting.id, "me", "ill", now=NOW)  # type: ignore[arg-type]


@pytest.mark.parametrize("record", [None, "present"])
async def test_excuse_late_needs_an_absence(record: str | None) -> None:
    meeting = _meeting()
    row = None if record is None else SimpleNamespace(status=record, source="lead", note=None)
    session = _session(meeting, result(row) if row else result(), scalars=[None, uuid4()])
    with pytest.raises(ConflictError) as error:
        await AttendanceService(session).excuse_late(meeting.id, "me", "ill", now=NOW)  # type: ignore[arg-type]
    assert error.value.code == "not_absent"


async def test_excuse_late_ends_with_the_window() -> None:
    meeting = _meeting()
    row = SimpleNamespace(status="absent", source="lead", note=None)
    session = _session(meeting, result(row), scalars=[7, uuid4()])
    late = NOW + timedelta(days=7, seconds=1)
    with pytest.raises(ConflictError) as error:
        await AttendanceService(session).excuse_late(meeting.id, "me", "ill", now=late)  # type: ignore[arg-type]
    assert error.value.code == "late_excuse_expired"
    assert row.status == "absent"


class _Mailer:
    def __init__(self) -> None:
        self.meetings: list[UUID] = []

    async def absence_limit(self, _settings: Any, meeting_id: UUID, _pool: Any) -> None:
        self.meetings.append(meeting_id)

    async def late_excuse(self, _settings: Any, meeting_id: UUID, sub: str, _pool: Any) -> None:
        self.meetings.append(meeting_id)


@pytest.mark.parametrize(("status", "sent"), [("closed", 1), ("live", 0)])
def test_close_of_a_meeting_starts_the_absence_mail(
    app: FastAPI,
    client: TestClient,
    fakes: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    sent: int,
) -> None:
    mailer = _Mailer()
    app.dependency_overrides[get_meeting_mailer] = lambda: mailer
    fakes["meeting"]._meeting_out = _meeting_out(status=status)

    class _Protocols:
        def __init__(self, session: Any) -> None:
            self.session = session

        async def get_or_create(self, meeting_id: UUID, *, author: str) -> Any:
            return object()

    monkeypatch.setattr("app.modules.protocol.service.ProtocolService", _Protocols)
    _login(app)
    meeting_id = uuid4()
    response = client.patch(f"/api/meetings/{meeting_id}", json={"status": status})
    assert response.status_code == 200
    assert mailer.meetings == [meeting_id] * sent


def test_late_excuse_route_passes_the_reason(
    app: FastAPI,
    client: TestClient,
    fakes: dict[str, Any],
) -> None:
    calls: list[tuple[str, str, bool]] = []

    async def excuse_late(
        _meeting_id: UUID, sub: str, note: str, *, now: datetime, can_write: bool
    ) -> list[Any]:
        calls.append((sub, note, can_write))
        return []

    fakes["attendance"].excuse_late = excuse_late
    fakes["attendance"].session = fakes["meeting"].session
    mailer = _Mailer()
    app.dependency_overrides[get_meeting_mailer] = lambda: mailer
    _login(app)
    meeting_id = uuid4()
    url = f"/api/meetings/{meeting_id}/attendance/me/late-excuse"
    assert client.post(url, json={"note": "ill"}).status_code == 200
    assert calls == [("p", "ill", True)]
    assert client.post(url, json={"note": " "}).status_code == 422
    assert mailer.meetings == [meeting_id]
