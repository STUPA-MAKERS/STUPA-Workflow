"""The delegate limit, the one cast for all ballots, and elections.

* A delegate holds at most `delegation_max_per_delegate` delegations in one meeting
  (§F/meetings/delegations/000909). One delegation more answers 409 `delegate_limit`.
* One cast of the delegate writes the own ballot and one ballot for each represented
  member (§F/meetings/voting/000932). The represented cast answers 409 `vote_as_unit`
  while the own ballot is open.
* The turnout of a running vote counts the persons who cast, not the ballots
  (§F/meetings/voting/000933).
* An election takes no delegation ballot without the gremium switch
  (§F/meetings/delegations/000910).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_principal
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.gremien.models import Gremium
from app.modules.voting.models import Vote, VotedMarker
from app.shared.config_schemas import VoteConfig
from tests.integration.modules.delegations.conftest import (
    act,
    gremium,
    meeting,
    member,
    person,
    set_status,
)

pytestmark = pytest.mark.integration

MOTION = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "simple", "secret": True}
).model_dump(by_alias=True)
ELECTION = {
    "seats": 1,
    "candidates": [{"id": "c1", "name": "Jonas Albrecht"}, {"id": "c2", "name": "Mara Keller"}],
    "secret": True,
}


class _World:
    def __init__(self) -> None:
        self.gremium_id = uuid.uuid4()
        self.meeting_id = uuid.uuid4()
        self.subs: dict[str, str] = {}
        self.ids: dict[str, uuid.UUID] = {}


async def _world(maker: async_sessionmaker[AsyncSession]) -> _World:
    w = _World()
    w.gremium_id = await gremium(maker)
    for name in ("Anna", "Ben", "Cem", "Dora"):
        w.subs[name], w.ids[name] = await member(maker, w.gremium_id, name)
    w.meeting_id = await meeting(maker, w.gremium_id)
    return w


def _delegate(client: TestClient, api: FastAPI, w: _World, name: str, to: str) -> Response:
    act(api, w.subs[name])
    body = {"meetingId": str(w.meeting_id), "delegateId": str(w.ids[to]), "delegateVoting": True}
    return client.post("/api/delegations", json=body)


async def _vote(
    maker: async_sessionmaker[AsyncSession], w: _World, *, election: bool = False
) -> uuid.UUID:
    async with maker() as session:
        vote = Vote(
            application_id=None,
            meeting_id=w.meeting_id,
            eligible_group=str(w.gremium_id),
            config=ELECTION if election else MOTION,
            kind="election" if election else "motion",
            status="open",
        )
        session.add(vote)
        await session.commit()
        return vote.id


async def _voters(maker: async_sessionmaker[AsyncSession], vote_id: uuid.UUID) -> set[str]:
    async with maker() as session:
        return set(
            (
                await session.scalars(
                    select(VotedMarker.voter_sub).where(VotedMarker.vote_id == vote_id)
                )
            ).all()
        )


def _as_member(api: FastAPI, w: _World, name: str) -> None:
    principal = Principal(sub=w.subs[name], groups={vote_group_key(str(w.gremium_id))})
    api.dependency_overrides[get_current_principal] = lambda: principal


def _cast(client: TestClient, vote_id: uuid.UUID, choice: Any, *, proxy: bool = False) -> Response:
    return client.post(
        f"/api/votes/{vote_id}/ballot", json={"choice": choice, "asDelegation": proxy}
    )


async def test_one_delegation_more_than_the_limit_conflicts(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/delegations/000909: the limit of a new Gremium is 2."""
    w = await _world(maker)
    with TestClient(api) as client:
        first = _delegate(client, api, w, "Anna", "Dora")
        second = _delegate(client, api, w, "Ben", "Dora")
        third = _delegate(client, api, w, "Cem", "Dora")
        async with maker() as session:
            await session.execute(
                update(Gremium)
                .where(Gremium.id == w.gremium_id)
                .values(delegation_max_per_delegate=3)
            )
            await session.commit()
        raised = _delegate(client, api, w, "Cem", "Dora")
    assert (first.status_code, second.status_code) == (201, 201), second.text
    assert third.status_code == 409, third.text
    assert third.json()["code"] == "delegate_limit"
    assert raised.status_code == 201, raised.text


async def test_one_cast_writes_the_own_and_each_represented_ballot(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/voting/000932: Dora casts once for herself, Anna and Ben.

    §F/meetings/voting/000933: the three ballots count as one person in the turnout.
    """
    w = await _world(maker)
    with TestClient(api) as client:
        assert _delegate(client, api, w, "Anna", "Dora").status_code == 201
        assert _delegate(client, api, w, "Ben", "Dora").status_code == 201
        await set_status(maker, w.meeting_id, "live")
        vote_id = await _vote(maker, w)
        _as_member(api, w, "Dora")
        status = client.get(f"/api/delegations/votes/{vote_id}/status").json()
        split = _cast(client, vote_id, "no", proxy=True)
        unit = _cast(client, vote_id, "yes")
        before_again = client.get(f"/api/votes/{vote_id}").json()
        again = _cast(client, vote_id, "yes")
        late = _cast(client, vote_id, "yes", proxy=True)
        _as_member(api, w, "Anna")
        anna = _cast(client, vote_id, "yes")
    assert status["delegatedByNames"] == ["Anna", "Ben"]
    assert status["delegatedByName"] == "Anna, Ben"
    assert split.status_code == 409, split.text
    assert split.json()["code"] == "vote_as_unit"
    assert unit.status_code == 200, unit.text
    assert unit.json()["ballots"] == 3
    assert before_again["representedCast"] is True
    assert before_again["tally"]["voted"] == 1
    assert (again.status_code, late.status_code) == (409, 409)
    assert anna.status_code == 403, anna.text
    assert await _voters(maker, vote_id) == {w.subs["Dora"], w.subs["Anna"], w.subs["Ben"]}


async def test_an_external_delegate_casts_for_every_represented_member(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """A delegate without an own ballot casts once for both delegators."""
    w = await _world(maker)
    sub, pid = await person(maker, "Extern")
    w.subs["Extern"], w.ids["Extern"] = sub, pid
    async with maker() as session:
        await session.execute(
            update(Gremium).where(Gremium.id == w.gremium_id).values(delegation_allow_external=True)
        )
        await session.commit()
    with TestClient(api) as client:
        assert _delegate(client, api, w, "Anna", "Extern").status_code == 201
        assert _delegate(client, api, w, "Ben", "Extern").status_code == 201
        await set_status(maker, w.meeting_id, "live")
        vote_id = await _vote(maker, w)
        act(api, sub)
        own = _cast(client, vote_id, "yes")
        proxy = _cast(client, vote_id, "yes", proxy=True)
        act(api, None)
        turnout = client.get(f"/api/votes/{vote_id}").json()["tally"]["voted"]
        listed = client.get(f"/api/meetings/{w.meeting_id}").json()
    assert turnout == 1
    assert [v["voted"] for v in listed["votes"]] == [1]
    assert own.status_code == 403, own.text
    assert proxy.status_code == 200, proxy.text
    assert proxy.json()["ballots"] == 2
    assert await _voters(maker, vote_id) == {w.subs["Anna"], w.subs["Ben"]}


async def test_an_election_takes_no_delegation_ballot(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/delegations/000910: the switch of the Gremium allows the ballot."""
    w = await _world(maker)
    with TestClient(api) as client:
        assert _delegate(client, api, w, "Anna", "Dora").status_code == 201
        await set_status(maker, w.meeting_id, "live")
        closed = await _vote(maker, w, election=True)
        _as_member(api, w, "Dora")
        status = client.get(f"/api/delegations/votes/{closed}/status").json()
        own = _cast(client, closed, ["c1"])
        proxy = _cast(client, closed, ["c1"], proxy=True)
        async with maker() as session:
            await session.execute(
                update(Gremium)
                .where(Gremium.id == w.gremium_id)
                .values(delegation_in_elections=True)
            )
            await session.commit()
        allowed = await _vote(maker, w, election=True)
        both = _cast(client, allowed, ["c2"])
    assert status["exercising"] is False
    assert status["delegatedByNames"] == []
    assert own.status_code == 200, own.text
    assert own.json()["ballots"] == 1
    assert proxy.status_code == 403, proxy.text
    assert proxy.json()["code"] == "delegation_not_in_election"
    assert await _voters(maker, closed) == {w.subs["Dora"]}
    assert both.status_code == 200, both.text
    assert both.json()["ballots"] == 2
    assert await _voters(maker, allowed) == {w.subs["Dora"], w.subs["Anna"]}
