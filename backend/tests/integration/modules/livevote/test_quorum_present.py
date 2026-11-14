"""The quorum of a meeting vote counts the present persons, and the members rules.

* A meeting vote with a quorum closes with few ballots when enough roster persons are
  present (§F/meetings/voting/000900).
* A Gremium with ``quorumMinPresent`` needs that number of present persons
  (§F/meetings/voting/000901).
* The dialog of a meeting vote stores ``quorumBasis = present`` and the least number of
  the Gremium, and it refuses guests on a members rule (§F/meetings/voting/000898).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.gremien.models import Gremium, GremiumMembership, GremiumRole
from app.modules.meetings.models import MeetingAttendance
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteClosed
from app.modules.voting.service import VotingService
from app.shared.errors import ConflictError
from tests.integration.modules.livevote.conftest import Seed, seed

pytestmark = pytest.mark.integration

MEMBERS = 5


def _config(*, min_present: int | None = None) -> dict[str, object]:
    return {
        "options": ["yes", "no", "abstain"],
        "majorityRule": "simple",
        "secret": True,
        "quorum": {"type": "percent", "value": 40},
        "quorumBasis": "present",
        **({} if min_present is None else {"quorumMinPresent": min_present}),
    }


async def _world(
    maker: async_sessionmaker[AsyncSession],
    *,
    present: int,
    min_present: int | None = None,
) -> tuple[Seed, uuid.UUID]:
    """Write a live meeting with five voting members, ``present`` of them checked in.

    The open vote has a quorum of 40 % and no ballot.
    """
    s = await seed(maker, status="live")
    async with maker() as session:
        role = GremiumRole(
            gremium_id=s.gremium_id,
            key="member",
            name_i18n={"de": "Mitglied"},
            permissions=["vote.cast"],
        )
        session.add(role)
        await session.flush()
        for n in range(MEMBERS):
            tag = uuid.uuid4().hex[:8]
            person = PrincipalRow(sub=f"m-{tag}", display_name=f"M{n}", email=f"m-{tag}@x.de")
            session.add(person)
            await session.flush()
            session.add(
                GremiumMembership(
                    gremium_id=s.gremium_id, principal_id=person.id, gremium_role_id=role.id
                )
            )
            if n < present:
                session.add(
                    MeetingAttendance(
                        meeting_id=s.meeting_id, principal_id=person.id, status="present"
                    )
                )
        vote = Vote(
            application_id=None,
            meeting_id=s.meeting_id,
            agenda_item_id=s.item_ids[0],
            eligible_group=str(s.gremium_id),
            config=_config(min_present=min_present),
            status="open",
            eligible_count=MEMBERS,
        )
        session.add(vote)
        await session.commit()
        return s, vote.id


async def _close(maker: async_sessionmaker[AsyncSession], vote_id: uuid.UUID) -> VoteClosed:
    """Close the vote by hand, as the minute taker does."""
    async with maker() as session:
        return await VotingService(session).close(vote_id, Principal(sub="mgr", roles=["admin"]))


async def test_close_meets_the_quorum_by_present_members(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Two of five are present (40 %): the vote closes without a ballot.

    Rule: §F/meetings/voting/000900.
    """
    _, vote_id = await _world(maker, present=2)
    closed = await _close(maker, vote_id)
    assert closed.tally.quorum_met is True


async def test_close_misses_the_quorum_with_too_few_present(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """One of five is present: the manual close is refused.

    Rules: §F/meetings/voting/000900, §F/meetings/voting/000380.
    """
    _, vote_id = await _world(maker, present=1)
    with pytest.raises(ConflictError):
        await _close(maker, vote_id)


async def test_close_needs_the_least_number_of_present_members(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """40 % are present, and the least number of three is not.

    Rule: §F/meetings/voting/000901.
    """
    _, low = await _world(maker, present=2, min_present=3)
    _, enough = await _world(maker, present=3, min_present=3)
    with pytest.raises(ConflictError):
        await _close(maker, low)
    assert (await _close(maker, enough)).tally.quorum_met is True


async def test_meeting_vote_takes_the_presence_rules_of_the_gremium(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """A prepared vote stores the basis ``present`` and the least number (§000901)."""
    s = await seed(maker, status="live")
    async with maker() as session:
        await session.execute(
            update(Gremium)
            .where(Gremium.id == s.gremium_id)
            .values(quorum_percent=40, quorum_min_present=3)
        )
        await session.commit()
    body = {
        "agendaItemId": str(s.item_ids[0]),
        "question": "Satzung ändern?",
        "majorityRule": "members_two_thirds",
        "draft": True,
    }
    with TestClient(api) as client:
        resp = client.post(f"/api/meetings/{s.meeting_id}/votes", json=body)
    assert resp.status_code in (200, 201), resp.text
    async with maker() as session:
        config = (await session.get(Vote, uuid.UUID(resp.json()["votes"][-1]["id"]))).config  # type: ignore[union-attr]
    assert config["majorityRule"] == "members_two_thirds"
    assert config["quorumBasis"] == "present"
    assert config["quorumMinPresent"] == 3
    assert config["quorum"] == {"type": "percent", "value": 40}


async def test_members_rule_refuses_guest_ballots(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """A members rule with ``guestsVote`` answers 422 (§000898)."""
    s = await seed(maker, status="live")
    body = {
        "agendaItemId": str(s.item_ids[0]),
        "question": "Satzung ändern?",
        "majorityRule": "members_majority",
        "guestsVote": True,
        "draft": True,
    }
    with TestClient(api) as client:
        resp = client.post(f"/api/meetings/{s.meeting_id}/votes", json=body)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "guests_vote_unavailable"
