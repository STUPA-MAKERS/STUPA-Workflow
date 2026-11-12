"""Integration: the public calendar (specs 000730-000734).

Covers the switch "Öffentlich" of a Termin, the reads without a session, the meetings
of a Gremium with public protocols, the public feed and its cache, and noindex.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date, time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.calendar.models import ExternalCalendar, ExternalEntry
from app.modules.calendar.public_router import get_public_feed_cache
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.meetings.protocol_models import Protocol
from tests.integration.modules.calendar.conftest import CalendarApi
from tests.integration.modules.todos.conftest import add_gremium, add_person

pytestmark = pytest.mark.integration

TERMIN = {"title": "Vollversammlung", "startsOn": "2031-05-05", "endsOn": "2031-05-05"}
SPAN = {"from": "2031-05-01", "to": "2031-05-31"}


@pytest.fixture(autouse=True)
async def _no_calendars(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    """Remove the external calendars after a test: no other fixture owns them."""
    yield
    async with maker() as session:
        await session.execute(delete(ExternalCalendar))
        await session.commit()


@dataclass
class _Cache:
    """A feed cache in memory that counts its reads."""

    bodies: list[bytes] = field(default_factory=list)
    reads: int = 0

    async def get(self) -> bytes | None:
        self.reads += 1
        return self.bodies[-1] if self.bodies else None

    async def put(self, body: bytes) -> None:
        self.bodies.append(body)


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _with(principal: Principal, *permissions: str) -> Principal:
    return Principal(
        sub=principal.sub,
        email=principal.email,
        display_name=principal.display_name,
        permissions=set(permissions),
    )


async def _meeting(
    maker: async_sessionmaker[AsyncSession], gremium_id: Any, title: str, *, public: bool
) -> Meeting:
    async with maker() as session:
        await session.execute(
            update(Gremium).where(Gremium.id == gremium_id).values(protocols_public=public)
        )
        meeting = Meeting(
            gremium_id=gremium_id,
            title=title,
            date=date(2031, 5, 12),
            start_time=time(18, 0),
            end_time=time(20, 0),
        )
        session.add(meeting)
        await session.flush()
        session.add_all(
            [
                MeetingAgendaItem(meeting_id=meeting.id, title="Haushalt", position=1),
                MeetingAgendaItem(
                    meeting_id=meeting.id, title="Personal", position=2, non_public=True
                ),
                MeetingAgendaItem(meeting_id=meeting.id, title="Berichte", position=0),
            ]
        )
        await session.commit()
        return meeting


async def test_public_termin(api: CalendarApi, maker: async_sessionmaker[AsyncSession]) -> None:
    """§F/meetings/calendar/000730: only ``calendar.publish`` sets the switch.

    A read without a session gives no creator, no invitation and no answer.
    """
    anna, anna_id = await add_person(maker, "Anna")
    bert, _ = await add_person(maker, "Bert")
    gremium_id, _ = await add_gremium(maker, "AStA")
    with TestClient(api.app) as client:
        api.login(anna)
        _ok(client.post("/api/calendar/appointments", json={**TERMIN, "public": True}), 403)
        private = _ok(client.post("/api/calendar/appointments", json=TERMIN), 201)
        api.login(_with(anna, "calendar.publish", "calendar.manage"))
        made = _ok(
            client.post(
                "/api/calendar/appointments",
                json={
                    **TERMIN,
                    "public": True,
                    "place": "Aula",
                    "description": "Offen für alle.",
                    "gremiumIds": [str(gremium_id)],
                    "principalIds": [str(anna_id)],
                },
            ),
            201,
        )
        assert made["public"] is True and made["forAll"] is False
        api.login(anna)
        _ok(client.put(f"/api/calendar/appointments/{made['id']}", json=TERMIN), 403)
        api.login(bert)
        assert _ok(client.get(f"/api/calendar/appointments/{made['id']}"))["public"] is True
        ids = [e["id"] for e in _ok(client.get("/api/calendar/entries", params=SPAN))["items"]]
        assert ids == [made["id"]]

        api.login(None)
        out = _ok(client.get(f"/api/public/calendar/appointments/{made['id']}"))
        assert out == {
            "id": made["id"],
            "title": "Vollversammlung",
            "startsOn": "2031-05-05",
            "endsOn": "2031-05-05",
            "startTime": None,
            "endTime": None,
            "place": "Aula",
            "description": "Offen für alle.",
        }
        _ok(client.get(f"/api/public/calendar/appointments/{private['id']}"), 404)
        entries = _ok(client.get("/api/public/calendar/entries", params=SPAN))["items"]
        assert [(e["kind"], e["title"], e["gremiumIds"], e["source"]) for e in entries] == [
            ("appointment", "Vollversammlung", [], None)
        ]


async def test_public_meetings_and_no_other_kind(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """§F/meetings/calendar/000731, 000732: the meetings of a Gremium with public protocols.

    A meeting shows its open TOPs. No card, no Event and no external entry is public.
    """
    open_id, _ = await add_gremium(maker, "StuPa")
    closed_id, _ = await add_gremium(maker, "Vorstand")
    shown = await _meeting(maker, open_id, "12. Sitzung", public=True)
    hidden = await _meeting(maker, closed_id, "Klausur", public=False)
    async with maker() as session:
        calendar = ExternalCalendar(name="Uni", url="https://example.org/a.ics")
        session.add(calendar)
        await session.flush()
        session.add(
            ExternalEntry(
                calendar_id=calendar.id,
                title="Extern",
                starts_on=date(2031, 5, 12),
                ends_on=date(2031, 5, 12),
            )
        )
        await session.commit()
    api.login(None)
    with TestClient(api.app) as client:
        assert _ok(client.get("/api/public/calendar/committees")) == [
            {"id": str(open_id), "name": "StuPa"}
        ]
        entries = _ok(client.get("/api/public/calendar/entries", params=SPAN))["items"]
        assert [(e["kind"], e["title"], e["source"]) for e in entries] == [
            ("meeting", "12. Sitzung", "StuPa")
        ]
        filtered = client.get(
            "/api/public/calendar/entries", params={**SPAN, "gremium": str(closed_id)}
        )
        assert _ok(filtered)["items"] == []
        out = _ok(client.get(f"/api/public/calendar/meetings/{shown.id}"))
        assert out == {
            "id": str(shown.id),
            "title": "12. Sitzung",
            "day": "2031-05-12",
            "startTime": "18:00:00",
            "endTime": "20:00:00",
            "gremium": "StuPa",
            "tops": ["Berichte", "Haushalt"],
            "protocolId": None,
        }
        _ok(client.get(f"/api/public/calendar/meetings/{hidden.id}"), 404)
        _ok(client.get("/api/public/calendar/entries", params={"from": "2031-05-02"}), 422)
        _ok(
            client.get(
                "/api/public/calendar/entries", params={"from": "2031-05-02", "to": "2031-05-01"}
            ),
            422,
        )
        _ok(
            client.get(
                "/api/public/calendar/entries", params={"from": "2031-01-01", "to": "2031-12-31"}
            ),
            422,
        )

    async with maker() as session:
        session.add(
            Protocol(
                meeting_id=shown.id,
                gremium_id=open_id,
                status="final",
                public_content={"tops": []},
            )
        )
        await session.commit()
    with TestClient(api.app) as client:
        out = _ok(client.get(f"/api/public/calendar/meetings/{shown.id}"))
        assert out["protocolId"] is not None


async def test_public_search(api: CalendarApi, maker: async_sessionmaker[AsyncSession]) -> None:
    """§F/meetings/calendar/000731: the search finds public entries by title and place."""
    anna, _ = await add_person(maker, "Anna")
    gremium_id, _ = await add_gremium(maker, "StuPa")
    await _meeting(maker, gremium_id, "Wahlsitzung", public=True)
    with TestClient(api.app) as client:
        api.login(_with(anna, "calendar.publish"))
        _ok(
            client.post(
                "/api/calendar/appointments",
                json={**TERMIN, "title": "Wahl", "place": "Wahllokal", "public": True},
            ),
            201,
        )
        _ok(client.post("/api/calendar/appointments", json={**TERMIN, "title": "Wahlparty"}), 201)
        api.login(None)
        found = _ok(client.get("/api/public/calendar/search", params={"q": "wahl"}))["items"]
        assert sorted(e["title"] for e in found) == ["Wahl", "Wahlsitzung"]
        by_place = _ok(client.get("/api/public/calendar/search", params={"q": "lokal"}))["items"]
        assert [e["title"] for e in by_place] == ["Wahl"]
        assert _ok(client.get("/api/public/calendar/search", params={"q": "w"}))["items"] == []
        assert _ok(client.get("/api/public/calendar/search"))["items"] == []


async def test_public_feed(api: CalendarApi, maker: async_sessionmaker[AsyncSession]) -> None:
    """§F/meetings/calendar/000733, 000734: the feed without a token.

    It holds the public entries, no organiser and no attendee, comes from the cache,
    and sends noindex.
    """
    anna, anna_id = await add_person(maker, "Anna")
    gremium_id, _ = await add_gremium(maker, "StuPa")
    await _meeting(maker, gremium_id, "12. Sitzung", public=True)
    cache = _Cache()
    api.app.dependency_overrides[get_public_feed_cache] = lambda: cache
    with TestClient(api.app) as client:
        api.login(_with(anna, "calendar.publish"))
        _ok(
            client.post(
                "/api/calendar/appointments",
                json={
                    **TERMIN,
                    "startTime": "10:00:00",
                    "endTime": "11:00:00",
                    "public": True,
                    "principalIds": [str(anna_id)],
                },
            ),
            201,
        )
        _ok(client.post("/api/calendar/appointments", json={**TERMIN, "title": "Intern"}), 201)
        api.login(None)
        first = client.get("/api/public/calendar.ics")
        assert first.status_code == 200, first.text
        assert first.headers["x-robots-tag"] == "noindex"
        assert first.headers["cache-control"] == "public, max-age=300"
        assert first.headers["content-type"].startswith("text/calendar")
        body = first.text
        assert "SUMMARY:Vollversammlung" in body
        assert "SUMMARY:12. Sitzung" in body
        assert "Intern" not in body
        assert "ORGANIZER" not in body
        assert "ATTENDEE" not in body
        assert len(cache.bodies) == 1

        api.login(_with(anna, "calendar.publish"))
        _ok(
            client.post(
                "/api/calendar/appointments", json={**TERMIN, "title": "Neu", "public": True}
            ),
            201,
        )
        api.login(None)
        second = client.get("/api/public/calendar.ics")
        assert second.content == first.content
        assert (cache.reads, len(cache.bodies)) == (2, 1)
        page = client.get("/api/public/calendar/entries", params=SPAN)
        assert page.headers["x-robots-tag"] == "noindex"
