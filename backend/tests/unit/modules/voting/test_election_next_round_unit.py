"""The next Wahlgang of an election in the election service, without a database.

Every branch of ``ElectionService.next_round`` runs here (§F/meetings/voting/000971).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.voting import election as election_mod
from app.modules.voting.election import ElectionService
from app.modules.voting.schemas import VoteCreateInternal
from app.modules.voting.service import VotingService
from app.shared.errors import ConflictError
from tests._support.flow_fakes import fake_session
from tests.unit.modules.voting.test_election_service import _econfig, _evote
from tests.unit.modules.voting.test_voting_service_unit import NOW

LEAD = Principal(sub="lead", display_name="Mara Keller")


def _first(pool: Any) -> str:
    return pool[0]


def _missed(counts: dict[str, int], **over: Any) -> SimpleNamespace:
    """Return a closed Wahlgang without the majority of the members."""
    base: dict[str, Any] = {
        "config": _econfig(majorityRule="members_majority"),
        "status": "closed",
        "result": "no_majority",
        "meeting_id": None,
        "agenda_item_id": None,
        "question": "Vorsitz",
        "eligible_count": 9,
        "election_result": {"counts": counts, "ballots": sum(counts.values()), "elected": []},
    }
    base.update(over)
    return _evote(**base)


class _World:
    """The patched voting service: the vote, the insert and the audit entries."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, vote: SimpleNamespace, *, child: bool):
        self.db = fake_session()
        self.db.scalar_results = [uuid4() if child else None]
        self.inserted: list[tuple[VoteCreateInternal, dict[str, Any]]] = []
        self.audits: list[dict[str, Any]] = []
        self.locked: list[Any] = []

        async def get_vote(_self: Any, _vote_id: Any, **_kw: Any) -> SimpleNamespace:
            return vote

        async def lock(_self: Any, meeting_id: Any, **_kw: Any) -> None:
            self.locked.append(meeting_id)

        async def insert(_self: Any, _app: Any, payload: VoteCreateInternal, **kw: Any) -> str:
            self.inserted.append((payload, kw))
            return "draft"

        async def audit(_session: Any, **kw: Any) -> None:
            self.audits.append(kw)

        monkeypatch.setattr(VotingService, "_get_vote", get_vote)
        monkeypatch.setattr(VotingService, "_lock_live_meeting", lock)
        monkeypatch.setattr(VotingService, "_insert", insert)
        monkeypatch.setattr(election_mod, "audit_record", audit)
        self.service = ElectionService(VotingService(self.db), _first)


async def test_second_round_keeps_the_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    meeting_id = uuid4()
    vote = _missed({"c1": 3, "c2": 2, "c3": 2}, meeting_id=meeting_id)
    world = _World(monkeypatch, vote, child=False)
    assert await world.service.next_round(vote.id, LEAD, now=NOW) == "draft"
    payload, kw = world.inserted[0]
    assert world.locked == [meeting_id]
    assert payload.round == 2
    assert payload.parent_vote_id == vote.id
    assert payload.eligible_count == 9
    assert [c.id for c in payload.config.candidates] == ["c1", "c2", "c3"]  # type: ignore[union-attr]
    assert kw["meeting_id"] == meeting_id
    assert world.audits == []


async def test_third_round_takes_the_two_strongest(monkeypatch: pytest.MonkeyPatch) -> None:
    vote = _missed({"c1": 1, "c2": 4, "c3": 3}, round=2)
    world = _World(monkeypatch, vote, child=False)
    await world.service.next_round(vote.id, LEAD, now=NOW)
    payload, _kw = world.inserted[0]
    assert world.locked == []
    assert payload.round == 3
    assert [c.id for c in payload.config.candidates] == ["c2", "c3"]  # type: ignore[union-attr]
    assert world.audits == []
    assert "nextRoundLot" not in vote.election_result


async def test_third_round_draws_the_lot_for_a_tied_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vote = _missed({"c1": 4, "c2": 2, "c3": 2}, round=2)
    world = _World(monkeypatch, vote, child=False)
    await world.service.next_round(vote.id, LEAD, now=NOW)
    payload, _kw = world.inserted[0]
    assert [c.id for c in payload.config.candidates] == ["c1", "c2"]  # type: ignore[union-attr]
    lot = vote.election_result["nextRoundLot"]
    assert lot["among"] == ["c2", "c3"]
    assert lot["drawn"] == ["c2"]
    assert lot["by"] == "lead"
    assert world.audits[0]["data"]["for"] == "next_round"
    assert world.audits[0]["data"]["drawn"] == ["c2"]


async def test_a_stored_lot_stands_for_a_new_third_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = {
        "counts": {"c1": 4, "c2": 2, "c3": 2},
        "ballots": 8,
        "elected": [],
        "nextRoundLot": {"among": ["c2", "c3"], "seats": 1, "drawn": ["c3"]},
    }
    vote = _missed({}, round=2, election_result=stored)
    world = _World(monkeypatch, vote, child=False)
    await world.service.next_round(vote.id, LEAD, now=NOW)
    payload, _kw = world.inserted[0]
    assert [c.id for c in payload.config.candidates] == ["c1", "c3"]  # type: ignore[union-attr]
    assert world.audits == []


@pytest.mark.parametrize(
    "over",
    [
        {"result": "elected"},
        {"result": "rejected"},
        {"round": 3},
        {"config": _econfig()},
    ],
)
async def test_no_next_round_for_another_result_round_or_rule(
    monkeypatch: pytest.MonkeyPatch, over: dict[str, Any]
) -> None:
    vote = _missed({"c1": 3, "c2": 2, "c3": 2}, **over)
    world = _World(monkeypatch, vote, child=False)
    with pytest.raises(ConflictError) as err:
        await world.service.next_round(vote.id, LEAD, now=NOW)
    assert err.value.code == "no_next_round"
    assert world.inserted == []


async def test_an_election_that_is_voted_on_again_takes_no_next_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vote = _missed({"c1": 3, "c2": 2, "c3": 2})
    world = _World(monkeypatch, vote, child=False)
    world.db.scalar_results = ["repeat"]
    with pytest.raises(ConflictError) as err:
        await world.service.next_round(vote.id, LEAD, now=NOW)
    assert err.value.code == "repeat_exists"
    assert world.inserted == []


async def test_an_election_has_one_next_round(monkeypatch: pytest.MonkeyPatch) -> None:
    vote = _missed({"c1": 3, "c2": 2, "c3": 2})
    world = _World(monkeypatch, vote, child=True)
    with pytest.raises(ConflictError) as err:
        await world.service.next_round(vote.id, LEAD, now=NOW)
    assert err.value.code == "next_round_exists"
    assert world.inserted == []
