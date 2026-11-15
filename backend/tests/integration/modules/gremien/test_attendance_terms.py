"""The unexcused count of a term, the late excuse in the member view and the export.

* ``GET /committees/{id}/attendance`` counts for each member the closed ordinary
  meetings of the current term with ``absent`` (§F/meetings/meetings/000920).
* ``GET /committees/{id}/attendance/{principalId}`` carries ``lateExcuseUntil`` on the
  own absence while the window is open (§F/meetings/meetings/000922).
* ``GET /committees/{id}/attendance/export.xlsx`` needs ``session.manage`` and gives one
  row per person, and an own row per pool substitute (§F/meetings/meetings/000923).
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import MeetingDelegation
from app.modules.gremien.models import Gremium, GremiumMembership, GremiumRole
from app.modules.meetings.models import Meeting, MeetingAttendance
from app.modules.meetings.periods import term_start
from tests.integration.modules.gremien.test_gremien_tab import _client, app_for, maker

__all__ = ["app_for", "maker"]

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Terms:
    gremium_id: uuid.UUID
    lead: Principal
    member: Principal
    ids: dict[str, uuid.UUID]
    start: date


async def _terms(maker: async_sessionmaker[AsyncSession]) -> Terms:
    """Seed a gremium with meetings in the current and in the last term.

    Anna is absent in two ordinary meetings of the current term and in one of the last
    term. The extraordinary meeting and the meeting with a vote transfer do not count.
    Pia holds a pool seat in one meeting.
    """
    tag = uuid.uuid4().hex[:8]
    start = term_start(datetime.now(UTC).date(), 10)
    async with maker() as s:
        g = Gremium(name=f"STUPA {tag}", slug=f"stupa-{tag}")
        s.add(g)
        await s.flush()
        lead_role = GremiumRole(
            gremium_id=g.id,
            key="lead",
            name_i18n={"de": "Vorsitz"},
            permissions=["session.manage"],
        )
        member_role = GremiumRole(
            gremium_id=g.id, key="member", name_i18n={"de": "Mitglied"}, permissions=["vote.cast"]
        )
        s.add_all([lead_role, member_role])
        people = {
            name: PrincipalRow(
                sub=f"{name}-{tag}", display_name=name.title(), email=f"{name}-{tag}@x.de"
            )
            for name in ("lea", "anna", "ben", "pia")
        }
        s.add_all(people.values())
        await s.flush()
        s.add_all(
            [
                GremiumMembership(
                    principal_id=people[name].id, gremium_id=g.id, gremium_role_id=role.id
                )
                for name, role in (("lea", lead_role), ("anna", member_role), ("ben", member_role))
            ]
        )
        closed = datetime.now(UTC) - timedelta(days=1)
        meetings = {
            key: Meeting(
                gremium_id=g.id,
                title=f"Sitzung {key}",
                date=day,
                status="closed",
                kind=kind,
                closed_at=closed if key != "old" else closed - timedelta(days=400),
            )
            for key, day, kind in (
                ("a", start + timedelta(days=1), "ordinary"),
                ("b", start + timedelta(days=2), "ordinary"),
                ("c", start + timedelta(days=3), "ordinary"),
                ("x", start + timedelta(days=4), "extraordinary"),
                ("old", start - timedelta(days=2), "ordinary"),
            )
        }
        s.add_all(meetings.values())
        await s.flush()

        def record(meeting: str, person: str, status: str) -> MeetingAttendance:
            return MeetingAttendance(
                meeting_id=meetings[meeting].id,
                principal_id=people[person].id,
                status=status,
                source="lead",
            )

        s.add_all(
            [
                record("a", "anna", "absent"),
                record("b", "anna", "absent"),
                record("c", "anna", "absent"),
                record("x", "anna", "absent"),
                record("old", "anna", "absent"),
                record("a", "ben", "present"),
                record("b", "ben", "present"),
                record("x", "ben", "present"),
                record("old", "ben", "present"),
                record("a", "lea", "present"),
                record("b", "pia", "present"),
                MeetingDelegation(
                    meeting_id=meetings["c"].id,
                    gremium_id=g.id,
                    delegator_principal_id=people["anna"].id,
                    delegate_principal_id=people["ben"].id,
                    delegate_voting=True,
                ),
                MeetingDelegation(
                    meeting_id=meetings["b"].id,
                    gremium_id=g.id,
                    delegator_principal_id=people["lea"].id,
                    delegate_principal_id=people["pia"].id,
                    delegate_voting=True,
                    via_pool=True,
                ),
            ]
        )
        await s.commit()
        return Terms(
            gremium_id=g.id,
            lead=Principal(sub=people["lea"].sub),
            member=Principal(sub=people["anna"].sub),
            ids={k: v.id for k, v in people.items()} | {k: v.id for k, v in meetings.items()},
            start=start,
        )


def _month_meetings(client: TestClient, url: str, months: list[str]) -> list[dict[str, Any]]:
    answers = [client.get(url, params={"month": month}).json() for month in months]
    return [meeting for answer in answers for meeting in answer["meetings"]]


async def test_attendance_counts_the_unexcused_absences_of_the_current_term(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    t = await _terms(maker)
    with _client(app_for, t.member) as client:
        resp = client.get(f"/api/committees/{t.gremium_id}/attendance")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["termStart"] == t.start.isoformat()
    assert body["absenceLimit"] == 3
    counts = {row["principalId"]: row["unexcused"] for row in body["rows"]}
    assert counts[str(t.ids["anna"])] == 2
    assert counts[str(t.ids["ben"])] == 0
    assert counts[str(t.ids["lea"])] == 0


async def test_member_view_offers_the_late_excuse_only_on_the_own_open_absence(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    t = await _terms(maker)
    months = sorted({(t.start + timedelta(days=n)).strftime("%Y-%m") for n in (1, 2, 3, 4)})
    old_month = (t.start - timedelta(days=2)).strftime("%Y-%m")
    url = f"/api/committees/{t.gremium_id}/attendance/{t.ids['anna']}"
    with _client(app_for, t.member) as client:
        own = _month_meetings(client, url, months)
        old = _month_meetings(client, url, [old_month])
    with _client(app_for, t.lead) as client:
        foreign = _month_meetings(client, url, months)
    until = {m["meetingId"]: m["lateExcuseUntil"] for m in own}
    assert until[str(t.ids["a"])] is not None
    assert until[str(t.ids["b"])] is not None
    assert until[str(t.ids["c"])] is None
    assert [m["lateExcuseUntil"] for m in old if m["meetingId"] == str(t.ids["old"])] == [None]
    assert all(m["lateExcuseUntil"] is None for m in foreign)


async def test_export_counts_present_meetings_and_pool_seats(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    t = await _terms(maker)
    url = f"/api/committees/{t.gremium_id}/attendance/export.xlsx"
    first = t.start.isoformat()
    last = (t.start + timedelta(days=30)).isoformat()
    with _client(app_for, t.member) as client:
        forbidden = client.get(url, params={"from": first, "to": last})
    with _client(app_for, t.lead) as client:
        resp = client.get(url, params={"from": first, "to": last})
        reversed_range = client.get(url, params={"from": last, "to": first})
        no_range = client.get(url)
    with _client(app_for, Principal(sub="nobody-here")) as client:
        hidden = client.get(url, params={"from": first, "to": last})
    assert forbidden.status_code == 403, forbidden.text
    assert hidden.status_code == 404, hidden.text
    assert reversed_range.status_code == 422, reversed_range.text
    assert reversed_range.json()["code"] == "invalid_date_range"
    assert no_range.status_code == 422, no_range.text
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-disposition"] == (
        f'attachment; filename="anwesenheit-{first}-{last}.xlsx"'
    )
    sheet = load_workbook(io.BytesIO(resp.content)).active
    assert sheet is not None
    cells = [tuple(row) for row in sheet.iter_rows(values_only=True)]
    table = cells[next(i for i, row in enumerate(cells) if row[0] == "Name") + 1 :]
    by_name = {(row[0], row[2]): (row[3] or None, row[4] or None) for row in table if row[0]}
    assert by_name[("Anna", "Mitglied")] == (None, None)
    assert by_name[("Ben", "Mitglied")] == (2, None)
    assert by_name[("Lea", "Mitglied")] == (1, None)
    assert by_name[("Pia", "Vertretung (Pool)")] == (None, 1)
    assert ("Pia", "Mitglied") not in by_name
    assert any("Ordentliche Sitzungen" in str(row[0]) and str(row[1]) == "3" for row in cells)
    async with maker() as s:
        audited = await s.scalars(
            select(AuditEntry).where(
                AuditEntry.action == "export", AuditEntry.target_id == "attendance.xlsx"
            )
        )
        assert any(e.data.get("gremiumId") == str(t.gremium_id) for e in audited.all())
