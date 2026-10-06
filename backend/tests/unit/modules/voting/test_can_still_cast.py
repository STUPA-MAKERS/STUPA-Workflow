"""`VotingService.can_still_cast`: the cast gate without a write, for the task list.

The method must say yes exactly when `cast` takes a ballot of the principal: an open
vote in its window, a human session, and an own or a represented ballot that is still
missing. The delegation check and the ballot read are faked, so no database is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.voting import service as voting_mod
from app.modules.voting.models import Vote
from app.modules.voting.schemas import MyBallot
from app.modules.voting.service import VotingService

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
GID = str(uuid4())


def _vote(**over: Any) -> Vote:
    base: dict[str, Any] = {
        "id": uuid4(),
        "status": "open",
        "closes_at": None,
        "meeting_id": uuid4(),
        "eligible_group": GID,
        "config": {"options": ["yes", "no"], "majorityRule": "simple", "secret": False},
    }
    base.update(over)
    return cast(Vote, SimpleNamespace(**base))


def _voter(*, token: bool = False, eligible: bool = True) -> Principal:
    return Principal(
        sub="me",
        groups={vote_group_key(GID)} if eligible else set(),
        scope_permissions=frozenset({"application.read"}) if token else None,
    )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Fake the delegation verdict and the stored ballots."""
    state = SimpleNamespace(blocked=False, delegator=None, cast_by=set())

    async def _check(*_a: Any) -> tuple[bool, str | None]:
        return state.blocked, state.delegator

    async def _my_ballot(_self: Any, _vote: Any, sub: str, *, secret: bool) -> MyBallot:
        assert secret is False
        return MyBallot(cast=sub in state.cast_by)

    monkeypatch.setattr(voting_mod, "voting_delegation_check", _check)
    monkeypatch.setattr(VotingService, "my_ballot", _my_ballot)
    return state


def _svc() -> VotingService:
    return VotingService(cast(AsyncSession, object()))


async def test_own_ballot_missing_is_castable(world: SimpleNamespace) -> None:
    assert await _svc().can_still_cast(_vote(), _voter(), now=NOW)


async def test_vote_not_open_or_window_over(world: SimpleNamespace) -> None:
    svc = _svc()
    assert not await svc.can_still_cast(_vote(status="draft"), _voter(), now=NOW)
    assert not await svc.can_still_cast(_vote(status="closed"), _voter(), now=NOW)
    assert not await svc.can_still_cast(_vote(closes_at=NOW), _voter(), now=NOW)
    later = _vote(closes_at=NOW + timedelta(minutes=5))
    assert await svc.can_still_cast(later, _voter(), now=NOW)


async def test_token_never_casts(world: SimpleNamespace) -> None:
    """Voting stays human: an OAuth token gets no ballot task."""
    assert not await _svc().can_still_cast(_vote(), _voter(token=True), now=NOW)


async def test_membership_without_vote_cast_is_no_ballot(world: SimpleNamespace) -> None:
    assert not await _svc().can_still_cast(_vote(), _voter(eligible=False), now=NOW)


async def test_own_ballot_already_cast(world: SimpleNamespace) -> None:
    world.cast_by = {"me"}
    assert not await _svc().can_still_cast(_vote(), _voter(), now=NOW)


async def test_delegated_away_blocks_the_own_ballot(world: SimpleNamespace) -> None:
    world.blocked = True
    assert not await _svc().can_still_cast(_vote(), _voter(), now=NOW)


async def test_represented_ballot(world: SimpleNamespace) -> None:
    """A delegate without an own right casts the missing ballot of the delegator."""
    world.delegator = "boss"
    assert await _svc().can_still_cast(_vote(), _voter(eligible=False), now=NOW)
    world.cast_by = {"me", "boss"}
    assert not await _svc().can_still_cast(_vote(), _voter(), now=NOW)
    world.cast_by = {"me"}
    assert await _svc().can_still_cast(_vote(), _voter(), now=NOW)
