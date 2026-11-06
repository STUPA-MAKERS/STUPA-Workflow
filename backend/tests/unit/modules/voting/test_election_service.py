"""Personnel elections in the voting service, without a database.

A result-queue fake drives every new branch: the election ballot on the member, the
secret and the guest path, the tally read, the close without a flow branch, the lot,
the runoff, the own ballot, the vote list and the two routes.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.voting import router as voting_router
from app.modules.voting.election import (
    ElectionService,
    election_fields,
    result_of,
)
from app.modules.voting.listing import _own_ballots
from app.modules.voting.schemas import (
    ElectionResultOut,
    MyBallot,
    TallyOut,
    VoteCreateInternal,
    VoteOut,
)
from app.modules.voting.service import VotingService
from app.modules.voting.tally import tally_election
from app.shared.config_schemas import ElectionConfig
from app.shared.errors import ConflictError, ForbiddenError, ValidationProblem
from tests._support.flow_fakes import fake_session, result
from tests.unit.modules.voting.test_voting_service_unit import (  # noqa: F401 - fixture
    GID,
    NOW,
    _FakeFlow,
    _patch_flow,
    _vote,
    _voter,
)


def _econfig(seats: int = 1, n: int = 3, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "seats": seats,
        "candidates": [{"id": f"c{i}", "name": f"Person {i}"} for i in range(1, n + 1)],
        "secret": True,
    }
    data.update(over)
    return ElectionConfig.model_validate(data).model_dump(mode="json", by_alias=True)


def _evote(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "application_id": None,
        "kind": "election",
        "config": _econfig(),
        "round": 1,
        "parent_vote_id": None,
        "election_result": None,
        "present_members": None,
        "present_guests": None,
    }
    base.update(over)
    return _vote(**base)


def _audits(db: Any) -> list[Any]:
    return [a for a in db.added if type(a).__name__ == "AuditEntry"]


def _stored(
    choices: list[str | None], config: dict[str, Any], *, round_: int = 1
) -> dict[str, Any]:
    outcome = tally_election(choices, ElectionConfig.model_validate(config), 10, round_=round_)
    return result_of(outcome).model_dump(mode="json", by_alias=True)


def _secret_choice(db: Any) -> str:
    [secret] = [a for a in db.added if type(a).__name__ == "SecretBallot"]
    return secret.choice


async def test_cast_election_stores_the_sorted_list() -> None:
    vote = _evote(config=_econfig(seats=2))
    db = fake_session(result(vote), result(uuid4()))
    out = await VotingService(db).cast(vote.id, _voter(), ["c2", "c1"], now=NOW)
    assert out.status == "cast"
    assert _secret_choice(db) == '["c1","c2"]'


async def test_cast_election_keeps_the_choice_apart() -> None:
    vote = _evote(config=_econfig(seats=2))
    db = fake_session(result(vote), result(uuid4()))
    await VotingService(db).cast(vote.id, _voter(), [], now=NOW)
    assert _secret_choice(db) == "[]"
    assert "choice" not in db.statements[-1].compile().params


async def test_cast_single_candidate_takes_yes_no() -> None:
    vote = _evote(config=_econfig(n=1))
    db = fake_session(result(vote), result(uuid4()))
    await VotingService(db).cast(vote.id, _voter(), "abstain", now=NOW)
    assert _secret_choice(db) == "abstain"


@pytest.mark.parametrize(
    ("config", "choice"),
    [
        (_econfig(seats=2), "c1"),
        (_econfig(seats=2), ["c1", "c1"]),
        (_econfig(seats=1), ["c1", "c2"]),
        (_econfig(seats=1), ["zz"]),
        (_econfig(n=1), ["c1"]),
        (_econfig(n=1), "maybe"),
    ],
)
async def test_cast_refuses_an_invalid_election_ballot(
    config: dict[str, Any], choice: str | list[str]
) -> None:
    vote = _evote(config=config)
    with pytest.raises(ValidationProblem):
        await VotingService(fake_session(result(vote))).cast(vote.id, _voter(), choice, now=NOW)


async def test_cast_motion_refuses_a_list() -> None:
    vote = _vote()
    with pytest.raises(ValidationProblem):
        await VotingService(fake_session(result(vote))).cast(vote.id, _voter(), ["yes"], now=NOW)


async def test_cast_guest_election() -> None:
    vote = _evote(meeting_id=uuid4(), config=_econfig(seats=2, guestsVote=True))
    db = fake_session(result(vote), result(), result(), result(uuid4()))
    out = await VotingService(db).cast_guest(vote.id, uuid4(), ["c3"], now=NOW)
    assert out.status == "cast"
    assert _secret_choice(db) == '["c3"]'


async def test_get_closed_election_counts_ballots_and_candidates() -> None:
    vote = _evote(config=_econfig(seats=2), status="closed", result="elected")
    ballots = result('["c1","c2"]', '["c1"]', "[]")
    db = fake_session(result(vote), result(), ballots)
    out = await VotingService(db).get(vote.id)
    assert out.kind == "election"
    assert out.election is not None and out.election.seats == 2
    assert out.tally.voted == 3
    assert out.tally.counts == {"c1": 2, "c2": 1, "c3": 0, "abstain": 3}
    assert out.tally.leading is None
    assert out.config.options == ["c1", "c2", "c3", "abstain"]


async def test_get_open_election_hides_the_counts() -> None:
    vote = _evote()
    db = fake_session(result(vote), result(), result('["c1"]'))
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is False
    assert out.tally.counts == {}
    assert out.tally.voted == 1


async def test_get_closed_election_carries_the_stored_result() -> None:
    config = _econfig()
    stored = _stored(['["c1"]'], config)
    vote = _evote(config=config, status="closed", result="elected", election_result=stored, round=2)
    db = fake_session(result(vote), result(), result('["c1"]'))
    out = await VotingService(db).get(vote.id)
    assert out.result == "elected"
    assert out.round == 2
    assert out.election_result is not None and out.election_result.elected == ["c1"]


def test_election_fields_of_a_motion_are_empty() -> None:
    assert election_fields(_vote()) == {}  # type: ignore[arg-type]


async def test_own_ballots_of_the_vote_list_give_only_cast() -> None:
    """The vote list reads the voted markers: an election gives `cast`, never a choice."""
    election, motion = _evote(), _vote()
    db = fake_session(result(election.id))
    out = await _own_ballots(db, "v1", [election, motion])  # type: ignore[list-item]
    assert out == {election.id: MyBallot(cast=True)}


async def test_create_internal_election_writes_kind_and_json_config() -> None:
    """An election is secret by default: the tally stays hidden until the close."""
    principal = uuid4()
    config = ElectionConfig.model_validate(
        {
            "seats": 1,
            "candidates": [
                {"id": "c1", "name": "A", "principalId": str(principal)},
                {"id": "c2", "name": "B"},
            ],
        }
    )
    payload = VoteCreateInternal(config=config, eligibleGroup=GID, eligibleCount=5)
    db = fake_session(result())
    out = await VotingService(db).create_internal(None, payload)
    [vote] = [a for a in db.added if type(a).__name__ == "Vote"]
    assert vote.kind == "election"
    assert vote.round == 1
    assert vote.config["candidates"][0]["principalId"] == str(principal)
    assert out.kind == "election"
    assert out.secret is True
    assert out.tally.counts == {}


@pytest.mark.usefixtures("_patch_flow")
async def test_close_election_elects_without_a_flow_branch() -> None:
    vote = _evote()
    db = fake_session(result(vote), result('["c1"]', '["c1"]', '["c2"]'))
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.result == "elected"
    assert out.kind == "election"
    assert out.branch_fired is False
    assert out.application_id is None
    assert out.election_result is not None and out.election_result.elected == ["c1"]
    assert out.tally.voted == 3
    assert out.tally.present_members is None
    assert vote.status == "closed"
    assert vote.result == "elected"
    assert vote.election_result["elected"] == ["c1"]
    assert _FakeFlow.branch_calls == []
    [entry] = _audits(db)
    assert entry.action == "vote_close"
    assert entry.data["kind"] == "election"
    assert entry.data["elected"] == ["c1"]


async def test_close_election_without_now_stamps_the_time() -> None:
    vote = _evote()
    db = fake_session(result(vote), result('["c1"]'))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.closed_at is not None


async def test_close_election_with_a_tie_keeps_the_lot_pending() -> None:
    vote = _evote()
    db = fake_session(result(vote), result('["c1"]', '["c2"]'))
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.result == "tie"
    assert out.election_result is not None
    assert out.election_result.lot is not None
    assert out.election_result.lot.among == ["c1", "c2"]
    assert out.election_result.lot.drawn is None


async def test_close_election_with_a_boundary_tie_needs_the_lot() -> None:
    vote = _evote(config=_econfig(seats=2, n=4))
    db = fake_session(result(vote), result('["c1","c2"]', '["c1","c3"]'))
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.result == "tie"
    assert out.election_result is not None and out.election_result.runoff is None
    assert out.election_result.lot is not None
    assert out.election_result.lot.among == ["c2", "c3"]
    assert out.election_result.lot.seats == 1


async def test_close_election_without_quorum_409() -> None:
    vote = _evote(config=_econfig(quorum={"type": "count", "value": 5}))
    db = fake_session(result(vote), result('["c1"]'))
    with pytest.raises(ConflictError):
        await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert vote.status == "open"


async def test_close_election_after_the_window_rejects_without_quorum() -> None:
    vote = _evote(
        config=_econfig(quorum={"type": "count", "value": 5}), closes_at=NOW - timedelta(1)
    )
    db = fake_session(result(vote), result('["c1"]'))
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.result == "rejected"
    assert out.tally.failed_reason == "quorum"
    assert out.election_result is not None and out.election_result.elected == []


async def test_close_meeting_election_fixes_the_attendance() -> None:
    """The close of a meeting election stores 4 present members and 2 admitted guests."""
    vote = _evote(meeting_id=uuid4())
    db = fake_session(result(vote), result('["c1"]'))
    db.scalar_results = [4, 2]
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.tally.present_members == 4
    assert out.tally.present_guests == 2
    assert out.tally.eligible == 10


async def test_close_meeting_election_with_guests_counts_them_as_eligible() -> None:
    """The admitted guests of a meeting election with guests count as eligible.

    The fake session serves the admitted guest, no guest ballots and no guest markers.
    The scalar is the number of present members.
    """
    vote = _evote(meeting_id=uuid4(), config=_econfig(guestsVote=True))
    guest = uuid4()
    db = fake_session(
        result(vote),
        result('["c1"]'),
        result(guest),
        result(),
        result(),
    )
    db.scalar_results = [3]
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.tally.eligible == 4
    assert vote.eligible_count == 4


def _first(pool: Any) -> str:
    return pool[0]


def _tied_vote(**over: Any) -> SimpleNamespace:
    config = _econfig()
    stored = _stored(['["c1"]', '["c2"]'], config)
    base: dict[str, Any] = {
        "config": config,
        "status": "closed",
        "result": "tie",
        "election_result": stored,
    }
    base.update(over)
    return _evote(**base)


async def test_draw_lot_elects_the_drawn_candidate() -> None:
    """The lot elects the drawn candidate.

    The fake session serves the audit hook and the reloaded ballots.
    """
    vote = _tied_vote()
    db = fake_session(
        result(vote),
        result(),
        result(),
        result(vote),
        result(),
        result('["c1"]', '["c2"]'),
    )
    lead = Principal(sub="lead", display_name="Mara Keller")
    out = await ElectionService(VotingService(db), _first).draw_lot(vote.id, lead, now=NOW)
    assert vote.result == "elected"
    lot = vote.election_result["lot"]
    assert lot["drawn"] == ["c1"]
    assert lot["by"] == "lead"
    assert lot["byName"] == "Mara Keller"
    assert vote.election_result["elected"] == ["c1"]
    assert out.result == "elected"
    [entry] = _audits(db)
    assert entry.action == "vote_lot_drawn"
    assert entry.data["drawn"] == ["c1"] and entry.data["among"] == ["c1", "c2"]
    assert db.committed == 1


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"kind": "motion"}, "not_an_election"),
        ({"status": "open"}, "not_an_election"),
        ({"election_result": None}, "not_an_election"),
    ],
)
async def test_draw_lot_needs_a_closed_election(over: dict[str, Any], code: str) -> None:
    vote = _tied_vote(**over)
    with pytest.raises(ConflictError) as err:
        await ElectionService(VotingService(fake_session(result(vote)))).draw_lot(
            vote.id, _voter(), now=NOW
        )
    assert err.value.code == code


async def test_draw_lot_without_a_pending_lot_409() -> None:
    config = _econfig()
    vote = _tied_vote(election_result=_stored(['["c1"]'], config), result="elected")
    with pytest.raises(ConflictError) as err:
        await ElectionService(VotingService(fake_session(result(vote)))).draw_lot(
            vote.id, _voter(), now=NOW
        )
    assert err.value.code == "no_lot_pending"


async def test_draw_lot_twice_409() -> None:
    vote = _tied_vote()
    vote.election_result["lot"]["drawn"] = ["c2"]
    with pytest.raises(ConflictError) as err:
        await ElectionService(VotingService(fake_session(result(vote)))).draw_lot(
            vote.id, _voter(), now=NOW
        )
    assert err.value.code == "lot_already_drawn"


def _legacy_runoff(stored: dict[str, Any]) -> dict[str, Any]:
    """Turn a pending lot into the runoff that an older close stored for the same tie."""
    lot = stored["lot"]
    return {**stored, "lot": None, "runoff": {"candidateIds": lot["among"], "seats": lot["seats"]}}


def _runoff_parent(**over: Any) -> SimpleNamespace:
    config = _econfig(seats=2, n=4, **over.pop("config_over", {}))
    stored = _legacy_runoff(_stored(['["c1","c2"]', '["c1","c3"]'], config))
    base: dict[str, Any] = {
        "config": config,
        "status": "closed",
        "result": "runoff",
        "election_result": stored,
        "meeting_id": uuid4(),
        "agenda_item_id": uuid4(),
        "question": "Wahl der Referate",
    }
    base.update(over)
    return _evote(**base)


def _linked_runoff(parent: SimpleNamespace, **over: Any) -> SimpleNamespace:
    runoff = _evote(parent_vote_id=parent.id, round=2, **over)
    parent.election_result["runoff"]["voteId"] = str(runoff.id)
    return runoff


async def test_cancel_of_a_runoff_releases_the_link() -> None:
    parent = _runoff_parent(meeting_id=None)
    runoff = _linked_runoff(parent, status="open")
    db = fake_session(result(runoff), result(parent))
    await VotingService(db).cancel(runoff.id, now=NOW, actor="lead")
    assert runoff.status == "cancelled"
    assert parent.election_result["runoff"]["voteId"] is None
    assert parent.election_result["runoff"]["candidateIds"] == ["c2", "c3"]


async def test_delete_of_a_runoff_releases_the_link() -> None:
    parent = _runoff_parent()
    runoff = _linked_runoff(parent, status="draft", meeting_id=parent.meeting_id)
    db = fake_session(result(runoff), result(parent))
    await VotingService(db).delete(runoff.id, meeting_id=parent.meeting_id, actor="lead")
    assert db.deleted == [runoff]
    assert parent.election_result["runoff"]["voteId"] is None


async def test_release_keeps_a_link_to_another_runoff() -> None:
    parent = _runoff_parent(meeting_id=None)
    runoff = _linked_runoff(parent, status="open")
    other = str(uuid4())
    parent.election_result["runoff"]["voteId"] = other
    db = fake_session(result(runoff), result(parent))
    await VotingService(db).cancel(runoff.id, now=NOW, actor="lead")
    assert parent.election_result["runoff"]["voteId"] == other


@pytest.mark.parametrize("parent_state", ["gone", "no_result", "no_runoff"])
async def test_release_without_a_linked_parent_does_nothing(parent_state: str) -> None:
    parent = _runoff_parent(meeting_id=None)
    runoff = _evote(parent_vote_id=parent.id, round=2, status="open")
    if parent_state == "no_result":
        parent.election_result = None
    elif parent_state == "no_runoff":
        parent.election_result = _stored(['["c1","c2"]'], _econfig(seats=2, n=4))
    found = [] if parent_state == "gone" else [parent]
    db = fake_session(result(runoff), result(*found))
    await VotingService(db).cancel(runoff.id, now=NOW, actor="lead")
    assert runoff.status == "cancelled"


async def test_cancel_of_a_first_round_election_touches_no_parent() -> None:
    vote = _evote(status="open")
    db = fake_session(result(vote))
    await VotingService(db).cancel(vote.id, now=NOW, actor="lead")
    assert vote.status == "cancelled"
    assert not any("vote.id = " in str(s) and "FOR UPDATE" in str(s) for s in db.statements[1:])


_TALLY = TallyOut(counts={}, eligible=0, quorumMet=True)
_MANAGER = "fake:manager"


def _vote_out() -> VoteOut:
    return VoteOut(
        id=uuid4(),
        meetingId=uuid4(),
        eligibleGroup=str(GID),
        config=ElectionConfig.model_validate(_econfig()).as_vote_config(),
        status="closed",
        result="elected",
        secret=True,
        tally=_TALLY,
        kind="election",
        electionResult=ElectionResultOut(counts={"c1": 1}, elected=["c1"]),
    )


class _FakeVoting:
    async def assert_can_manage_vote(self, vote_id: UUID, principal: Principal) -> None:
        if _MANAGER not in principal.groups:
            raise ForbiddenError("not allowed to manage this vote")


class _FakeElections:
    calls: list[str] = []

    def __init__(self, voting: object) -> None:
        self.voting = voting

    async def draw_lot(self, vote_id: UUID, principal: Principal, *, now: object) -> VoteOut:
        _FakeElections.calls.append(f"lot:{principal.sub}")
        return _vote_out()


class _Pub:
    def __init__(self) -> None:
        self.lots: list[object] = []

    async def vote_lot_drawn(self, vote: object) -> None:
        self.lots.append(vote)


@pytest.fixture
def routes(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, _Pub]:
    from app.modules.livevote.publisher import get_meeting_publisher

    _FakeElections.calls = []
    monkeypatch.setattr(voting_router, "ElectionService", _FakeElections)
    app = create_app()
    pub = _Pub()
    app.dependency_overrides[voting_router.get_voting_service] = lambda: _FakeVoting()
    app.dependency_overrides[get_meeting_publisher] = lambda: pub
    app.dependency_overrides[get_current_applicant] = lambda: None
    return app, pub


def _login(app: FastAPI, *groups: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="p", groups=set(groups)
    )


def test_route_draw_lot_publishes_the_result(routes: tuple[FastAPI, _Pub]) -> None:
    app, pub = routes
    _login(app, _MANAGER)
    r = TestClient(app).post(f"/api/votes/{uuid4()}/draw-lot")
    assert r.status_code == 200
    assert r.json()["electionResult"]["elected"] == ["c1"]
    assert len(pub.lots) == 1
    assert _FakeElections.calls == ["lot:p"]


@pytest.mark.parametrize("path", ["draw-lot"])
def test_routes_need_the_manage_right(routes: tuple[FastAPI, _Pub], path: str) -> None:
    app, _ = routes
    _login(app, f"vote:{GID}")
    r = TestClient(app).post(f"/api/votes/{uuid4()}/{path}")
    assert r.status_code == 403
    assert r.headers["content-type"] == "application/problem+json"
    assert _FakeElections.calls == []


def test_ballot_body_takes_a_list(routes: tuple[FastAPI, _Pub]) -> None:
    from app.modules.voting.schemas import BallotIn

    assert BallotIn.model_validate({"choice": ["c1"]}).choice == ["c1"]
    with pytest.raises(ValueError):
        BallotIn.model_validate({"choice": ""})


def test_runoff_route_is_gone(routes: tuple[FastAPI, _Pub]) -> None:
    """There is no runoff: a tie in an election is decided by lot (§F/meetings/voting/000027)."""
    app, _ = routes
    _login(app, _MANAGER)
    r = TestClient(app).post(f"/api/votes/{uuid4()}/runoff")
    assert r.status_code in (404, 405)
