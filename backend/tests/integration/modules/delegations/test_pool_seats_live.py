"""A pool substitute votes for a missing member without a delegation.

* Two members A and B, two substitutes X and Y for both. A and B are not
  checked in. X and Y each take one seat with a represented ballot, and the
  ballots run under the subs of A and B. Of the four, at most two vote.
* A substitute holds at most one seat: X gets no second seat.
* A check-in of A frees the seat of X. The ballot that X cast for A stays.
* The own ballot of a missing member frees the seat in the next vote.
* The pool needs no switch: a gremium without `allow_vote_delegation` still gives
  the seat. `pool_seat.py` reads no server setting, so `delegation_voting_enabled`
  does not apply either.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_principal
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.delegations.models import MeetingDelegation
from app.modules.voting.models import Ballot, Vote
from app.shared.config_schemas import VoteConfig
from tests.integration.modules.delegations.conftest import (
    act,
    gremium,
    meeting,
    member,
    person,
    pool_entry,
)

pytestmark = pytest.mark.integration

CONFIG = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "simple"}
).model_dump(by_alias=True)


class _World:
    def __init__(self) -> None:
        self.gremium_id = uuid.uuid4()
        self.meeting_id = uuid.uuid4()
        self.subs: dict[str, str] = {}
        self.ids: dict[str, uuid.UUID] = {}


async def _world(maker: async_sessionmaker[AsyncSession], *, allow: bool = True) -> _World:
    w = _World()
    w.gremium_id = await gremium(maker, allow=allow)
    for name in ("Anna", "Ben"):
        w.subs[name], w.ids[name] = await member(maker, w.gremium_id, name)
    for name in ("Xaver", "Yara"):
        w.subs[name], w.ids[name] = await person(maker, name)
        for m in ("Anna", "Ben"):
            await pool_entry(maker, w.gremium_id, w.ids[name], for_member=w.ids[m])
    w.meeting_id = await meeting(maker, w.gremium_id, status="live")
    return w


async def _vote(maker: async_sessionmaker[AsyncSession], w: _World) -> uuid.UUID:
    async with maker() as session:
        vote = Vote(
            application_id=None,
            meeting_id=w.meeting_id,
            eligible_group=str(w.gremium_id),
            config=CONFIG,
            status="open",
        )
        session.add(vote)
        await session.commit()
        return vote.id


async def _voters(maker: async_sessionmaker[AsyncSession], vote_id: uuid.UUID) -> set[str]:
    async with maker() as session:
        return set(
            (await session.scalars(select(Ballot.voter_sub).where(Ballot.vote_id == vote_id))).all()
        )


def _as_member(api: FastAPI, w: _World, name: str) -> None:
    """Act as a member with the vote key that the resolver sets for `vote.cast`."""
    principal = Principal(sub=w.subs[name], groups={vote_group_key(str(w.gremium_id))})
    api.dependency_overrides[get_current_principal] = lambda: principal


def _cast(client: TestClient, vote_id: uuid.UUID, *, proxy: bool) -> int:
    body = {"choice": "yes", "asDelegation": proxy}
    return client.post(f"/api/votes/{vote_id}/ballot", json=body).status_code


async def test_two_substitutes_fill_two_seats_and_no_more(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    w = await _world(maker)
    vote_id = await _vote(maker, w)
    with TestClient(api) as client:
        act(api, w.subs["Xaver"])
        status_x = client.get(f"/api/delegations/votes/{vote_id}/status").json()
        x = _cast(client, vote_id, proxy=True)
        x_again = _cast(client, vote_id, proxy=True)
        act(api, w.subs["Yara"])
        y = _cast(client, vote_id, proxy=True)
        _as_member(api, w, "Anna")
        anna = _cast(client, vote_id, proxy=False)
    assert status_x["exercising"] is True
    assert status_x["delegatedByName"] == "Anna"
    assert (x, x_again, y) == (200, 409, 200)
    assert anna == 409
    assert await _voters(maker, vote_id) == {w.subs["Anna"], w.subs["Ben"]}
    async with maker() as session:
        rows = (
            await session.scalars(
                select(MeetingDelegation).where(MeetingDelegation.meeting_id == w.meeting_id)
            )
        ).all()
    assert {(r.delegator_principal_id, r.delegate_principal_id) for r in rows} == {
        (w.ids["Anna"], w.ids["Xaver"]),
        (w.ids["Ben"], w.ids["Yara"]),
    }
    assert all(r.via_pool and r.created_by in w.subs.values() for r in rows)


async def test_third_substitute_finds_no_seat(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """One member, two possible substitutes: the first takes the seat, the second none."""
    w = await _world(maker)
    vote_id = await _vote(maker, w)
    with TestClient(api) as client:
        _as_member(api, w, "Ben")
        ben = _cast(client, vote_id, proxy=False)
        act(api, w.subs["Xaver"])
        x = _cast(client, vote_id, proxy=True)
        act(api, w.subs["Yara"])
        status_y = client.get(f"/api/delegations/votes/{vote_id}/status").json()
        y = _cast(client, vote_id, proxy=True)
    assert (ben, x, y) == (200, 200, 403)
    assert status_y["exercising"] is False


async def test_check_in_frees_the_seat_and_the_ballot_stays(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    w = await _world(maker)
    first = await _vote(maker, w)
    with TestClient(api) as client:
        act(api, w.subs["Xaver"])
        x = _cast(client, first, proxy=True)
        _as_member(api, w, "Anna")
        check_in = client.put(
            f"/api/meetings/{w.meeting_id}/attendance/me", json={"status": "present"}
        )
        again = _cast(client, first, proxy=False)
        second = await _vote(maker, w)
        own = _cast(client, second, proxy=False)
    assert x == 200
    assert check_in.status_code == 200, check_in.text
    assert again == 409
    assert own == 200
    async with maker() as session:
        held = (
            await session.scalars(
                select(MeetingDelegation.delegator_principal_id).where(
                    MeetingDelegation.meeting_id == w.meeting_id
                )
            )
        ).all()
    assert w.ids["Anna"] not in held


async def test_own_ballot_of_a_missing_member_frees_the_seat(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    w = await _world(maker)
    first = await _vote(maker, w)
    second = await _vote(maker, w)
    with TestClient(api) as client:
        act(api, w.subs["Xaver"])
        x = _cast(client, first, proxy=True)
        _as_member(api, w, "Anna")
        status_a = client.get(f"/api/delegations/votes/{second}/status").json()
        own = _cast(client, second, proxy=False)
    assert x == 200
    assert status_a["blocked"] is False
    assert own == 200
    assert await _voters(maker, second) == {w.subs["Anna"]}


async def test_pool_seat_needs_no_delegation_switch(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """The gremium switch governs only the free transfers, not the pool."""
    w = await _world(maker, allow=False)
    vote_id = await _vote(maker, w)
    with TestClient(api) as client:
        act(api, w.subs["Xaver"])
        x = _cast(client, vote_id, proxy=True)
    assert x == 200
    assert await _voters(maker, vote_id) == {w.subs["Anna"]}
