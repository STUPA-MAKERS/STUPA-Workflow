"""Integration: Termine in the feed, the Auskunft, the erasure and the account merge.

Covers specs 000724 (feed) and 000725 (privacy), and the rule of the account merge for
the three principal columns of the Termin tables.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.principal_merge import PrincipalMergeService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.calendar import service
from app.modules.calendar.ics import build_calendar
from app.modules.calendar.models import Answer, Appointment, Invitation
from app.modules.calendar.privacy import appointment_export, erase_appointments
from app.modules.privacy.service import build_auskunft_workbook
from tests.integration.modules.calendar.conftest import CalendarApi
from tests.integration.modules.todos.conftest import add_person

pytestmark = pytest.mark.integration

TIMED = {
    "title": "Klausurtagung",
    "startsOn": "2031-05-05",
    "endsOn": "2031-05-05",
    "startTime": "14:00:00",
    "endTime": "16:00:00",
    "place": "Raum 1",
}


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


async def _feed(maker: async_sessionmaker[AsyncSession], person_id: uuid.UUID) -> str:
    async with maker() as session:
        row = await session.get(PrincipalRow, person_id)
        assert row is not None
        events = await service.feed_appointments(session, row)
    return build_calendar([], domain="x.test", appointments=events).decode()


async def test_feed_holds_readable_termine_with_the_answer(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """§F/meetings/calendar/000724: the feed of an invited person, not of a third person."""
    anna, anna_id = await add_person(maker, "Anna")
    bert, bert_id = await add_person(maker, "Bert")
    _, dora_id = await add_person(maker, "Dora")
    with TestClient(api.app) as client:
        api.login(anna)
        made = _ok(
            client.post(
                "/api/calendar/appointments", json={**TIMED, "principalIds": [str(bert_id)]}
            ),
            201,
        )
        _ok(
            client.post(
                "/api/calendar/appointments",
                json={"title": "Urlaub", "startsOn": "2031-06-01", "endsOn": "2031-06-03"},
            ),
            201,
        )
        api.login(bert)
        _ok(
            client.put(
                f"/api/calendar/appointments/{made['id']}/answer", json={"answer": "tentative"}
            )
        )
    invited = await _feed(maker, bert_id)
    assert f"UID:appointment-{made['id']}@x.test" in invited
    assert "DTSTART:20310505T120000Z" in invited and "DTEND:20310505T140000Z" in invited
    assert "PARTSTAT=TENTATIVE" in invited and "Urlaub" not in invited
    own = await _feed(maker, anna_id)
    assert "DTSTART;VALUE=DATE:20310601" in own and "DTEND;VALUE=DATE:20310604" in own
    assert "ATTENDEE" not in own
    assert "VEVENT" not in await _feed(maker, dora_id)


async def test_export_and_erasure(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """§F/meetings/calendar/000725: the Auskunft holds both; the erasure removes the person."""
    anna, anna_id = await add_person(maker, "Anna")
    bert, bert_id = await add_person(maker, "Bert")
    with TestClient(api.app) as client:
        api.login(anna)
        private = _ok(client.post("/api/calendar/appointments", json=TIMED), 201)
        only_bert = _ok(
            client.post(
                "/api/calendar/appointments", json={**TIMED, "principalIds": [str(bert_id)]}
            ),
            201,
        )
        api.login(bert)
        shared = _ok(
            client.post(
                "/api/calendar/appointments",
                json={**TIMED, "title": "Runde", "principalIds": [str(anna_id)]},
            ),
            201,
        )
        api.login(anna)
        _ok(
            client.put(
                f"/api/calendar/appointments/{shared['id']}/answer", json={"answer": "accept"}
            )
        )
    async with maker() as session:
        data = await appointment_export(session, [anna_id])
        assert [a["title"] for a in data["appointments"]] == ["Klausurtagung", "Klausurtagung"]
        assert [(a["title"], a["answer"]) for a in data["answers"]] == [("Runde", "accept")]
        assert await appointment_export(session, []) == {"appointments": [], "answers": []}
        workbook = build_auskunft_workbook(
            email="a@example.org",
            applications=[],
            versions=[],
            principal=None,
            appointments=data["appointments"],
            appointment_answers=data["answers"],
        )
        assert workbook[:2] == b"PK"
        await erase_appointments(session, anna_id)
        await session.commit()
    async with maker() as session:
        rows = {row.id: row for row in (await session.scalars(select(Appointment))).all()}
        assert uuid.UUID(private["id"]) not in rows
        assert rows[uuid.UUID(only_bert["id"])].creator_id is None
        assert rows[uuid.UUID(shared["id"])].creator_id == bert_id
        assert (await session.scalars(select(Answer))).all() == []
        assert (await session.scalars(select(Invitation.principal_id))).all() == [bert_id]


async def test_account_merge_moves_termine(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """The merge moves the created Termine and combines the invitations and the answers."""
    anna, _ = await add_person(maker, "Anna")
    old, old_id = await add_person(maker, "Alt")
    new, new_id = await add_person(maker, "Neu")
    with TestClient(api.app) as client:
        api.login(old)
        mine = _ok(client.post("/api/calendar/appointments", json=TIMED), 201)
        api.login(anna)
        both = _ok(
            client.post(
                "/api/calendar/appointments",
                json={**TIMED, "principalIds": [str(old_id), str(new_id)]},
            ),
            201,
        )
        one = _ok(
            client.post(
                "/api/calendar/appointments", json={**TIMED, "principalIds": [str(old_id)]}
            ),
            201,
        )
        for person, answer in ((old, "accept"), (new, "decline")):
            api.login(person)
            _ok(
                client.put(
                    f"/api/calendar/appointments/{both['id']}/answer", json={"answer": answer}
                )
            )
        api.login(old)
        _ok(client.put(f"/api/calendar/appointments/{one['id']}/answer", json={"answer": "accept"}))
    async with maker() as session:
        preview = await PrincipalMergeService(session).preview(old_id, new_id, actor="admin")
        area = next(a for a in preview.areas if a.area == "calendar")
        assert (area.rewritten, area.combined) == (3, 2)
    async with maker() as session:
        await PrincipalMergeService(session).merge(old_id, new_id, actor="admin")
    async with maker() as session:
        created = await session.get(Appointment, uuid.UUID(mine["id"]))
        assert created is not None and created.creator_id == new_id
        invited = (
            await session.execute(select(Invitation.appointment_id, Invitation.principal_id))
        ).all()
        assert sorted((str(a), p) for a, p in invited) == sorted(
            [(both["id"], new_id), (one["id"], new_id)]
        )
        answers = (
            await session.execute(select(Answer.appointment_id, Answer.principal_id, Answer.answer))
        ).all()
        assert sorted((str(a), p, v) for a, p, v in answers) == sorted(
            [(both["id"], new_id, "decline"), (one["id"], new_id, "accept")]
        )
