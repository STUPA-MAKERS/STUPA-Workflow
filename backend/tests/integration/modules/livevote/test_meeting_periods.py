"""The periods of the Geschäftsordnung through the real API.

* ``GET/PUT /admin/meeting-periods`` hold the seven periods with their start values,
  check the bounds and write a ``config_change`` (§F/administration/admin/000917).
* ``GET /committees/{id}/meeting-defaults`` gives the invitation periods to the meeting
  form (§F/meetings/meetings/000918).
* A member changes the own ``absent`` of a closed meeting to ``excused`` with a reason,
  until ``lateExcuseDays`` days after the close (§F/meetings/meetings/000922).
* The close of an ordinary meeting mails the persons with ``session.manage`` when a
  member reaches the limit minus 1 or the limit (§F/meetings/meetings/000921).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_principal
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import MeetingDelegation
from app.modules.gremien.models import GremiumMembership, GremiumRole
from app.modules.livevote import mails as meeting_mails
from app.modules.livevote.mails import MeetingMailer, get_meeting_mailer
from app.modules.livevote.open_window import load_meeting_settings
from app.modules.meetings.absence import absence_notices
from app.modules.meetings.models import Meeting, MeetingAttendance
from app.settings import Settings, load_settings
from tests.integration.modules.livevote.conftest import admin, audit_actions, seed

pytestmark = pytest.mark.integration

DEFAULTS = {
    "inviteDaysOrdinary": 7,
    "inviteDaysExtraordinary": 3,
    "protocolDraftDays": 14,
    "lateExcuseDays": 7,
    "absenceLimit": 3,
    "circularMinDays": 3,
    "termStartMonth": 10,
}
URL = "/api/admin/meeting-periods"


async def _member(
    maker: async_sessionmaker[AsyncSession],
    gremium_id: uuid.UUID,
    name: str,
    permissions: tuple[str, ...] = ("vote.cast",),
) -> tuple[str, uuid.UUID]:
    """Write a member of the gremium with the permissions and return sub and id."""
    sub = f"{name}-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        row = PrincipalRow(sub=sub, display_name=name, email=f"{sub}@x.de")
        role = GremiumRole(
            gremium_id=gremium_id,
            key=f"r-{sub}",
            name_i18n={"de": "Rolle"},
            permissions=list(permissions),
        )
        session.add_all([row, role])
        await session.flush()
        session.add(
            GremiumMembership(principal_id=row.id, gremium_id=gremium_id, gremium_role_id=role.id)
        )
        await session.commit()
    return sub, row.id


async def _closed_meeting(
    maker: async_sessionmaker[AsyncSession],
    gremium_id: uuid.UUID,
    day: date,
    absent: tuple[uuid.UUID, ...],
    *,
    kind: str = "ordinary",
    closed_at: datetime | None = None,
) -> uuid.UUID:
    """Write a closed meeting of the gremium with ``absent`` records."""
    async with maker() as session:
        meeting = Meeting(
            gremium_id=gremium_id,
            title=f"Sitzung {day.isoformat()}",
            date=day,
            status="closed",
            kind=kind,
            closed_at=closed_at or datetime.now(UTC),
        )
        session.add(meeting)
        await session.flush()
        session.add_all(
            [
                MeetingAttendance(
                    meeting_id=meeting.id, principal_id=pid, status="absent", source="lead"
                )
                for pid in absent
            ]
        )
        await session.commit()
        return meeting.id


def _settings(url: str) -> Settings:
    return load_settings(
        database_url=url,
        session_secret="session-secret-meeting-p5a-000",
        magic_link_secret="magic-link-secret-meeting-p5a0",
        cookie_secure=False,
    )


def _as(api: FastAPI, sub: str | None) -> None:
    api.dependency_overrides[get_current_principal] = (
        admin if sub is None else (lambda: Principal(sub=sub))
    )


def test_periods_start_values_update_bounds_and_audit(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    changed = {**DEFAULTS, "inviteDaysOrdinary": 10, "absenceLimit": 4}
    with TestClient(api) as client:
        try:
            start = client.get(URL)
            saved = client.put(URL, json=changed)
            read = client.get(URL)
            bad_month = client.put(URL, json={**DEFAULTS, "termStartMonth": 13})
            bad_limit = client.put(URL, json={**DEFAULTS, "absenceLimit": 0})
            missing = client.put(URL, json={"inviteDaysOrdinary": 7})
            api.dependency_overrides[get_current_principal] = lambda: Principal(
                sub="site-admin", roles=[], permissions={"admin.site"}
            )
            forbidden_get = client.get(URL)
            forbidden_put = client.put(URL, json=DEFAULTS)
        finally:
            _as(api, None)
            assert client.put(URL, json=DEFAULTS).status_code == 200
    assert start.status_code == 200, start.text
    assert start.json() == DEFAULTS
    assert saved.status_code == 200, saved.text
    assert read.json() == changed
    assert bad_month.status_code == 422, bad_month.text
    assert bad_limit.status_code == 422, bad_limit.text
    assert missing.status_code == 422, missing.text
    assert forbidden_get.status_code == 403, forbidden_get.text
    assert forbidden_put.status_code == 403, forbidden_put.text


async def test_periods_change_writes_a_config_change(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    with TestClient(api) as client:
        try:
            assert client.put(URL, json={**DEFAULTS, "lateExcuseDays": 9}).status_code == 200
        finally:
            assert client.put(URL, json=DEFAULTS).status_code == 200
    diffs = [
        e.data["periods"]
        for e in await audit_actions(maker, target_id=None)
        if e.action == "config_change" and "periods" in e.data
    ]
    assert {"lateExcuseDays": {"from": 7, "to": 9}} in diffs
    assert {"lateExcuseDays": {"from": 9, "to": 7}} in diffs


async def test_meeting_defaults_carry_the_invitation_periods(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    s = await seed(maker, status="planned", items=0)
    with TestClient(api) as client:
        resp = client.get(f"/api/committees/{s.gremium_id}/meeting-defaults")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["inviteDaysOrdinary"], body["inviteDaysExtraordinary"]) == (7, 3)


async def test_late_excuse_needs_a_reason_and_the_open_window(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    s = await seed(maker, status="live", items=0)
    sub, pid = await _member(maker, s.gremium_id, "Anna")
    other_sub, _ = await _member(maker, s.gremium_id, "Ben")
    url = f"/api/meetings/{s.meeting_id}/attendance/me/late-excuse"
    with TestClient(api) as client:
        lead = client.put(
            f"/api/meetings/{s.meeting_id}/attendance/{pid}", json={"status": "absent"}
        )
        _as(api, sub)
        too_early = client.post(url, json={"note": "Krank"})
        _as(api, None)
        closed = client.patch(f"/api/meetings/{s.meeting_id}", json={"status": "closed"})
        _as(api, sub)
        roster = client.get(f"/api/meetings/{s.meeting_id}/attendance")
        no_note = client.post(url, json={"note": "   "})
        _as(api, other_sub)
        not_absent = client.post(url, json={"note": "Krank"})
        other_roster = client.get(f"/api/meetings/{s.meeting_id}/attendance")
        _as(api, sub)
        excused = client.post(url, json={"note": " Krank "})
        again = client.post(url, json={"note": "Krank"})
    assert lead.status_code == 200, lead.text
    assert too_early.status_code == 409, too_early.text
    assert too_early.json()["code"] == "meeting_not_closed"
    assert closed.status_code == 200, closed.text
    mine = next(r for r in roster.json() if r["principalId"] == str(pid))
    assert mine["lateExcuseUntil"] is not None
    assert all(r["lateExcuseUntil"] is None for r in other_roster.json())
    assert no_note.status_code == 422, no_note.text
    assert not_absent.status_code == 409, not_absent.text
    assert not_absent.json()["code"] == "not_absent"
    assert excused.status_code == 200, excused.text
    row = next(r for r in excused.json() if r["principalId"] == str(pid))
    assert (row["status"], row["source"], row["note"], row["lateExcuseUntil"]) == (
        "excused",
        "self",
        "Krank",
        None,
    )
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "not_absent"
    late = [
        e
        for e in await audit_actions(maker, target_id=s.meeting_id)
        if e.action == "attendance_set" and e.data.get("late") is True
    ]
    assert len(late) == 1
    assert "Krank" not in str(late[0].data)


async def test_late_excuse_after_the_period_gives_409(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    s = await seed(maker, status="planned", items=0)
    sub, pid = await _member(maker, s.gremium_id, "Anna")
    old = await _closed_meeting(
        maker,
        s.gremium_id,
        date(2026, 5, 5),
        (pid,),
        closed_at=datetime.now(UTC) - timedelta(days=8),
    )
    _as(api, sub)
    with TestClient(api) as client:
        roster = client.get(f"/api/meetings/{old}/attendance")
        resp = client.post(f"/api/meetings/{old}/attendance/me/late-excuse", json={"note": "Krank"})
        outsider = Principal(sub="nobody-here")
        api.dependency_overrides[get_current_principal] = lambda: outsider
        foreign = client.post(
            f"/api/meetings/{old}/attendance/me/late-excuse", json={"note": "Krank"}
        )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "late_excuse_expired"
    mine = next(r for r in roster.json() if r["principalId"] == str(pid))
    assert mine["lateExcuseUntil"] is None
    assert foreign.status_code in (403, 404), foreign.text


class _Mailer(MeetingMailer):
    """Record the absence notices of a close in place of the mail."""

    def __init__(self) -> None:
        self.closed: list[uuid.UUID] = []

    async def absence_limit(self, settings: Any, meeting_id: uuid.UUID, pool: object) -> None:
        self.closed.append(meeting_id)

    async def meeting_created(self, settings: Any, meeting_id: uuid.UUID, pool: object) -> None:
        return None


class _Queue:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def enqueue(self, message: Any) -> None:
        self.messages.append(message)


async def test_close_mails_the_managers_when_a_member_nears_the_limit(
    api: FastAPI,
    maker: async_sessionmaker[AsyncSession],
    migrated: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close a meeting with an absent member and mail the persons with ``session.manage``.

    Anna has one unexcused absence in the term, so the absence in this meeting is the
    limit minus 1. Ben is absent for the first time and gives no notice. Cem transferred
    the vote, so the absence does not count.
    """
    s = await seed(maker, status="live", items=0)
    _, anna = await _member(maker, s.gremium_id, "Anna")
    _, ben = await _member(maker, s.gremium_id, "Ben")
    _, cem = await _member(maker, s.gremium_id, "Cem")
    lead_sub, lead = await _member(maker, s.gremium_id, "Lea", ("session.manage",))
    await _closed_meeting(maker, s.gremium_id, date(2026, 5, 5), (anna, cem))
    await _closed_meeting(maker, s.gremium_id, date(2025, 9, 30), (anna, ben))
    await _closed_meeting(maker, s.gremium_id, date(2026, 5, 12), (ben,), kind="extraordinary")
    async with maker() as session:
        session.add(
            MeetingDelegation(
                meeting_id=s.meeting_id,
                gremium_id=s.gremium_id,
                delegator_principal_id=cem,
                delegate_principal_id=lead,
                delegate_voting=True,
            )
        )
        session.add_all(
            [
                MeetingAttendance(
                    meeting_id=s.meeting_id, principal_id=pid, status="absent", source="lead"
                )
                for pid in (anna, ben, cem)
            ]
        )
        await session.commit()
    mailer = _Mailer()
    api.dependency_overrides[get_meeting_mailer] = lambda: mailer
    with TestClient(api) as client:
        closed = client.patch(f"/api/meetings/{s.meeting_id}", json={"status": "closed"})
    assert closed.status_code == 200, closed.text
    assert mailer.closed == [s.meeting_id]

    async with maker() as session:
        meeting = await session.get(Meeting, s.meeting_id)
        settings_row = await load_meeting_settings(session)
        assert meeting is not None
        notices = await absence_notices(session, meeting, settings_row)
    assert [(n.principal_id, n.count, n.limit, n.reached) for n in notices] == [
        (anna, 2, 3, False)
    ]

    queue = _Queue()
    monkeypatch.setattr(meeting_mails, "get_sessionmaker", lambda: maker)
    monkeypatch.setattr(meeting_mails, "mail_queue_from_pool", lambda _pool: queue)
    settings = _settings(migrated[1])
    await MeetingMailer().absence_limit(settings, s.meeting_id, pool=object())
    await MeetingMailer().absence_limit(settings, uuid.uuid4(), pool=object())
    assert len(queue.messages) == 1
    message = queue.messages[0]
    assert message.to == (f"{lead_sub}@x.de",)
    assert "Anna" in message.text
    assert "2" in message.text


async def test_third_absence_reaches_the_limit_and_no_manager_means_no_mail(
    maker: async_sessionmaker[AsyncSession],
    migrated: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await seed(maker, status="planned", items=0)
    _, anna = await _member(maker, s.gremium_id, "Anna")
    await _closed_meeting(maker, s.gremium_id, date(2026, 4, 7), (anna,))
    await _closed_meeting(maker, s.gremium_id, date(2026, 4, 21), (anna,))
    third = await _closed_meeting(maker, s.gremium_id, date(2026, 5, 5), (anna,))
    special = await _closed_meeting(
        maker, s.gremium_id, date(2026, 5, 6), (anna,), kind="extraordinary"
    )
    quiet = await _closed_meeting(maker, s.gremium_id, date(2026, 5, 7), ())
    async with maker() as session:
        settings_row = await load_meeting_settings(session)
        reached = await absence_notices(
            session, await session.get_one(Meeting, third), settings_row
        )
        none_special = await absence_notices(
            session, await session.get_one(Meeting, special), settings_row
        )
        none_quiet = await absence_notices(
            session, await session.get_one(Meeting, quiet), settings_row
        )
        planned = await absence_notices(
            session, await session.get_one(Meeting, s.meeting_id), settings_row
        )
    assert [(n.count, n.reached) for n in reached] == [(3, True)]
    assert none_special == []
    assert none_quiet == []
    assert planned == []

    queue = _Queue()
    monkeypatch.setattr(meeting_mails, "get_sessionmaker", lambda: maker)
    monkeypatch.setattr(meeting_mails, "mail_queue_from_pool", lambda _pool: queue)
    await MeetingMailer().absence_limit(_settings(migrated[1]), third, pool=object())
    assert queue.messages == []
