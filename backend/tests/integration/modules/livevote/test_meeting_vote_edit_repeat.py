"""A prepared meeting vote changes, and a closed one is voted on again.

``PUT /meetings/{id}/votes/{voteId}`` replaces the question and the rules of a draft and
writes ``vote_update``; an open or closed vote stays as it is. ``repeatOf`` on the create
repeats a closed vote of the same agenda item: the repeat counts on (``attempt``), and on
an application item the open moves the application back into its vote state, so the
repeat decides it again.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.applications.models import Application, StatusEvent
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.service import BrokerPublisher
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.meetings.publisher import get_meeting_publisher
from app.modules.voting.models import Vote
from tests.integration.modules.livevote.conftest import ADMIN_SUB, audit_actions, seed
from tests.integration.modules.voting.vote_support import seed_vote_flow

pytestmark = pytest.mark.integration


async def test_update_draft_replaces_question_and_rules(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="planned", votes=("draft",))
    vote_id = s.vote_ids["draft"]
    body = {
        "agendaItemId": str(s.item_ids[0]),
        "question": "Neue Frage?",
        "majorityRule": "absolute",
    }
    with TestClient(api) as client:
        resp = client.put(f"/api/meetings/{s.meeting_id}/votes/{vote_id}", json=body)
    assert resp.status_code == 200, resp.text
    [vote] = resp.json()["votes"]
    assert vote["question"] == "Neue Frage?"
    assert vote["majorityRule"] == "absolute"
    assert vote["status"] == "draft"
    assert vote["secret"] is True
    [entry] = await audit_actions(maker, target_id=vote_id)
    assert entry.action == "vote_update"
    assert entry.data["kind"] == "motion"
    assert "question" not in entry.data


async def test_update_draft_to_a_poll(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", votes=("draft",))
    vote_id = s.vote_ids["draft"]
    body = {
        "agendaItemId": str(s.item_ids[0]),
        "kind": "poll",
        "question": "Pizza?",
        "poll": {"mode": "single", "options": [{"label": "Ja"}, {"label": "Nein"}]},
    }
    with TestClient(api) as client:
        resp = client.put(f"/api/meetings/{s.meeting_id}/votes/{vote_id}", json=body)
    assert resp.status_code == 200, resp.text
    [vote] = resp.json()["votes"]
    assert vote["kind"] == "poll"
    assert [o["label"] for o in vote["poll"]["options"]] == ["Ja", "Nein"]


@pytest.mark.parametrize("status", ["open", "closed", "cancelled"])
async def test_update_refuses_a_vote_that_is_no_draft(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, status: str
) -> None:
    s = await seed(maker, status="live", votes=(status,))
    vote_id = s.vote_ids[status]
    body = {"agendaItemId": str(s.item_ids[0]), "question": "X"}
    with TestClient(api) as client:
        resp = client.put(f"/api/meetings/{s.meeting_id}/votes/{vote_id}", json=body)
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "vote_not_editable"
    assert await audit_actions(maker, target_id=vote_id) == []


async def test_update_keeps_the_agenda_item(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=2, votes=("draft",))
    body = {"agendaItemId": str(s.item_ids[1]), "question": "X"}
    with TestClient(api) as client:
        resp = client.put(
            f"/api/meetings/{s.meeting_id}/votes/{s.vote_ids['draft']}", json=body
        )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "agenda_item_mismatch"


async def test_update_after_close_of_the_meeting_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="closed", votes=("draft",))
    body = {"agendaItemId": str(s.item_ids[0]), "question": "X"}
    with TestClient(api) as client:
        resp = client.put(
            f"/api/meetings/{s.meeting_id}/votes/{s.vote_ids['draft']}", json=body
        )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "meeting_closed"


async def test_repeat_of_a_free_text_vote(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", votes=("closed",))
    closed = s.vote_ids["closed"]
    body = {
        "agendaItemId": str(s.item_ids[0]),
        "question": "Nochmal?",
        "repeatOf": str(closed),
        "draft": True,
    }
    with TestClient(api) as client:
        resp = client.post(f"/api/meetings/{s.meeting_id}/votes", json=body)
        assert resp.status_code == 200, resp.text
        votes = resp.json()["votes"]
        again = client.post(f"/api/meetings/{s.meeting_id}/votes", json=body)
    repeat = next(v for v in votes if v["id"] != str(closed))
    assert repeat["repeatOfId"] == str(closed)
    assert repeat["attempt"] == 2
    assert repeat["status"] == "draft"
    first = next(v for v in votes if v["id"] == str(closed))
    assert first["status"] == "closed" and first["result"] == "passed"
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "repeat_exists"


@pytest.mark.parametrize("status", ["draft", "open", "cancelled"])
async def test_repeat_needs_a_closed_vote(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, status: str
) -> None:
    s = await seed(maker, status="live", votes=(status,))
    body = {
        "agendaItemId": str(s.item_ids[0]),
        "repeatOf": str(s.vote_ids[status]),
        "draft": True,
    }
    with TestClient(api) as client:
        resp = client.post(f"/api/meetings/{s.meeting_id}/votes", json=body)
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "vote_not_closed"


async def test_repeat_waits_for_a_pending_vote_of_the_item(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", votes=("closed", "draft"))
    body = {
        "agendaItemId": str(s.item_ids[0]),
        "repeatOf": str(s.vote_ids["closed"]),
        "draft": True,
    }
    with TestClient(api) as client:
        resp = client.post(f"/api/meetings/{s.meeting_id}/votes", json=body)
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "vote_pending"


async def test_repeat_of_another_item_is_not_found(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=2, votes=("closed",))
    body = {
        "agendaItemId": str(s.item_ids[1]),
        "repeatOf": str(s.vote_ids["closed"]),
        "draft": True,
    }
    with TestClient(api) as client:
        resp = client.post(f"/api/meetings/{s.meeting_id}/votes", json=body)
    assert resp.status_code == 404, resp.text


@pytest.fixture
def app_api(api: FastAPI) -> FastAPI:
    """The app of ``api`` with the vote close publishing to an in-memory broker."""
    broker = InMemoryBroker()
    api.dependency_overrides[get_meeting_publisher] = lambda: BrokerPublisher(broker)
    return api


async def _application_meeting(
    maker: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]:
    """Seed an application in a vote state on the agenda of a live meeting.

    The admin keeps the minutes, so the admin opens and closes the votes.
    """
    async with maker() as session:
        flow = await seed_vote_flow(session)
        row = (
            await session.execute(select(PrincipalRow).where(PrincipalRow.sub == ADMIN_SUB))
        ).scalar_one_or_none()
        if row is None:
            row = PrincipalRow(sub=ADMIN_SUB, display_name="Admin", email="admin@x.de")
            session.add(row)
            await session.flush()
        meeting = Meeting(
            gremium_id=flow.gremium_id, title="Sitzung", status="live", protokollant_id=row.id
        )
        session.add(meeting)
        await session.flush()
        item = MeetingAgendaItem(meeting_id=meeting.id, application_id=flow.app_id, position=0)
        session.add(item)
        await session.commit()
        return meeting.id, item.id, flow.app_id, flow.states


async def _state(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> uuid.UUID:
    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None and app.current_state_id is not None
        return app.current_state_id


async def test_repeat_of_an_application_vote_moves_the_application_back(
    maker: async_sessionmaker[AsyncSession], app_api: FastAPI
) -> None:
    meeting_id, item_id, app_id, states = await _application_meeting(maker)
    with TestClient(app_api) as client:
        resp = client.post(
            f"/api/meetings/{meeting_id}/votes", json={"agendaItemId": str(item_id)}
        )
        assert resp.status_code == 200, resp.text
        [first] = resp.json()["votes"]
        closed = client.post(f"/api/votes/{first['id']}/close")
        assert closed.status_code == 200, closed.text
        assert closed.json()["branchFired"] is True
        assert await _state(maker, app_id) == states["rejected"]
        prepared = client.post(
            f"/api/meetings/{meeting_id}/votes",
            json={"agendaItemId": str(item_id), "repeatOf": first["id"], "draft": True},
        )
        assert prepared.status_code == 200, prepared.text
        assert await _state(maker, app_id) == states["rejected"]
        repeat = next(v for v in prepared.json()["votes"] if v["id"] != first["id"])
        opened = client.post(f"/api/meetings/{meeting_id}/votes/{repeat['id']}/open")
        assert opened.status_code == 200, opened.text
    assert await _state(maker, app_id) == states["voting"]
    async with maker() as session:
        events = (
            (
                await session.execute(
                    select(StatusEvent)
                    .where(StatusEvent.application_id == app_id)
                    .order_by(StatusEvent.at)
                )
            )
            .scalars()
            .all()
        )
        back = events[-1]
        assert back.note == "vote:repeat"
        assert back.to_state_id == states["voting"]
        assert back.from_state_id == states["rejected"]
        row = await session.get(Vote, uuid.UUID(repeat["id"]))
        assert row is not None and row.status == "open" and row.attempt == 2


async def test_repeat_opened_at_once_moves_the_application_back(
    maker: async_sessionmaker[AsyncSession], app_api: FastAPI
) -> None:
    meeting_id, item_id, app_id, states = await _application_meeting(maker)
    with TestClient(app_api) as client:
        [first] = client.post(
            f"/api/meetings/{meeting_id}/votes", json={"agendaItemId": str(item_id)}
        ).json()["votes"]
        assert client.post(f"/api/votes/{first['id']}/close").status_code == 200
        again = client.post(
            f"/api/meetings/{meeting_id}/votes",
            json={"agendaItemId": str(item_id), "repeatOf": first["id"]},
        )
        assert again.status_code == 200, again.text
        repeat = next(v for v in again.json()["votes"] if v["id"] != first["id"])
        assert repeat["status"] == "open"
        assert await _state(maker, app_id) == states["voting"]
        closed = client.post(f"/api/votes/{repeat['id']}/close")
    assert closed.status_code == 200, closed.text
    assert closed.json()["branchFired"] is True
    assert await _state(maker, app_id) == states["rejected"]


async def test_repeat_refuses_an_application_that_moved_on(
    maker: async_sessionmaker[AsyncSession], app_api: FastAPI
) -> None:
    meeting_id, item_id, app_id, states = await _application_meeting(maker)
    with TestClient(app_api) as client:
        [first] = client.post(
            f"/api/meetings/{meeting_id}/votes", json={"agendaItemId": str(item_id)}
        ).json()["votes"]
        assert client.post(f"/api/votes/{first['id']}/close").status_code == 200
        async with maker() as session:
            app = await session.get(Application, app_id)
            assert app is not None
            app.current_state_id = states["review"]
            await session.commit()
        resp = client.post(
            f"/api/meetings/{meeting_id}/votes",
            json={"agendaItemId": str(item_id), "repeatOf": first["id"]},
        )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "application_moved_on"
    assert await _state(maker, app_id) == states["review"]
