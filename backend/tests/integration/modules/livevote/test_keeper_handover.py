"""Z3, O1, O20, A13: the periods of the protocol keeper through the real API.

* The start opens the first period, the close ends it.
* A handover `now` ends the running period and opens the next one. The rights that
  follow the keeper move with it: `canManageVotes` goes to the new keeper, the old
  keeper keeps `canWrite` through `protocol.write`.
* A handover `next_item` waits for the next forward move of the current agenda item.
  A new plan replaces the old one, the last agenda item has no next item, and a
  DELETE discards the plan.
* The new keeper needs `protocol.write` in the gremium (O20, 422).
* Each handover writes `protokollant_handover` and sends `meeting_state`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_principal
from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.models import Meeting, ProtocolKeeperPeriod
from app.modules.livevote.schemas import MeetingOut
from app.modules.livevote.service.pubsub import BrokerPublisher
from tests.integration.modules.livevote.conftest import admin, audit_actions, seed

pytestmark = pytest.mark.integration


async def _member(
    maker: async_sessionmaker[AsyncSession],
    gremium_id: uuid.UUID,
    name: str,
    permissions: list[str],
) -> tuple[str, uuid.UUID]:
    """Write a member of the gremium with an own role and return sub and id."""
    sub = f"{name}-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        row = PrincipalRow(sub=sub, display_name=name, email=f"{sub}@x.de")
        role = GremiumRole(
            gremium_id=gremium_id,
            key=f"r-{sub}",
            name_i18n={"de": name},
            permissions=permissions,
        )
        session.add_all([row, role])
        await session.flush()
        session.add(
            GremiumMembership(principal_id=row.id, gremium_id=gremium_id, gremium_role_id=role.id)
        )
        await session.commit()
    return sub, row.id


def _as(api: FastAPI, sub: str | None) -> None:
    """Act as the member `sub`, or as the admin for `None`."""
    api.dependency_overrides[get_current_principal] = (
        admin if sub is None else (lambda: Principal(sub=sub))
    )


async def _set_keeper(
    maker: async_sessionmaker[AsyncSession],
    meeting_id: uuid.UUID,
    principal_id: uuid.UUID,
    *,
    current: uuid.UUID | None = None,
) -> None:
    async with maker() as session:
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None
        meeting.protokollant_id = principal_id
        meeting.current_agenda_item_id = current
        await session.commit()


async def _periods(
    maker: async_sessionmaker[AsyncSession], meeting_id: uuid.UUID
) -> list[ProtocolKeeperPeriod]:
    async with maker() as session:
        return list(
            (
                await session.scalars(
                    select(ProtocolKeeperPeriod)
                    .where(ProtocolKeeperPeriod.meeting_id == meeting_id)
                    .order_by(ProtocolKeeperPeriod.created_at)
                )
            ).all()
        )


@pytest.fixture
def states(monkeypatch: pytest.MonkeyPatch) -> list[MeetingOut]:
    """Record every `meeting_state` broadcast."""
    sent: list[MeetingOut] = []
    original = BrokerPublisher.meeting_state

    async def _record(self: BrokerPublisher, meeting: MeetingOut) -> None:
        sent.append(meeting)
        await original(self, meeting)

    monkeypatch.setattr(BrokerPublisher, "meeting_state", _record)
    return sent


async def test_start_opens_and_close_ends_the_first_period(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="planned", items=2)
    _, anna = await _member(maker, s.gremium_id, "Anna", ["protocol.write"])
    await _set_keeper(maker, s.meeting_id, anna, current=s.item_ids[0])
    url = f"/api/meetings/{s.meeting_id}"
    with TestClient(api) as client:
        started = client.patch(url, json={"status": "live"})
        assert started.status_code == 200, started.text
        periods = started.json()["keeperPeriods"]
        assert len(periods) == 1
        assert periods[0]["principalId"] == str(anna)
        assert periods[0]["name"] == "Anna"
        assert periods[0]["fromAt"] is not None
        assert periods[0]["toAt"] is None
        assert periods[0]["fromPosition"] == 1
        assert started.json()["plannedHandover"] is None
        closed = client.patch(url, json={"status": "closed"})
        assert closed.status_code == 200, closed.text
    period = closed.json()["keeperPeriods"][0]
    assert period["toAt"] == closed.json()["closedAt"]
    assert period["toPosition"] == 1


async def test_handover_now_moves_the_keeper_rights(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, states: list[MeetingOut]
) -> None:
    s = await seed(maker, status="live", items=2)
    anna_sub, anna = await _member(maker, s.gremium_id, "Anna", ["protocol.write"])
    bert_sub, bert = await _member(maker, s.gremium_id, "Bert", ["protocol.write"])
    await _set_keeper(maker, s.meeting_id, anna, current=s.item_ids[0])
    url = f"/api/meetings/{s.meeting_id}"
    with TestClient(api) as client:
        _as(api, anna_sub)
        before = client.get(url).json()
        assert (before["canWrite"], before["canManageVotes"]) == (True, True)
        resp = client.post(
            f"{url}/protokollant-handover", json={"principalId": str(bert), "mode": "now"}
        )
        assert resp.status_code == 200, resp.text
        after_anna = client.get(url).json()
        _as(api, bert_sub)
        after_bert = client.get(url).json()
    body = resp.json()
    assert body["protokollantId"] == str(bert)
    assert [p["name"] for p in body["keeperPeriods"]] == ["Bert"]  # no period for Anna yet
    # Anna keeps the write access through protocol.write, the room control moves.
    assert (after_anna["canWrite"], after_anna["canManageVotes"]) == (True, False)
    assert after_anna["isProtokollant"] is False
    assert (after_bert["canWrite"], after_bert["canManageVotes"]) == (True, True)
    assert after_bert["isProtokollant"] is True
    assert states and states[-1].protokollant_id == bert
    entries = [
        e for e in await audit_actions(maker, target_id=s.meeting_id)
        if e.action == "protokollant_handover"
    ]
    assert len(entries) == 1
    assert entries[0].actor == anna_sub
    assert entries[0].data["mode"] == "now"
    assert entries[0].data["from"] == str(anna)
    assert entries[0].data["to"] == str(bert)


async def test_handover_now_ends_the_running_period(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="planned", items=2)
    _, anna = await _member(maker, s.gremium_id, "Anna", ["protocol.write"])
    _, bert = await _member(maker, s.gremium_id, "Bert", ["protocol.write"])
    await _set_keeper(maker, s.meeting_id, anna, current=s.item_ids[0])
    url = f"/api/meetings/{s.meeting_id}"
    with TestClient(api) as client:
        assert client.patch(url, json={"status": "live"}).status_code == 200
        moved = client.patch(url, json={"currentAgendaItemId": str(s.item_ids[1])})
        assert moved.status_code == 200, moved.text
        resp = client.post(
            f"{url}/protokollant-handover", json={"principalId": str(bert), "mode": "now"}
        )
        assert resp.status_code == 200, resp.text
    periods = resp.json()["keeperPeriods"]
    assert [p["name"] for p in periods] == ["Anna", "Bert"]
    assert periods[0]["toAt"] == periods[1]["fromAt"]
    assert (periods[0]["fromPosition"], periods[0]["toPosition"]) == (1, 2)
    assert (periods[1]["fromPosition"], periods[1]["toPosition"]) == (2, None)


async def test_next_item_starts_on_a_forward_move(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, states: list[MeetingOut]
) -> None:
    s = await seed(maker, status="planned", items=3)
    _, anna = await _member(maker, s.gremium_id, "Anna", ["protocol.write"])
    _, bert = await _member(maker, s.gremium_id, "Bert", ["protocol.write"])
    await _set_keeper(maker, s.meeting_id, anna, current=s.item_ids[1])
    url = f"/api/meetings/{s.meeting_id}"
    with TestClient(api) as client:
        assert client.patch(url, json={"status": "live"}).status_code == 200
        planned = client.post(
            f"{url}/protokollant-handover",
            json={"principalId": str(bert), "mode": "next_item"},
        )
        assert planned.status_code == 200, planned.text
        assert planned.json()["protokollantId"] == str(anna)
        assert planned.json()["plannedHandover"]["principalId"] == str(bert)
        assert planned.json()["plannedHandover"]["fromAt"] is None
        # A move back keeps the plan.
        back = client.patch(url, json={"currentAgendaItemId": str(s.item_ids[0])})
        assert back.json()["plannedHandover"] is not None
        assert back.json()["protokollantId"] == str(anna)
        forward = client.patch(url, json={"currentAgendaItemId": str(s.item_ids[2])})
        assert forward.status_code == 200, forward.text
    body = forward.json()
    assert body["protokollantId"] == str(bert)
    assert body["plannedHandover"] is None
    periods = body["keeperPeriods"]
    assert [p["name"] for p in periods] == ["Anna", "Bert"]
    assert periods[0]["toPosition"] == 1  # the item before the move
    assert periods[1]["fromPosition"] == 3
    assert states[-1].protokollant_id == bert
    entries = await audit_actions(maker, target_id=s.meeting_id)
    modes = [e.data["mode"] for e in entries if e.action == "protokollant_handover"]
    assert modes == ["next_item", "activate"]
    # The handover is not a planning change of the meeting.
    updates = [e.data["changes"] for e in entries if e.action == "meeting_update"]
    assert all("protokollantId" not in c for c in updates)


async def test_new_plan_replaces_the_old_and_delete_discards_it(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=2)
    anna_sub, anna = await _member(maker, s.gremium_id, "Anna", ["protocol.write"])
    _, bert = await _member(maker, s.gremium_id, "Bert", ["protocol.write"])
    _, cora = await _member(maker, s.gremium_id, "Cora", ["protocol.write"])
    await _set_keeper(maker, s.meeting_id, anna, current=s.item_ids[0])
    url = f"/api/meetings/{s.meeting_id}/protokollant-handover"
    with TestClient(api) as client:
        _as(api, anna_sub)
        first = client.post(url, json={"principalId": str(bert), "mode": "next_item"})
        assert first.status_code == 200, first.text
        second = client.post(url, json={"principalId": str(cora), "mode": "next_item"})
        assert second.status_code == 200, second.text
        assert second.json()["plannedHandover"]["principalId"] == str(cora)
        dropped = client.delete(url)
        missing = client.delete(url)
    assert len([p for p in await _periods(maker, s.meeting_id) if p.from_at is None]) == 0
    assert dropped.status_code == 200, dropped.text
    assert dropped.json()["plannedHandover"] is None
    assert missing.status_code == 404, missing.text
    assert missing.json()["code"] == "no_planned_handover"
    entries = await audit_actions(maker, target_id=s.meeting_id)
    modes = [e.data["mode"] for e in entries if e.action == "protokollant_handover"]
    assert modes == ["next_item", "next_item", "cancel"]


async def test_next_item_on_the_last_item_is_409(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=2)
    _, anna = await _member(maker, s.gremium_id, "Anna", ["protocol.write"])
    _, bert = await _member(maker, s.gremium_id, "Bert", ["protocol.write"])
    await _set_keeper(maker, s.meeting_id, anna, current=s.item_ids[1])
    empty = await seed(maker, status="live", items=0)
    _, carl = await _member(maker, empty.gremium_id, "Carl", ["protocol.write"])
    body = {"principalId": str(bert), "mode": "next_item"}
    with TestClient(api) as client:
        last = client.post(f"/api/meetings/{s.meeting_id}/protokollant-handover", json=body)
        none = client.post(
            f"/api/meetings/{empty.meeting_id}/protokollant-handover",
            json={"principalId": str(carl), "mode": "next_item"},
        )
    assert last.status_code == 409, last.text
    assert last.json()["code"] == "no_next_item"
    assert none.status_code == 409, none.text
    assert none.json()["code"] == "no_next_item"


@pytest.mark.parametrize("status", ["planned", "closed"])
async def test_handover_only_while_live(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, status: str
) -> None:
    s = await seed(maker, status=status, items=1)
    _, bert = await _member(maker, s.gremium_id, "Bert", ["protocol.write"])
    url = f"/api/meetings/{s.meeting_id}/protokollant-handover"
    with TestClient(api) as client:
        post = client.post(url, json={"principalId": str(bert)})
        delete = client.delete(url)
    for resp in (post, delete):
        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == "meeting_not_live"


async def test_target_rules(maker: async_sessionmaker[AsyncSession], api: FastAPI) -> None:
    """O20: the new keeper is an active member with protocol.write."""
    s = await seed(maker, status="live", items=1)
    _, anna = await _member(maker, s.gremium_id, "Anna", ["protocol.write"])
    _, voter = await _member(maker, s.gremium_id, "Vera", ["vote.cast"])
    other = await seed(maker, status="live", items=0)
    _, stranger = await _member(maker, other.gremium_id, "Sven", ["protocol.write"])
    await _set_keeper(maker, s.meeting_id, anna)
    url = f"/api/meetings/{s.meeting_id}/protokollant-handover"
    with TestClient(api) as client:
        no_right = client.post(url, json={"principalId": str(voter)})
        no_member = client.post(url, json={"principalId": str(stranger)})
        unknown = client.post(url, json={"principalId": str(uuid.uuid4())})
        same = client.post(url, json={"principalId": str(anna)})
        bad_mode = client.post(url, json={"principalId": str(anna), "mode": "later"})
    assert no_right.status_code == 422, no_right.text
    assert no_right.json()["code"] == "protokollant_needs_protocol_write"
    assert no_member.status_code == 403, no_member.text
    assert unknown.status_code == 404, unknown.text
    assert same.status_code == 409, same.text
    assert same.json()["code"] == "already_protokollant"
    assert bad_mode.status_code == 422, bad_mode.text


async def test_only_the_lead_or_the_keeper_hands_over(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=1)
    _, anna = await _member(maker, s.gremium_id, "Anna", ["protocol.write"])
    bert_sub, bert = await _member(maker, s.gremium_id, "Bert", ["protocol.write"])
    await _set_keeper(maker, s.meeting_id, anna)
    url = f"/api/meetings/{s.meeting_id}/protokollant-handover"
    _as(api, bert_sub)
    with TestClient(api) as client:
        post = client.post(url, json={"principalId": str(bert)})
        delete = client.delete(url)
    assert post.status_code == 403, post.text
    assert delete.status_code == 403, delete.text


async def test_patch_protokollant_while_live_is_a_handover(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="planned", items=1)
    _, anna = await _member(maker, s.gremium_id, "Anna", ["protocol.write"])
    _, bert = await _member(maker, s.gremium_id, "Bert", ["protocol.write"])
    _, vera = await _member(maker, s.gremium_id, "Vera", ["vote.cast"])
    await _set_keeper(maker, s.meeting_id, anna)
    url = f"/api/meetings/{s.meeting_id}"
    with TestClient(api) as client:
        assert client.patch(url, json={"status": "live"}).status_code == 200
        same = client.patch(url, json={"protokollantId": str(anna)})
        resp = client.patch(url, json={"protokollantId": str(bert)})
        no_right = client.patch(url, json={"protokollantId": str(vera)})
        cleared = client.patch(url, json={"protokollantId": None})
    assert same.status_code == 200, same.text
    assert len(same.json()["keeperPeriods"]) == 1
    assert resp.status_code == 200, resp.text
    assert [p["name"] for p in resp.json()["keeperPeriods"]] == ["Anna", "Bert"]
    assert no_right.status_code == 422, no_right.text
    assert cleared.status_code == 409, cleared.text
    entries = await audit_actions(maker, target_id=s.meeting_id)
    handovers = [e.data for e in entries if e.action == "protokollant_handover"]
    assert [(h["mode"], h["to"]) for h in handovers] == [("now", str(bert))]
    updates = [e.data["changes"] for e in entries if e.action == "meeting_update"]
    assert all("protokollantId" not in c for c in updates)


async def test_assign_needs_protocol_write_but_an_old_keeper_can_start(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """O20 validates a new assignment only."""
    s = await seed(maker, status="planned", items=1)
    _, vera = await _member(maker, s.gremium_id, "Vera", ["vote.cast"])
    url = f"/api/meetings/{s.meeting_id}"
    with TestClient(api) as client:
        refused = client.patch(url, json={"protokollantId": str(vera)})
        await _set_keeper(maker, s.meeting_id, vera)
        # The settings dialog sends the unchanged value with each save.
        unchanged = client.patch(url, json={"protokollantId": str(vera), "date": "2026-06-21"})
        started = client.patch(url, json={"status": "live"})
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "protokollant_needs_protocol_write"
    assert unchanged.status_code == 200, unchanged.text
    assert started.status_code == 200, started.text
    assert started.json()["keeperPeriods"][0]["principalId"] == str(vera)


async def test_members_and_roster_mark_the_possible_keepers(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=0)
    _, anna = await _member(maker, s.gremium_id, "Anna", ["protocol.write"])
    _, vera = await _member(maker, s.gremium_id, "Vera", ["vote.cast"])
    with TestClient(api) as client:
        members = client.get(f"/api/gremien/{s.gremium_id}/meeting-members")
        roster = client.get(f"/api/meetings/{s.meeting_id}/attendance")
    for resp in (members, roster):
        assert resp.status_code == 200, resp.text
        flags: dict[str, Any] = {r["principalId"]: r["canKeepProtocol"] for r in resp.json()}
        assert flags == {str(anna): True, str(vera): False}


async def test_meeting_list_carries_the_periods(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="planned", items=1)
    _, anna = await _member(maker, s.gremium_id, "Anna", ["protocol.write"])
    await _set_keeper(maker, s.meeting_id, anna)
    with TestClient(api) as client:
        started = client.patch(f"/api/meetings/{s.meeting_id}", json={"status": "live"})
        assert started.status_code == 200, started.text
        listed = client.get("/api/meetings", params={"gremiumId": str(s.gremium_id)})
    assert listed.status_code == 200, listed.text
    (row,) = listed.json()
    assert [p["name"] for p in row["keeperPeriods"]] == ["Anna"]
