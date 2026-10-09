"""VotingService: the decision proposal of a vote (F1)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.applications.decision import CODE_AMOUNT_EXCEEDS, CODE_NOT_ALLOWED, DecisionIn
from app.modules.auth.principal import Principal
from app.modules.flow.schemas import TransitionOut
from app.modules.voting import service as voting_service
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteCreateInternal
from app.modules.voting.service import VotingService
from app.shared.errors import ConflictError, ValidationProblem
from tests._support.flow_fakes import fake_session, result
from tests.unit.modules.voting.test_voting_service_unit import (
    GID,
    _config,
    _create_body,
    _FakeFlow,
    _patch_flow,
    _vote,
    _voter,
)

__all__ = ["_patch_flow"]  # the fixture, imported for its side effect

PROPOSAL = {"approvedAmount": "800.00", "conditions": ["Belege nachreichen"]}


class _Recorder:
    """Stands in for `record_decision` and keeps each call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.row = SimpleNamespace(status_event_id=None)

    async def __call__(self, _session: Any, app: Any, decision: DecisionIn, **kw: Any) -> Any:
        self.calls.append({"app": app, "decision": decision, **kw})
        return self.row


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(voting_service, "record_decision", rec)
    return rec


def _with_app(monkeypatch: pytest.MonkeyPatch, **kw: Any) -> SimpleNamespace:
    app = SimpleNamespace(
        **{"id": uuid4(), "amount": Decimal("1000.00"), "approved_amount": None, **kw}
    )

    async def _get(self: VotingService, application_id: UUID, **_kw: Any) -> Any:
        return app

    monkeypatch.setattr(VotingService, "_get_application", _get)
    return app


def _branch(patch: type[_FakeFlow], monkeypatch: pytest.MonkeyPatch) -> UUID:
    """Give the fake flow a `pass` branch whose staged fire names a status event."""
    patch.branch = TransitionOut(id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={})
    event_id = uuid4()
    original = _FakeFlow.stage_branch

    async def _stage(self: _FakeFlow, *args: Any, **kw: Any) -> Any:
        staged = await original(self, *args, **kw)
        staged.status_event_id = event_id
        return staged

    monkeypatch.setattr(_FakeFlow, "stage_branch", _stage)
    return event_id


# --- create ---------------------------------------------------------------------------


async def test_create_stores_the_proposal() -> None:
    app = SimpleNamespace(
        id=uuid4(),
        current_state_id=None,
        gremium_id=GID,
        vote_gremium_id=None,
        amount=Decimal("1000"),
    )
    db = fake_session(result(app), result((uuid4(), ["vote.cast"])))
    db.scalar_results = [GID]
    out = await VotingService(db).create(
        app.id, _create_body(proposal=PROPOSAL), Principal(sub="m")
    )
    vote = next(a for a in db.added if isinstance(a, Vote))
    assert vote.proposal == PROPOSAL
    assert out.proposal == DecisionIn.model_validate(PROPOSAL)


async def test_create_refuses_an_amount_above_the_requested_one() -> None:
    app = SimpleNamespace(id=uuid4(), amount=Decimal("500"))
    db = fake_session(result(app))
    db.scalar_results = [GID]
    with pytest.raises(ValidationProblem) as exc:
        await VotingService(db).create(app.id, _create_body(proposal=PROPOSAL), Principal(sub="m"))
    assert exc.value.code == CODE_AMOUNT_EXCEEDS


def _internal(**over: Any) -> VoteCreateInternal:
    return VoteCreateInternal.model_validate(
        {"config": _config(), "eligibleGroup": str(GID), "eligibleCount": 3, **over}
    )


async def test_create_internal_refuses_a_proposal_without_application() -> None:
    db = fake_session()
    with pytest.raises(ValidationProblem) as exc:
        await VotingService(db).create_internal(None, _internal(proposal=PROPOSAL))
    assert exc.value.code == CODE_NOT_ALLOWED


async def test_create_internal_checks_the_proposal_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_app(monkeypatch, amount=Decimal("100"))
    with pytest.raises(ValidationProblem) as exc:
        await VotingService(fake_session()).create_internal(uuid4(), _internal(proposal=PROPOSAL))
    assert exc.value.code == CODE_AMOUNT_EXCEEDS


async def test_create_internal_without_proposal_and_without_application() -> None:
    db = fake_session()
    out = await VotingService(db).create_internal(None, _internal())
    assert out.proposal is None


# --- close ----------------------------------------------------------------------------


async def test_close_passed_records_the_proposal_and_links_the_event(
    _patch_flow: type[_FakeFlow],
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
) -> None:
    event_id = _branch(_patch_flow, monkeypatch)
    app = _with_app(monkeypatch, approved_amount=Decimal("900.00"))
    vote = _vote(proposal=PROPOSAL)
    db = fake_session(result(vote), result("yes", "yes", "no"))
    out = await VotingService(db).close(vote.id, _voter(sub="closer"), now=None)
    assert out.branch_fired is True
    (call,) = recorder.calls
    assert call["app"] is app
    assert call["decision"].approved_amount == Decimal("800.00")
    assert call["decision"].conditions == ["Belege nachreichen"]
    assert call["actor"] == "closer"
    assert call["decided_by"] is None
    assert call["old_approved"] == Decimal("900.00")
    assert call["vote_id"] == vote.id
    assert recorder.row.status_event_id == event_id


async def test_close_passed_with_blocked_branch_keeps_the_decision(
    _patch_flow: type[_FakeFlow],
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
) -> None:
    _patch_flow.branch = TransitionOut(id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={})
    _patch_flow.fire_raises = ConflictError("guard", code="guard_failed")
    _with_app(monkeypatch)
    vote = _vote(proposal=PROPOSAL)
    db = fake_session(result(vote), result("yes"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.branch_fired is False
    assert len(recorder.calls) == 1
    assert recorder.row.status_event_id is None


async def test_close_rejected_writes_no_decision(
    _patch_flow: type[_FakeFlow],
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
) -> None:
    _with_app(monkeypatch)
    vote = _vote(proposal=PROPOSAL)
    db = fake_session(result(vote), result("no", "no"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.result == "rejected"
    assert recorder.calls == []


async def test_close_passed_without_proposal_writes_no_decision(
    _patch_flow: type[_FakeFlow],
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
) -> None:
    _branch(_patch_flow, monkeypatch)
    vote = _vote()
    db = fake_session(result(vote), result("yes"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.branch_fired is True
    assert recorder.calls == []


async def test_close_with_gremium_mismatch_writes_no_decision(
    _patch_flow: type[_FakeFlow],
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
) -> None:
    async def _mismatch(self: VotingService, vote: Any) -> bool:
        return True

    monkeypatch.setattr(VotingService, "vote_gremium_mismatch", _mismatch)
    vote = _vote(proposal=PROPOSAL)
    db = fake_session(result(vote), result("yes"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.branch_fired is False
    assert recorder.calls == []


@pytest.mark.parametrize("amount", [Decimal("500.00"), None])
async def test_close_clamps_an_amount_above_the_current_request(
    _patch_flow: type[_FakeFlow],
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
    amount: Decimal | None,
) -> None:
    _branch(_patch_flow, monkeypatch)
    _with_app(monkeypatch, amount=amount)
    vote = _vote(proposal=PROPOSAL)
    db = fake_session(result(vote), result("yes"))
    await VotingService(db).close(vote.id, _voter())
    (call,) = recorder.calls
    assert call["decision"].approved_amount is None
    assert call["decision"].conditions == ["Belege nachreichen"]


async def test_close_keeps_a_proposal_as_requested(
    _patch_flow: type[_FakeFlow],
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
) -> None:
    _branch(_patch_flow, monkeypatch)
    _with_app(monkeypatch)
    vote = _vote(proposal={"approvedAmount": None, "conditions": ["A"]})
    db = fake_session(result(vote), result("yes"))
    await VotingService(db).close(vote.id, _voter())
    assert recorder.calls[0]["decision"].approved_amount is None
