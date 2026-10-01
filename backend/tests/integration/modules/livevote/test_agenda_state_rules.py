"""F24, O25 and O22: the agenda follows the meeting state, and every change is audited.

* Add, reorder, rename and remove need a planned or live meeting (409 otherwise).
* Remove answers 409 while the item has an open or closed vote. It deletes the
  draft and cancelled votes of the item first, each with ``vote_delete``. To delete
  them the caller needs ``canManageVotes``: ``protocol.write`` alone gives 403.
* The body needs a live meeting, or a closed meeting with a draft protocol.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_principal
from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.models import MeetingAgendaItem
from app.modules.voting.models import Ballot, Vote
from tests.integration.modules.livevote.conftest import ADMIN_SUB, audit_actions, seed

pytestmark = pytest.mark.integration


async def test_closed_meeting_refuses_agenda_changes(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="closed", items=2, protocol="draft")
    base = f"/api/meetings/{s.meeting_id}/agenda"
    with TestClient(api) as client:
        responses = [
            client.post(base, json={"title": "Neu"}),
            client.put(f"{base}/order", json={"itemIds": [str(i) for i in s.item_ids[::-1]]}),
            client.patch(f"{base}/{s.item_ids[0]}", json={"title": "Umbenannt"}),
            client.delete(f"{base}/{s.item_ids[0]}"),
        ]
    for resp in responses:
        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == "meeting_closed"
    assert await audit_actions(maker, target_id=s.meeting_id) == []


@pytest.mark.parametrize("status", ["open", "closed"])
async def test_remove_item_with_open_or_closed_vote_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, status: str
) -> None:
    s = await seed(maker, status="live", votes=(status, "draft"))
    with TestClient(api) as client:
        resp = client.delete(f"/api/meetings/{s.meeting_id}/agenda/{s.item_ids[0]}")
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "agenda_item_has_vote"
    async with maker() as session:
        assert await session.get(MeetingAgendaItem, s.item_ids[0]) is not None
        for vote_id in s.vote_ids.values():
            assert await session.get(Vote, vote_id) is not None


async def test_remove_item_deletes_draft_and_cancelled_votes_with_audit(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=2, votes=("draft", "cancelled"))
    with TestClient(api) as client:
        resp = client.delete(f"/api/meetings/{s.meeting_id}/agenda/{s.item_ids[0]}")
    assert resp.status_code == 200, resp.text
    assert [i["id"] for i in resp.json()] == [str(s.item_ids[1])]
    async with maker() as session:
        assert await session.get(MeetingAgendaItem, s.item_ids[0]) is None
        for vote_id in s.vote_ids.values():
            assert await session.get(Vote, vote_id) is None
    entries = await audit_actions(maker)
    deletes = [e for e in entries if e.action == "vote_delete"]
    assert {e.target_id for e in deletes} == {str(v) for v in s.vote_ids.values()}
    assert all(e.actor == ADMIN_SUB for e in deletes)
    [remove] = [e for e in entries if e.action == "agenda_item_remove"]
    assert remove.target_id == str(s.meeting_id)
    assert remove.data["agendaItemId"] == str(s.item_ids[0])
    assert sorted(remove.data["deletedVoteIds"]) == sorted(str(v) for v in s.vote_ids.values())


@pytest.mark.parametrize("status", ["planned", "live"])
async def test_agenda_changes_are_audited(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, status: str
) -> None:
    s = await seed(maker, status=status, items=2)
    base = f"/api/meetings/{s.meeting_id}/agenda"
    with TestClient(api) as client:
        added = client.post(base, json={"title": "Sonstiges", "nonPublic": True})
        assert added.status_code == 200, added.text
        new_id = added.json()[-1]["id"]
        order = [new_id, *(str(i) for i in s.item_ids)]
        assert client.put(f"{base}/order", json={"itemIds": order}).status_code == 200
        renamed = client.patch(f"{base}/{new_id}", json={"title": "Verschiedenes"})
        assert renamed.status_code == 200, renamed.text
        assert client.delete(f"{base}/{new_id}").status_code == 200
    entries = await audit_actions(maker, target_id=s.meeting_id)
    assert [e.action for e in entries] == [
        "agenda_item_add",
        "agenda_reorder",
        "agenda_item_update",
        "agenda_item_remove",
    ]
    assert entries[0].data["nonPublic"] is True
    assert entries[1].data["itemIds"] == order
    assert entries[2].data["fields"] == ["title"]
    # No entry carries a text of the agenda.
    assert "Verschiedenes" not in str([e.data for e in entries])


async def test_body_on_planned_meeting_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="planned")
    with TestClient(api) as client:
        resp = client.patch(
            f"/api/meetings/{s.meeting_id}/agenda/{s.item_ids[0]}", json={"body": "x"}
        )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "meeting_not_started"


async def test_live_minutes_are_not_audited(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", protocol="draft")
    with TestClient(api) as client:
        resp = client.patch(
            f"/api/meetings/{s.meeting_id}/agenda/{s.item_ids[0]}", json={"body": "Notiz"}
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["body"] == "Notiz"
    assert await audit_actions(maker, target_id=s.meeting_id) == []


async def test_body_after_close_with_draft_protocol(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """O22: the minutes stay correctable between the close and the finalize."""
    s = await seed(maker, status="closed", protocol="draft")
    with TestClient(api) as client:
        resp = client.patch(
            f"/api/meetings/{s.meeting_id}/agenda/{s.item_ids[0]}",
            json={"body": "Korrektur", "nonPublic": True},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["body"] == "Korrektur"
    assert resp.json()[0]["nonPublic"] is True
    [entry] = await audit_actions(maker, target_id=s.meeting_id)
    assert entry.action == "agenda_item_update"
    assert entry.data["fields"] == ["body", "nonPublic"]
    assert "Korrektur" not in str(entry.data)


@pytest.mark.parametrize("protocol", ["rendering", "final"])
async def test_body_after_close_with_locked_protocol_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, protocol: str
) -> None:
    s = await seed(maker, status="closed", protocol=protocol)
    with TestClient(api) as client:
        resp = client.patch(
            f"/api/meetings/{s.meeting_id}/agenda/{s.item_ids[0]}", json={"body": "spät"}
        )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "protocol_locked"


async def _protocol_writer(maker: async_sessionmaker[AsyncSession], gremium_id: uuid.UUID) -> str:
    """Write a member whose gremium role holds only ``protocol.write``. Return its sub."""
    sub = f"pw-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        row = PrincipalRow(sub=sub, display_name="PW", email=f"{sub}@x.de")
        role = GremiumRole(
            gremium_id=gremium_id,
            key=f"pw-{sub}",
            name_i18n={"de": "Protokoll"},
            permissions=["protocol.write"],
        )
        session.add_all([row, role])
        await session.flush()
        session.add(
            GremiumMembership(
                principal_id=row.id, gremium_id=gremium_id, gremium_role_id=role.id
            )
        )
        await session.commit()
    return sub


async def test_protocol_writer_cannot_remove_an_item_with_votes(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """``protocol.write`` edits the agenda, but deleting a vote needs ``canManageVotes``.

    A cancelled vote can hold ballots. Without this gate the agenda right alone would
    delete the vote and its ballots, past the gate of the vote delete route.
    """
    s = await seed(maker, status="live", items=2, votes=("cancelled",))
    async with maker() as session:
        session.add(Ballot(vote_id=s.vote_ids["cancelled"], voter_sub="voter", choice="yes"))
        await session.commit()
    sub = await _protocol_writer(maker, s.gremium_id)
    api.dependency_overrides[get_current_principal] = lambda: Principal(sub=sub)
    base = f"/api/meetings/{s.meeting_id}/agenda"
    with TestClient(api) as client:
        refused = client.delete(f"{base}/{s.item_ids[0]}")
        # The same member removes an item without votes.
        allowed = client.delete(f"{base}/{s.item_ids[1]}")
    assert refused.status_code == 403, refused.text
    assert allowed.status_code == 200, allowed.text
    assert [i["id"] for i in allowed.json()] == [str(s.item_ids[0])]
    async with maker() as session:
        assert await session.get(MeetingAgendaItem, s.item_ids[0]) is not None
        assert await session.get(Vote, s.vote_ids["cancelled"]) is not None
        ballots = await session.scalar(
            select(func.count()).select_from(Ballot).where(
                Ballot.vote_id == s.vote_ids["cancelled"]
            )
        )
        assert ballots == 1
    actions = [e.action for e in await audit_actions(maker)]
    assert "vote_delete" not in actions
    assert actions.count("agenda_item_remove") == 1
