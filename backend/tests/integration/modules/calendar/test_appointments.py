"""Integration: the Termine and the entries of the Kalender (specs 000711-000720, 000727).

Covers the time span of a Termin, who changes it, the invitation of Gremien and
persons, who reads it, the answers, the mails of a write, the entries of the Kalender
page under the read rule of each module, and the search.
"""

from __future__ import annotations

import uuid
from datetime import date, time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.calendar.mails import send_appointment_mail
from app.modules.meetings.models import Meeting
from app.modules.notifications.mail import MailMessage
from app.modules.notifications.models import NotificationPreference
from app.settings import Settings
from tests.integration.modules.calendar.conftest import CalendarApi
from tests.integration.modules.todos.conftest import add_gremium, add_member, add_person

pytestmark = pytest.mark.integration

TERMIN = {"title": "Klausurtagung", "startsOn": "2031-05-05", "endsOn": "2031-05-05"}
TIMED = {**TERMIN, "startTime": "14:00:00", "endTime": "16:00:00", "place": "Raum 1"}


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _create(client: TestClient, **body: Any) -> dict[str, Any]:
    return _ok(client.post("/api/calendar/appointments", json={**TERMIN, **body}), 201)


def _entries(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    query = {"from": "2031-05-01", "to": "2031-05-31", **params}
    return _ok(client.get("/api/calendar/entries", params=query))["items"]


def _with(principal: Principal, *permissions: str) -> Principal:
    return Principal(
        sub=principal.sub,
        email=principal.email,
        display_name=principal.display_name,
        permissions=set(permissions),
    )


async def test_termin_span(api: CalendarApi, maker: async_sessionmaker[AsyncSession]) -> None:
    """§F/meetings/calendar/000715: all-day over three days, no end before the start."""
    anna, _ = await add_person(maker, "Anna")
    api.login(anna)
    with TestClient(api.app) as client:
        made = _create(client, endsOn="2031-05-07")
        assert (made["startsOn"], made["endsOn"], made["startTime"]) == (
            "2031-05-05",
            "2031-05-07",
            None,
        )
        assert made["canEdit"] is True and made["invited"] is False
        _ok(client.post("/api/calendar/appointments", json={**TERMIN, "endsOn": "2031-05-04"}), 422)
        _ok(
            client.post(
                "/api/calendar/appointments",
                json={**TERMIN, "startTime": "14:00:00", "endTime": "13:00:00"},
            ),
            422,
        )
        _ok(
            client.post("/api/calendar/appointments", json={**TERMIN, "startTime": "14:00:00"}), 422
        )
        _ok(client.post("/api/calendar/appointments", json={**TERMIN, "title": "  "}), 422)


async def test_only_creator_or_manager_changes(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """§F/meetings/calendar/000716: an invited person gets 403, a manager changes."""
    anna, _ = await add_person(maker, "Anna")
    bert, bert_id = await add_person(maker, "Bert")
    with TestClient(api.app) as client:
        api.login(anna)
        made = _create(client, principalIds=[str(bert_id)])
        url = f"/api/calendar/appointments/{made['id']}"
        api.login(bert)
        _ok(client.put(url, json={**TERMIN, "title": "Neu"}), 403)
        _ok(client.delete(url), 403)
        api.login(_with(bert, "calendar.manage"))
        assert _ok(client.put(url, json={**TERMIN, "title": "Neu"}))["title"] == "Neu"
        _ok(client.delete(url), 204)
        _ok(client.get(url), 404)


async def test_invited_gremium_follows_its_members(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """§F/meetings/calendar/000717: a new member reads; a foreign Gremium is refused."""
    anna, anna_id = await add_person(maker, "Anna")
    cleo, cleo_id = await add_person(maker, "Cleo")
    stupa, _ = await add_gremium(maker, "StuPa")
    asta, _ = await add_gremium(maker, "AStA")
    await add_member(maker, stupa, anna_id)
    with TestClient(api.app) as client:
        api.login(anna)
        _ok(
            client.post("/api/calendar/appointments", json={**TERMIN, "gremiumIds": [str(asta)]}),
            403,
        )
        _ok(
            client.post(
                "/api/calendar/appointments", json={**TERMIN, "gremiumIds": [str(uuid.uuid4())]}
            ),
            422,
        )
        _ok(
            client.post(
                "/api/calendar/appointments", json={**TERMIN, "principalIds": [str(uuid.uuid4())]}
            ),
            422,
        )
        made = _create(client, gremiumIds=[str(stupa)])
        assert [g["name"] for g in made["gremien"]] == ["StuPa"]
        url = f"/api/calendar/appointments/{made['id']}"
        api.login(cleo)
        _ok(client.get(url), 404)
        await add_member(maker, stupa, cleo_id)
        seen = _ok(client.get(url))
        assert seen["invited"] is True and seen["canEdit"] is False
        api.login(_with(anna, "calendar.manage"))
        kept = _ok(client.put(url, json={**TERMIN, "gremiumIds": [str(stupa), str(asta)]}))
        assert [g["name"] for g in kept["gremien"]] == ["AStA", "StuPa"]
        api.login(anna)
        again = _ok(client.put(url, json={**TERMIN, "gremiumIds": [str(asta)]}))
        assert [g["name"] for g in again["gremien"]] == ["AStA"]


async def test_visibility_and_for_all(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """§F/meetings/calendar/000718: a third person gets 404; the switch needs the right."""
    anna, _ = await add_person(maker, "Anna")
    dora, _ = await add_person(maker, "Dora")
    with TestClient(api.app) as client:
        api.login(anna)
        made = _create(client)
        url = f"/api/calendar/appointments/{made['id']}"
        _ok(client.put(url, json={**TERMIN, "forAll": True}), 403)
        _ok(client.post("/api/calendar/appointments", json={**TERMIN, "forAll": True}), 403)
        api.login(dora)
        _ok(client.get(url), 404)
        _ok(client.put(url, json=TERMIN), 404)
        _ok(client.put(f"{url}/answer", json={"answer": "accept"}), 404)
        assert _entries(client) == []
        api.login(_with(anna, "calendar.publish"))
        assert _ok(client.put(url, json={**TERMIN, "forAll": True}))["forAll"] is True
        api.login(dora)
        seen = _ok(client.get(url))
        assert seen["forAll"] is True and seen["invited"] is False and seen["answers"] == []
        _ok(client.put(f"{url}/answer", json={"answer": "accept"}), 403)
        assert [e["title"] for e in _entries(client)] == ["Klausurtagung"]
        assert _entries(client, mine=True) == []
        api.login(Principal(sub=dora.sub, scope_permissions=frozenset({"todo.write"})))
        _ok(client.get(url), 404)
        _ok(client.post("/api/calendar/appointments", json=TERMIN), 403)
        assert _ok(client.get("/api/calendar/people", params={"q": "Anna"})) == []


async def test_answers(api: CalendarApi, maker: async_sessionmaker[AsyncSession]) -> None:
    """§F/meetings/calendar/000719: answer, change the answer, a moved start clears it."""
    anna, _ = await add_person(maker, "Anna")
    bert, bert_id = await add_person(maker, "Bert")
    cleo, cleo_id = await add_person(maker, "Cleo")
    with TestClient(api.app) as client:
        api.login(anna)
        made = _create(client, **TIMED, principalIds=[str(bert_id), str(cleo_id)])
        url = f"/api/calendar/appointments/{made['id']}"
        api.login(bert)
        assert _ok(client.put(f"{url}/answer", json={"answer": "accept"}))["myAnswer"] == "accept"
        assert (
            _ok(client.put(f"{url}/answer", json={"answer": "tentative"}))["myAnswer"]
            == "tentative"
        )
        api.login(cleo)
        _ok(client.put(f"{url}/answer", json={"answer": "decline"}))
        api.login(anna)
        seen = _ok(client.get(url))
        assert [(a["name"], a["answer"]) for a in seen["answers"]] == [
            ("Bert", "tentative"),
            ("Cleo", "decline"),
        ]
        assert _entries(client)[0]["myAnswer"] is None
        kept = _ok(client.put(url, json={**TIMED, "title": "Neu", "principalIds": [str(bert_id)]}))
        assert [a["name"] for a in kept["answers"]] == ["Bert"]
        moved = _ok(
            client.put(url, json={**TIMED, "startTime": "15:00:00", "principalIds": [str(bert_id)]})
        )
        assert moved["answers"] == []
        past = _create(
            client, startsOn="2020-01-01", endsOn="2020-01-01", principalIds=[str(bert_id)]
        )
        api.login(bert)
        _ok(
            client.put(
                f"/api/calendar/appointments/{past['id']}/answer", json={"answer": "accept"}
            ),
            409,
        )
        assert _entries(client, mine=True)[0]["mine"] is True


async def test_mails_of_a_write(api: CalendarApi, maker: async_sessionmaker[AsyncSession]) -> None:
    """§F/meetings/calendar/000720: invitation, change and deletion, never to the actor."""
    anna, anna_id = await add_person(maker, "Anna")
    _, bert_id = await add_person(maker, "Bert")
    _, cleo_id = await add_person(maker, "Cleo")
    stupa, _ = await add_gremium(maker, "StuPa")
    for person in (anna_id, bert_id):
        await add_member(maker, stupa, person)
    api.login(anna)
    with TestClient(api.app) as client:
        made = _create(client, **TIMED, gremiumIds=[str(stupa)])
        url = f"/api/calendar/appointments/{made['id']}"
        assert [(m.kind, m.recipients) for m in api.mails] == [("invited", (bert_id,))]
        api.mails.clear()
        _ok(client.put(url, json={**TIMED, "title": "Neu", "gremiumIds": [str(stupa)]}))
        assert api.mails == []
        _ok(
            client.put(
                url,
                json={
                    **TIMED,
                    "place": "Aula",
                    "gremiumIds": [str(stupa)],
                    "principalIds": [str(cleo_id)],
                },
            )
        )
        assert sorted((m.kind, m.recipients) for m in api.mails) == [
            ("changed", (bert_id,)),
            ("invited", (cleo_id,)),
        ]
        assert api.mails[0].facts.sequence == 1
        api.mails.clear()
        _ok(client.delete(url), 204)
        assert [(m.kind, set(m.recipients)) for m in api.mails] == [
            ("cancelled", {bert_id, cleo_id})
        ]


class _Queue:
    def __init__(self) -> None:
        self.sent: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.sent.append(msg)


async def test_mail_per_person_with_ics_and_opt_out(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """§F/meetings/calendar/000720: one mail per member with the .ics file, none after opt-out."""
    anna, anna_id = await add_person(maker, "Anna")
    _, bert_id = await add_person(maker, "Bert")
    _, cleo_id = await add_person(maker, "Cleo")
    stupa, _ = await add_gremium(maker, "StuPa")
    for person in (anna_id, bert_id, cleo_id):
        await add_member(maker, stupa, person)
    api.login(anna)
    with TestClient(api.app) as client:
        made = _create(client, **TIMED, gremiumIds=[str(stupa)])
        _ok(client.delete(f"/api/calendar/appointments/{made['id']}"), 204)
    queue = _Queue()
    async with maker() as session:
        session.add(NotificationPreference(principal_id=cleo_id, kind="appointment", enabled=False))
        await session.commit()
        sent = [
            await send_appointment_mail(session, queue=queue, settings=settings, mail=mail)
            for mail in api.mails
        ]
    assert sent == [1, 1]
    invited, cancelled = queue.sent
    assert len(invited.to) == 1 and invited.to[0].startswith("bert")
    assert "Klausurtagung" in invited.subject and "05.05.2031 14:00 – 16:00" in invited.text
    assert "/calendar?appointment=" in invited.text
    ics = invited.attachments[0].content.decode()
    assert "METHOD:PUBLISH" in ics and "PARTSTAT=NEEDS-ACTION" in ics and "LOCATION:Raum 1" in ics
    assert "/calendar?appointment=" not in cancelled.text
    gone = cancelled.attachments[0].content.decode()
    assert "METHOD:CANCEL" in gone and "STATUS:CANCELLED" in gone


async def test_entries_follow_the_module_rules(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """§F/meetings/calendar/000711 and 000712: each kind under its own read rule."""
    anna, anna_id = await add_person(maker, "Anna")
    bert, bert_id = await add_person(maker, "Bert")
    dora, _ = await add_person(maker, "Dora")
    stupa, board = await add_gremium(maker, "StuPa")
    for person in (anna_id, bert_id):
        await add_member(maker, stupa, person, "todo.write")
    async with maker() as session:
        session.add_all(
            [
                Meeting(
                    gremium_id=stupa,
                    title="Sitzung 12",
                    date=date(2031, 5, 6),
                    start_time=time(18, 0),
                    end_time=time(20, 0),
                ),
                Meeting(gremium_id=stupa, title="Ohne Datum"),
            ]
        )
        await session.commit()
    with TestClient(api.app) as client:
        api.login(anna)
        cards = "/api/todos/cards"
        _ok(
            client.post(
                cards,
                json={
                    "boardId": str(board),
                    "title": "Bericht",
                    "dueDate": "2031-05-08",
                    "assigneeIds": [str(bert_id)],
                },
            ),
            201,
        )
        fest = _ok(client.post(cards, json={"boardId": str(board), "title": "Sommerfest"}), 201)
        _ok(
            client.put(
                f"{cards}/{fest['id']}/event",
                json={"startsOn": "2031-05-30", "endsOn": "2031-06-01", "place": "Hof"},
            )
        )
        _create(client, **TIMED, gremiumIds=[str(stupa)])
        seen = _entries(client)
        assert [(e["kind"], e["title"], e["mine"]) for e in seen] == [
            ("appointment", "Klausurtagung", True),
            ("meeting", "Sitzung 12", False),
            ("card", "Bericht", False),
            ("event", "Sommerfest", False),
        ]
        assert seen[0]["source"] == "StuPa" and seen[0]["gremiumIds"] == [str(stupa)]
        assert (seen[1]["startTime"], seen[1]["source"]) == ("18:00:00", "StuPa")
        assert (seen[3]["endsOn"], seen[3]["place"]) == ("2031-06-01", "Hof")
        assert [e["kind"] for e in _entries(client, mine=True)] == ["appointment", "meeting"]
        api.login(bert)
        assert [e["kind"] for e in _entries(client, mine=True)] == [
            "appointment",
            "meeting",
            "card",
        ]
        assert [
            e["title"] for e in _ok(client.get("/api/calendar/search", params={"q": "s"}))["items"]
        ] == []
        hits = _ok(client.get("/api/calendar/search", params={"q": "e%"}))["items"]
        assert hits == []
        found = _ok(client.get("/api/calendar/search", params={"q": "raum"}))["items"]
        assert [e["title"] for e in found] == ["Klausurtagung"]
        assert sorted(
            e["kind"] for e in _ok(client.get("/api/calendar/search", params={"q": "er"}))["items"]
        ) == ["card", "event"]
        _ok(
            client.get("/api/calendar/entries", params={"from": "2031-05-02", "to": "2031-05-01"}),
            422,
        )
        _ok(
            client.get("/api/calendar/entries", params={"from": "2031-01-01", "to": "2031-12-31"}),
            422,
        )
        people = _ok(client.get("/api/calendar/people", params={"q": "nn"}))
        assert [p["name"] for p in people] == ["Anna"] and "email" not in people[0]
        assert _ok(client.get("/api/calendar/people", params={"q": "a"})) == []
        api.login(dora)
        assert _entries(client) == []
        assert _ok(client.get("/api/calendar/search", params={"q": "Klausur"}))["items"] == []
        assert _ok(client.get("/api/calendar/search", params={"q": "Sitzung"}))["items"] == []
