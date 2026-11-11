"""Integration: the external calendars (specs 000711, 000721-000724, 000729).

Covers the admin writes, the fetch of the worker with a fake fetcher, the entries that
stay after a failed fetch, the read scope of a calendar for all and of a Gremium
calendar, the entries of the Kalender page, the search, the dialog read and the feed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.calendar import service
from app.modules.calendar.external import ExternalCalendarService
from app.modules.calendar.external_fetch import Fetched
from app.modules.calendar.ics import build_calendar
from app.modules.calendar.models import ExternalCalendar, ExternalEntry
from tests.integration.modules.calendar.conftest import CalendarApi
from tests.integration.modules.todos.conftest import add_gremium, add_member, add_person
from worker.calendars import fetch_external_calendars

pytestmark = pytest.mark.integration

NOW = datetime(2031, 5, 2, 9, 0, tzinfo=UTC)
FEED = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:a
DTSTART;TZID=Europe/Berlin:20310505T180000
DTEND;TZID=Europe/Berlin:20310505T193000
RRULE:FREQ=WEEKLY;COUNT=2
SUMMARY:Senat
LOCATION:Aula
DESCRIPTION:<p>Offen</p>
ATTENDEE:mailto:paul@example.org
END:VEVENT
BEGIN:VEVENT
UID:b
DTSTART;VALUE=DATE:20310520
SUMMARY:Vorlesungsfrei
END:VEVENT
END:VCALENDAR
"""
ADMIN = Principal(sub="admin-x", permissions={"admin.calendars"})


@pytest.fixture(autouse=True)
async def _no_calendars(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    """Remove the external calendars before and after a test: no other fixture owns them."""

    async def _clear() -> None:
        async with maker() as session:
            await session.execute(delete(ExternalCalendar))
            await session.commit()

    await _clear()
    yield
    await _clear()


@dataclass
class FakeFetcher:
    """Answer each address with a prepared result and record the addresses."""

    results: dict[str, Fetched]
    seen: list[str] = field(default_factory=list)

    async def fetch(self, url: str) -> Fetched:
        self.seen.append(url)
        return self.results[url]


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _subscribe(client: TestClient, name: str, **body: Any) -> dict[str, Any]:
    data = {"name": name, "url": f"https://feeds.example.org/{name}.ics", **body}
    return _ok(client.post("/api/admin/calendars", json=data), 201)


async def _fetch(
    maker: async_sessionmaker[AsyncSession], fetcher: FakeFetcher, now: datetime = NOW
) -> int:
    return await fetch_external_calendars(
        {"calendars_sessionmaker": maker, "calendars_fetcher": fetcher}, now
    )


def _entries(client: TestClient) -> list[dict[str, Any]]:
    query = {"from": "2031-05-01", "to": "2031-05-31"}
    items = _ok(client.get("/api/calendar/entries", params=query))["items"]
    return [item for item in items if item["kind"] == "external"]


async def test_admin_subscribes_changes_and_deletes(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """§F/meetings/calendar/000729: the list, the dialog rules and the delete with entries."""
    gremium_id, _ = await add_gremium(maker, "Senat")
    api.login(ADMIN)
    with TestClient(api.app) as client:
        made = _subscribe(client, "uni")
        assert (made["intervalMinutes"], made["gremiumId"], made["entryCount"]) == (60, None, 0)
        assert made["lastAttemptAt"] is None and made["lastError"] is None
        for bad in (
            {"url": "http://feeds.example.org/a.ics"},
            {"url": "https://feeds.example.org/a b.ics"},
            {"name": "   "},
            {"intervalMinutes": 30},
            {"gremiumId": str(uuid.uuid4())},
        ):
            _ok(client.post("/api/admin/calendars", json={**made, **bad}), 422)
        fetcher = FakeFetcher({made["url"]: Fetched(data=FEED)})
        assert await _fetch(maker, fetcher) == 1
        body = {
            "name": " Senat ",
            "url": made["url"],
            "gremiumId": str(gremium_id),
            "intervalMinutes": 15,
        }
        changed = _ok(client.put(f"/api/admin/calendars/{made['id']}", json=body))
        assert (changed["name"], changed["gremiumName"], changed["intervalMinutes"]) == (
            "Senat",
            "Senat",
            15,
        )
        assert changed["entryCount"] == 3 and changed["lastSuccessAt"] is not None
        assert [row["id"] for row in _ok(client.get("/api/admin/calendars"))] == [made["id"]]
        missing = f"/api/admin/calendars/{uuid.uuid4()}"
        _ok(client.put(missing, json=body), 404)
        _ok(client.delete(missing), 404)
        _ok(client.post(f"{missing}/fetch"), 404)
        _ok(client.delete(f"/api/admin/calendars/{made['id']}"), 204)
    async with maker() as session:
        assert await session.scalar(select(func.count()).select_from(ExternalEntry)) == 0
        assert await session.scalar(select(func.count()).select_from(ExternalCalendar)) == 0


async def test_worker_fetches_when_due(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """§F/meetings/calendar/000722: the interval, a new address and "Jetzt abrufen"."""
    api.login(ADMIN)
    with TestClient(api.app) as client:
        made = _subscribe(client, "uni")
        other = "https://feeds.example.org/neu.ics"
        fetcher = FakeFetcher({made["url"]: Fetched(data=FEED), other: Fetched(data=FEED)})
        assert await _fetch(maker, fetcher) == 1
        assert await _fetch(maker, fetcher, NOW + timedelta(minutes=59)) == 0
        assert await _fetch(maker, fetcher, NOW + timedelta(minutes=60)) == 1
        assert fetcher.seen == [made["url"]] * 2
        later = NOW + timedelta(minutes=61)
        same = {"name": "uni", "url": made["url"], "intervalMinutes": 1440}
        _ok(client.put(f"/api/admin/calendars/{made['id']}", json=same))
        assert await _fetch(maker, fetcher, later) == 0
        _ok(client.put(f"/api/admin/calendars/{made['id']}", json={**same, "url": other}))
        assert await _fetch(maker, fetcher, datetime.now(UTC)) == 1
        assert fetcher.seen[-1] == other
        assert await _fetch(maker, fetcher, datetime.now(UTC)) == 0
        _ok(client.post(f"/api/admin/calendars/{made['id']}/fetch"))
        assert await _fetch(maker, fetcher, datetime.now(UTC)) == 1


async def test_failed_fetch_keeps_the_old_entries(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """§F/meetings/calendar/000722: the entries stay, the page shows the time and the cause."""
    anna, _ = await add_person(maker, "Anna")
    api.login(ADMIN)
    with TestClient(api.app) as client:
        made = _subscribe(client, "uni")
        results = {made["url"]: Fetched(data=FEED)}
        fetcher = FakeFetcher(results)
        assert await _fetch(maker, fetcher) == 1
        for at, result, cause in (
            (1, Fetched(error="timeout"), "timeout"),
            (2, Fetched(data=b"<html>Login</html>"), "format"),
            (3, Fetched(), "unreachable"),
        ):
            results[made["url"]] = result
            assert await _fetch(maker, fetcher, NOW + timedelta(hours=at)) == 0
            row = _ok(client.get("/api/admin/calendars"))[0]
            assert (row["lastError"], row["entryCount"]) == (cause, 3)
            assert row["lastSuccessAt"] < row["lastAttemptAt"]
        api.login(anna)
        assert [e["title"] for e in _entries(client)] == ["Senat", "Senat", "Vorlesungsfrei"]
        api.login(ADMIN)
        results[made["url"]] = Fetched(data=FEED.replace(b"Vorlesungsfrei", b"Ferien"))
        assert await _fetch(maker, fetcher, NOW + timedelta(hours=4)) == 1
        row = _ok(client.get("/api/admin/calendars"))[0]
        assert row["lastError"] is None and row["lastSuccessAt"] == row["lastAttemptAt"]
        api.login(anna)
        assert [e["title"] for e in _entries(client)] == ["Senat", "Senat", "Ferien"]


async def test_crashing_fetcher_does_not_stop_the_run(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    api.login(ADMIN)
    with TestClient(api.app) as client:
        first = _subscribe(client, "a")
        second = _subscribe(client, "b")
    fetcher = FakeFetcher({second["url"]: Fetched(data=FEED)})
    assert await _fetch(maker, fetcher) == 1
    assert sorted(fetcher.seen) == [first["url"], second["url"]]


async def test_empty_feed_and_unknown_calendar(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """A feed without events removes the entries; a calendar that is gone gives False."""
    api.login(ADMIN)
    with TestClient(api.app) as client:
        made = _subscribe(client, "uni")
        results = {made["url"]: Fetched(data=FEED)}
        fetcher = FakeFetcher(results)
        assert await _fetch(maker, fetcher) == 1
        results[made["url"]] = Fetched(data=b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n")
        assert await _fetch(maker, fetcher, NOW + timedelta(hours=1)) == 1
        assert _ok(client.get("/api/admin/calendars"))[0]["entryCount"] == 0
    async with maker() as session:
        gone = await ExternalCalendarService(session).refresh(uuid.uuid4(), fetcher, NOW)
        assert gone is False


async def test_scope_of_a_gremium_calendar(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """§F/meetings/calendar/000721 and 000711: a non-member does not find the entry."""
    gremium_id, _ = await add_gremium(maker, "Senat")
    member, member_id = await add_person(maker, "Mia")
    outsider, outsider_id = await add_person(maker, "Otto")
    await add_member(maker, gremium_id, member_id)
    api.login(ADMIN)
    with TestClient(api.app) as client:
        for_all = _subscribe(client, "uni")
        scoped = _subscribe(client, "senat", gremiumId=str(gremium_id))
        feed = FEED.replace(b"Senat", b"Intern").replace(b"Vorlesungsfrei", b"Klausur")
        fetcher = FakeFetcher(
            {for_all["url"]: Fetched(data=FEED), scoped["url"]: Fetched(data=feed)}
        )
        assert await _fetch(maker, fetcher) == 2

        api.login(member)
        seen = _entries(client)
        titles = sorted({e["title"] for e in seen})
        assert titles == ["Intern", "Klausur", "Senat", "Vorlesungsfrei"]
        intern = next(e for e in seen if e["title"] == "Intern")
        assert (intern["source"], intern["gremiumIds"], intern["place"]) == (
            "senat",
            [str(gremium_id)],
            "Aula",
        )
        assert (intern["startTime"], intern["endTime"], intern["mine"]) == (
            "18:00:00",
            "19:30:00",
            False,
        )
        detail = _ok(client.get(f"/api/calendar/external/{intern['id']}"))
        assert (detail["calendar"], detail["description"]) == ("senat", "Offen")
        assert "url" not in detail and "example.org" not in str(detail)
        hits = _ok(client.get("/api/calendar/search", params={"q": "aula"}))["items"]
        assert sorted({h["title"] for h in hits}) == ["Intern", "Senat"]

        api.login(outsider)
        assert sorted({e["title"] for e in _entries(client)}) == ["Senat", "Vorlesungsfrei"]
        _ok(client.get(f"/api/calendar/external/{intern['id']}"), 404)
        hits = _ok(client.get("/api/calendar/search", params={"q": "klausur"}))["items"]
        assert hits == []
        _ok(client.get("/api/admin/calendars"), 403)

        api.login(Principal(sub="chef", permissions={"meeting.view_all"}))
        assert len(_entries(client)) == 6

    async def _feed(person_id: uuid.UUID) -> str:
        async with maker() as session:
            row = await session.get(PrincipalRow, person_id)
            assert row is not None
            events = await service.feed_external(session, row)
        return build_calendar([], domain="x.test", external=events).decode()

    inside = await _feed(member_id)
    assert f"UID:external-{intern['id']}@x.test" in inside
    assert "DTSTART:20310505T160000Z" in inside and "DTEND:20310505T173000Z" in inside
    assert "DTSTART;VALUE=DATE:20310520" in inside and "DTEND;VALUE=DATE:20310521" in inside
    assert "CATEGORIES:senat" in inside and "paul@example.org" not in inside
    outside = await _feed(outsider_id)
    assert "SUMMARY:Senat" in outside and "Intern" not in outside
