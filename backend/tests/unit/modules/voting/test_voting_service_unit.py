"""VotingService (T-15): lifecycle, RBAC and race branches without a database.

The real database constraints (UNIQUE double ballot, ON CONFLICT) belong to the
integration tests. Here a result-queue fake hits every service branch in a
deterministic way, which gives full branch coverage.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest import mock
from uuid import UUID, uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.flow.schemas import TransitionOut, TransitionResult
from app.modules.voting import service as voting_service
from app.modules.voting.schemas import VoteCreate
from app.modules.voting.service import VotingService, open_tally_revealed
from app.shared.config_schemas import VoteConfig
from app.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationProblem,
)
from tests._support.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
OPTIONS = ["yes", "no", "abstain"]


def _config(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "options": OPTIONS,
        "majorityRule": "simple",
        "quorum": None,
        "abstainCountsQuorum": True,
        "secret": False,
        "allowChange": True,
        "tieBreak": "rejected",
    }
    base.update(over)
    return VoteConfig.model_validate(base).model_dump(by_alias=True)


def _vote(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "application_id": uuid4(),
        "meeting_id": None,
        "eligible_group": "stupa",
        "config": _config(),
        "eligible_count": 10,
        "opens_at": None,
        "closes_at": None,
        "status": "open",
        "result": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _voter(*, group: str = "stupa", sub: str = "v1") -> Principal:
    return Principal(sub=sub, permissions={"vote.cast"}, groups={group})


async def test_create_ok() -> None:
    app = SimpleNamespace(id=uuid4())
    db = fake_session(result(app))
    payload = VoteCreate.model_validate(
        {"config": VoteConfig.model_validate(
            {"options": OPTIONS, "majorityRule": "simple"}).model_dump(by_alias=True),
         "eligibleGroup": "stupa"}
    )
    out = await VotingService(db).create(app.id, payload)
    assert out.status == "draft"
    assert out.eligible_group == "stupa"
    assert out.tally.counts == {"yes": 0, "no": 0, "abstain": 0}
    assert db.committed == 1


def test_votecreate_percent_quorum_requires_eligible_count() -> None:
    """A percent quorum without an eligible count fails closed with 422."""
    with pytest.raises(ValueError, match="eligibleCount"):
        VoteCreate.model_validate(
            {
                "config": _config(quorum={"type": "percent", "value": 50}),
                "eligibleGroup": "stupa",
            }
        )


def test_votecreate_percent_quorum_with_eligible_count_ok() -> None:
    payload = VoteCreate.model_validate(
        {
            "config": _config(quorum={"type": "percent", "value": 50}),
            "eligibleGroup": "stupa",
            "eligibleCount": 12,
        }
    )
    assert payload.eligible_count == 12


async def test_create_unknown_application_404() -> None:
    db = fake_session(result())
    payload = VoteCreate.model_validate(
        {"config": VoteConfig.model_validate(
            {"options": OPTIONS, "majorityRule": "simple"}).model_dump(by_alias=True),
         "eligibleGroup": "stupa"}
    )
    with pytest.raises(NotFoundError):
        await VotingService(db).create(uuid4(), payload)


async def test_open_sets_window_keeps_roster_eligible() -> None:
    # The roster sets eligible_count at create time. It never counts logged-in users,
    # so open() recounts nothing.
    vote = _vote(status="draft", eligible_count=20)
    db = fake_session(result(vote))  # only _get_vote, no count query
    out = await VotingService(db).open(vote.id, now=NOW)
    assert out.status == "open"
    assert out.opens_at == NOW
    assert out.tally.eligible == 20


async def test_open_non_draft_409() -> None:
    vote = _vote(status="open")
    db = fake_session(result(vote))
    with pytest.raises(ConflictError):
        await VotingService(db).open(vote.id, now=NOW)


async def test_open_unknown_vote_404() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await VotingService(db).open(uuid4(), now=NOW)


async def test_cast_not_open_409() -> None:
    vote = _vote(status="draft")
    db = fake_session(result(vote))
    with pytest.raises(ConflictError, match="not open"):
        await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)


async def test_cast_window_closed_409() -> None:
    vote = _vote(closes_at=NOW - timedelta(minutes=1))
    db = fake_session(result(vote))
    with pytest.raises(ConflictError, match="window"):
        await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)


async def test_cast_not_in_group_403() -> None:
    vote = _vote()
    db = fake_session(result(vote))
    with pytest.raises(ForbiddenError):
        await VotingService(db).cast(vote.id, _voter(group="other"), "yes", now=NOW)


async def test_cast_blocked_when_voting_right_delegated_403() -> None:
    # #delegation-rework: an outgoing vote delegation for THIS meeting
    # (is_delegator=True, delegate_voting=True) forbids an own ballot.
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(result(vote), result((True, True, _voter().sub)))
    with pytest.raises(ForbiddenError, match="delegated"):
        await VotingService(db).cast(
            vote.id, _voter(group=str(gid)), "yes", now=NOW
        )
    assert db.committed == 0


async def test_cast_nonvoting_delegation_does_not_block_member() -> None:
    # A non-voting delegation, for example a pure meeting delegation, does not block
    # the own voting right of a member.
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(
        result(vote),
        result((True, False, _voter().sub)),  # outgoing NON-voting delegation
        result(SimpleNamespace(inserted=True)),  # ballot insert
    )
    # Gremium vote: the right to vote comes from the namespaced key (AUD-066) that a
    # real vote.cast membership sets, not from the bare UUID string.
    out = await VotingService(db).cast(
        vote.id, _voter(group=vote_group_key(gid)), "yes", now=NOW
    )
    assert out.status == "cast"
    assert db.committed == 1


async def test_cast_exercising_delegated_vote_is_audited() -> None:
    # External substitute: not in eligible_group, but the receiver of a vote delegation
    # of the meeting. The delegated ballot (as_delegation=True) goes under the sub of
    # the delegator and writes a DELEGATION_USE audit entry.
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(
        result(vote),
        result((False, True, "delegator-1")),  # incoming vote delegation
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        result(SimpleNamespace(inserted=True)),  # ballot insert (allowChange → xmax)
    )
    out = await VotingService(db).cast(
        vote.id, _voter(group="somewhere-else"), "yes", now=NOW, as_delegation=True
    )
    assert out.status == "cast"
    assert db.committed == 1
    assert any(type(a).__name__ == "AuditEntry" for a in db.added)


async def test_cast_own_vote_unaffected_by_incoming_delegation() -> None:
    # Member WITH an incoming delegation: the own ballot still runs as a separate cast.
    # Without as_delegation the service writes no audit entry and the ballot uses the
    # own sub.
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(
        result(vote),
        result((False, True, "delegator-1")),  # incoming vote delegation
        result(SimpleNamespace(inserted=True)),  # ballot insert
    )
    out = await VotingService(db).cast(
        vote.id, _voter(group=vote_group_key(gid)), "yes", now=NOW
    )
    assert out.status == "cast"
    assert not any(type(a).__name__ == "AuditEntry" for a in db.added)


async def test_cast_as_delegation_without_incoming_403() -> None:
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(result(vote), result())
    with pytest.raises(ForbiddenError, match="delegated"):
        await VotingService(db).cast(
            vote.id, _voter(group=str(gid)), "yes", now=NOW, as_delegation=True
        )


async def test_cast_vote_without_meeting_skips_delegation_check() -> None:
    vote = _vote()  # meeting_id=None, so the service runs no delegation query
    db = fake_session(result(vote), result(SimpleNamespace(inserted=True)))
    out = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert out.status == "cast"


async def test_cast_unknown_option_422() -> None:
    vote = _vote()
    db = fake_session(result(vote))
    with pytest.raises(ValidationProblem):
        await VotingService(db).cast(vote.id, _voter(), "maybe", now=NOW)


async def test_cast_open_first_vote() -> None:
    vote = _vote(config=_config(allowChange=False))
    db = fake_session(result(vote), result(SimpleNamespace(id=uuid4())))
    out = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert out.status == "cast"
    assert db.committed == 1


async def test_cast_open_double_no_change_409() -> None:
    vote = _vote(config=_config(allowChange=False))
    db = fake_session(result(vote), result())  # an empty RETURNING means conflict
    with pytest.raises(ConflictError, match="Already voted"):
        await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    # ON CONFLICT DO NOTHING wrote nothing, so there is no commit. get_session
    # rolls the transaction back.
    assert db.committed == 0


async def test_cast_open_allowchange_first_vote_is_cast() -> None:
    # allowChange plus a first ballot (INSERT, xmax=0) gives "cast", not "changed".
    vote = _vote(config=_config(allowChange=True))
    db = fake_session(result(vote), result(SimpleNamespace(inserted=True)))
    out = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert out.status == "cast"
    assert db.committed == 1


async def test_cast_open_change_updates() -> None:
    # allowChange plus an existing ballot (UPDATE through ON CONFLICT) gives "changed".
    vote = _vote(config=_config(allowChange=True))
    db = fake_session(result(vote), result(SimpleNamespace(inserted=False)))
    out = await VotingService(db).cast(vote.id, _voter(), "no", now=NOW)
    assert out.status == "changed"
    assert db.committed == 1


async def test_cast_open_allowchange_empty_returning_is_changed() -> None:
    # Defensive: an empty RETURNING gives no row. The service sees no insert and
    # reports "changed".
    vote = _vote(config=_config(allowChange=True))
    db = fake_session(result(vote), result())
    out = await VotingService(db).cast(vote.id, _voter(), "no", now=NOW)
    assert out.status == "changed"


async def test_cast_secret_first_vote_writes_anonymous() -> None:
    vote = _vote(config=_config(secret=True))
    db = fake_session(result(vote), result(SimpleNamespace(id=uuid4())))
    out = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert out.status == "cast"
    # The service adds a secret_ballot without an identity and no ballot.
    assert len(db.added) == 1
    assert type(db.added[0]).__name__ == "SecretBallot"
    assert db.committed == 1


async def test_cast_secret_double_409() -> None:
    vote = _vote(config=_config(secret=True))
    db = fake_session(result(vote), result())  # the marker exists, so conflict
    with pytest.raises(ConflictError, match="Already voted"):
        await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert db.committed == 0


async def test_get_open_aggregates_tally() -> None:
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes", "no"))
    out = await VotingService(db).get(vote.id)
    assert out.tally.counts == {"yes": 2, "no": 1, "abstain": 0}
    assert out.tally.result is None  # still open, so no final result


async def test_get_closed_includes_result() -> None:
    vote = _vote(status="closed", result="passed")
    db = fake_session(result(vote), result("yes", "yes", "no"))
    out = await VotingService(db).get(vote.id)
    assert out.result == "passed"
    assert out.tally.result == "passed"


async def test_get_secret_hides_counts_until_close() -> None:
    # Secret: no choice counts before the close, only participation (#vote-progress).
    vote = _vote(config=_config(secret=True))
    db = fake_session(result(vote), result("yes", "no", "yes"))
    out = await VotingService(db).get(vote.id)
    assert out.secret is True
    assert out.tally.revealed is False
    assert out.tally.counts == {}
    assert out.tally.voted == 3  # participation stays visible


class _FakeFlow:
    available: ClassVar[list[TransitionOut]] = []
    calls: ClassVar[list[str | None]] = []
    new_state: ClassVar[Any] = uuid4()
    fire_raises: ClassVar[Exception | None] = None
    branch: ClassVar[Any] = None
    branch_calls: ClassVar[list[str]] = []

    def __init__(self, session: object, dispatcher: object) -> None:
        self.fired: dict[str, object] | None = None
        self._available: list[TransitionOut] = _FakeFlow.available

    async def branch_transition(self, application_id, branch):  # noqa: ANN001
        _FakeFlow.branch_calls.append(branch)
        return _FakeFlow.branch

    async def available_transitions(self, application_id, principal, *, deadline_passed=False):  # noqa: ANN001
        _FakeFlow.calls.append("called")
        return self._available

    async def fire_branch(self, application_id, branch, principal, *, note=None):  # noqa: ANN001
        if _FakeFlow.fire_raises is not None:
            raise _FakeFlow.fire_raises
        self.fired = {"branch": branch, "note": note}
        return TransitionResult(
            newStateId=_FakeFlow.new_state, statusEventId=uuid4(), dispatchedActions=[]
        )


@pytest.fixture
def _patch_flow(monkeypatch: pytest.MonkeyPatch) -> type[_FakeFlow]:
    _FakeFlow.available = []
    _FakeFlow.calls = []
    _FakeFlow.new_state = uuid4()
    _FakeFlow.fire_raises = None
    _FakeFlow.branch = None
    _FakeFlow.branch_calls = []
    monkeypatch.setattr(voting_service, "FlowService", _FakeFlow)
    return _FakeFlow


async def test_close_fires_matching_branch(_patch_flow: type[_FakeFlow]) -> None:
    branch_t = TransitionOut(
        id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={}
    )
    _patch_flow.branch = branch_t
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes", "yes", "no"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.result == "passed"
    assert out.tally.result == "passed"
    assert out.fired_transition_id == branch_t.id
    assert out.new_state_id == _patch_flow.new_state
    assert _patch_flow.branch_calls == ["pass"]


async def test_close_prefers_global_flow_branch(_patch_flow: type[_FakeFlow]) -> None:
    """Fire the `pass` branch directly from a `vote` state (#28).

    The close path never uses the guard-based `available_transitions` path.
    """
    branch_t = TransitionOut(id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={})
    _patch_flow.branch = branch_t
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes", "yes", "no"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.result == "passed"
    assert out.fired_transition_id == branch_t.id
    assert _patch_flow.branch_calls == ["pass"]
    assert _patch_flow.calls == []  # the guard path stays unused


async def test_close_application_vote_without_branch_raises_conflict(
    _patch_flow: type[_FakeFlow],
) -> None:
    """Fail closed with 409 when an application vote finds no matching branch.

    The service must not close the vote in silence. The result would be final while
    the application stays forever in the state before the vote. The vote result and
    the flow state would drift apart.
    """
    _patch_flow.available = []  # no matching transition
    vote = _vote()  # application_id is set
    db = fake_session(result(vote), result("no", "no", "yes"))
    with pytest.raises(ConflictError):
        await VotingService(db).close(vote.id, _voter())
    assert db.committed == 0  # no silent partial commit


async def test_close_generic_vote_without_application_just_closes(
    _patch_flow: type[_FakeFlow],
) -> None:
    """A generic vote without an application fires NO branch.

    The vote only holds the result for the protocol. The close commits itself.
    """
    _patch_flow.available = []
    vote = _vote(application_id=None)
    db = fake_session(result(vote), result("no", "no", "yes"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.result == "rejected"
    assert out.fired_transition_id is None
    assert out.new_state_id is None
    assert db.committed == 1


async def test_close_atomic_fire_failure_does_not_commit(
    _patch_flow: type[_FakeFlow],
) -> None:
    """A `fire` error during the close writes NO commit.

    The vote stays open and the caller can repeat the close. There is no state where
    the vote is closed but the branch never fired. The close is atomic with `fire`.
    """
    branch_t = TransitionOut(
        id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={}
    )
    _patch_flow.branch = branch_t
    _patch_flow.fire_raises = ConflictError("guard", code="guard_failed")
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes"))
    with pytest.raises(ConflictError):
        await VotingService(db).close(vote.id, _voter())
    # The close never committed. The vote change stays unsaved in the session, and
    # get_session rolls back on the exception.
    assert db.committed == 0


async def test_close_non_open_409() -> None:
    vote = _vote(status="closed")
    db = fake_session(result(vote))
    with pytest.raises(ConflictError):
        await VotingService(db).close(vote.id, _voter())


async def test_close_unknown_vote_404() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await VotingService(db).close(uuid4(), _voter())


async def test_close_blocked_without_quorum(_patch_flow: type[_FakeFlow]) -> None:
    """Return 409 when the quorum fails, instead of a silent "rejected" (#12).

    The vote stays open. The caller collects more ballots or cancels the vote.
    """
    vote = _vote(
        config=_config(quorum={"type": "percent", "value": 50}), eligible_count=10
    )
    db = fake_session(result(vote), result("yes", "no"))  # 2/10, so the quorum fails
    with pytest.raises(ConflictError):
        await VotingService(db).close(vote.id, _voter())
    assert db.committed == 0
    assert vote.status == "open"


async def test_close_expired_unmet_quorum_fires_fail_branch(
    _patch_flow: type[_FakeFlow],
) -> None:
    """Close a timed vote for good when the window expired and the quorum failed.

    The cron passes `now`. The service fires the `fail` branch and closes the vote,
    so the vote never stays stuck (#stuck-vote).
    """
    branch_t = TransitionOut(id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={})
    _patch_flow.branch = branch_t
    vote = _vote(
        config=_config(quorum={"type": "percent", "value": 50}),
        eligible_count=10,
        closes_at=NOW - timedelta(minutes=1),
    )
    db = fake_session(result(vote), result("yes", "no"))  # 2/10, so the quorum fails
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert vote.status == "closed"
    assert out.result == "rejected"
    assert out.tally.failed_reason == "quorum"
    assert out.fired_transition_id == branch_t.id
    assert _patch_flow.branch_calls == ["fail"]


async def test_close_expired_unmet_quorum_generic_vote_just_closes(
    _patch_flow: type[_FakeFlow],
) -> None:
    """Close an expired generic vote for good and fire no branch.

    The vote has no application. The close commits itself.
    """
    vote = _vote(
        application_id=None,
        config=_config(quorum={"type": "percent", "value": 50}),
        eligible_count=10,
        closes_at=NOW - timedelta(minutes=1),
    )
    db = fake_session(result(vote), result("yes", "no"))
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert vote.status == "closed"
    assert out.result == "rejected"
    assert out.fired_transition_id is None
    assert db.committed == 1


async def test_close_now_but_window_not_expired_still_blocks(
    _patch_flow: type[_FakeFlow],
) -> None:
    """Keep the 409 when `now` is set but the window is still open."""
    vote = _vote(
        config=_config(quorum={"type": "percent", "value": 50}),
        eligible_count=10,
        closes_at=NOW + timedelta(minutes=5),
    )
    db = fake_session(result(vote), result("yes", "no"))
    with pytest.raises(ConflictError):
        await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert vote.status == "open"


async def test_close_now_untimed_vote_still_blocks(
    _patch_flow: type[_FakeFlow],
) -> None:
    """Keep the 409 when `now` is set but `closes_at` is None, so no window exists."""
    vote = _vote(
        config=_config(quorum={"type": "percent", "value": 50}),
        eligible_count=10,
        closes_at=None,
    )
    db = fake_session(result(vote), result("yes", "no"))
    with pytest.raises(ConflictError):
        await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert vote.status == "open"


async def test_cancel_open_vote_sets_cancelled_without_branch() -> None:
    vote = _vote()
    db = fake_session(result(vote), result())
    out = await VotingService(db).cancel(vote.id)
    assert vote.status == "cancelled"
    assert out.status == "cancelled"
    assert db.committed == 1


async def test_cancel_non_open_409() -> None:
    vote = _vote(status="draft")
    db = fake_session(result(vote))
    with pytest.raises(ConflictError):
        await VotingService(db).cancel(vote.id)


async def test_cancel_closed_409() -> None:
    vote = _vote(status="closed")
    db = fake_session(result(vote))
    with pytest.raises(ConflictError):
        await VotingService(db).cancel(vote.id)


async def test_create_without_application_skips_lookup() -> None:
    # With application_id=None the service runs no _get_application query (branch
    # 195->197).
    db = fake_session()
    payload = VoteCreate.model_validate(
        {"config": VoteConfig.model_validate(
            {"options": OPTIONS, "majorityRule": "simple"}).model_dump(by_alias=True),
         "eligibleGroup": "stupa"}
    )
    out = await VotingService(db).create(None, payload)
    assert out.status == "draft"
    assert out.application_id is None
    assert db.committed == 1


async def test_delete_vote_in_meeting_removes_and_commits() -> None:
    mid = uuid4()
    vote = _vote(meeting_id=mid)
    db = fake_session(result(vote))
    await VotingService(db).delete(vote.id, meeting_id=mid)
    assert vote in db.deleted
    assert db.committed == 1


async def test_delete_vote_from_other_meeting_404() -> None:
    vote = _vote(meeting_id=uuid4())
    db = fake_session(result(vote))
    with pytest.raises(NotFoundError, match="not found in this meeting"):
        await VotingService(db).delete(vote.id, meeting_id=uuid4())
    assert db.deleted == []


# A meeting vote reveals the counts only when every expected ballot arrived. The
# denominator comes from the attendance roster (#vote-progress).
async def test_get_meeting_open_reveals_when_all_present_voted() -> None:
    vote = _vote(meeting_id=uuid4())  # open, not secret
    db = fake_session(result(vote), result("yes", "yes"))
    db.scalar_results = [2]  # present=2, voted=2 → revealed
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is True
    assert out.tally.counts == {"yes": 2, "no": 0, "abstain": 0}


async def test_get_meeting_open_hidden_until_all_present_voted() -> None:
    vote = _vote(meeting_id=uuid4())
    db = fake_session(result(vote), result("yes", "yes"))
    db.scalar_results = [3]  # present=3 > voted=2 → hidden
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is False
    assert out.tally.counts == {}
    assert out.tally.voted == 2


async def test_get_meeting_open_without_attendance_stays_hidden() -> None:
    vote = _vote(meeting_id=uuid4())
    db = fake_session(result(vote), result())
    db.scalar_results = [0]  # present=0 → present>0 False
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is False


def test_open_tally_revealed_rule() -> None:
    # present must be above 0 AND voted must reach expected (#vote-progress).
    assert open_tally_revealed(present=2, voted=2, expected=2) is True
    assert open_tally_revealed(present=2, voted=3, expected=2) is True
    assert open_tally_revealed(present=2, voted=1, expected=2) is False
    assert open_tally_revealed(present=0, voted=0, expected=0) is False


async def test_get_meeting_open_hidden_until_proxy_voted() -> None:
    # #vote-progress: 2 present members plus 1 vote delegation of an ABSENT delegator
    # give expected=3. Only the 2 own ballots arrived, so the proxy ballot is still
    # missing and the tally stays hidden.
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(result(vote), result("yes", "yes"))
    db.scalar_results = [2, 1]  # present=2, absent-delegated=1 → expected=3
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is False
    assert out.tally.counts == {}


async def test_get_meeting_open_reveals_when_proxy_also_voted() -> None:
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(result(vote), result("yes", "yes", "no"))
    db.scalar_results = [2, 1]  # present=2 + 1 proxy → expected=3, voted=3 → revealed
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is True
    assert out.tally.counts == {"yes": 2, "no": 1, "abstain": 0}


async def test_absent_delegated_count_no_meeting_is_zero() -> None:
    vote = _vote(meeting_id=None)
    svc = VotingService(fake_session())
    assert await svc._absent_delegated_count(vote) == 0  # pyright: ignore[reportArgumentType]


async def test_absent_delegated_count_non_uuid_group_is_zero() -> None:
    # An eligible_group that is not UUID text, "stupa" for example, runs no delegation
    # query.
    vote = _vote(meeting_id=uuid4(), eligible_group="stupa")
    svc = VotingService(fake_session())
    assert await svc._absent_delegated_count(vote) == 0  # pyright: ignore[reportArgumentType]


async def test_absent_delegated_count_queries_when_uuid_group() -> None:
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session()
    db.scalar_results = [4]
    assert await VotingService(db)._absent_delegated_count(vote) == 4  # pyright: ignore[reportArgumentType]


async def test_absent_delegated_count_none_scalar_is_zero() -> None:
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session()
    db.scalar_results = [None]  # COUNT → None → 0 through the or-default
    assert await VotingService(db)._absent_delegated_count(vote) == 0  # pyright: ignore[reportArgumentType]


# Object-level authorization lives in assert_can_read and get_scoped (#sec-audit).
async def test_assert_can_read_meeting_vote_goes_through_the_meeting_guard() -> None:
    """Even an admin reads a meeting-bound vote through the meeting guard.

    The admin used to return early here on a raw `principal.roles` read, before the
    meeting check ran. That skipped `Principal.has`, which is where the OAuth scope cap
    lives, so a narrowly scoped token issued to an admin read as a full admin.
    """
    seen: list[UUID] = []

    class _Meetings:
        def __init__(self, _session: object) -> None: ...

        async def assert_can_read(self, meeting_id: UUID, _principal: object) -> None:
            seen.append(meeting_id)

    svc = VotingService(fake_session())
    admin = Principal(sub="a", roles=["admin"])
    meeting_id = uuid4()
    with mock.patch("app.modules.livevote.service.MeetingService", _Meetings):
        await svc.assert_can_read(_vote(meeting_id=meeting_id), admin)  # pyright: ignore[reportArgumentType]
    assert seen == [meeting_id]


async def test_assert_can_manage_denies_a_scope_capped_admin_token() -> None:
    """A token scoped below `vote.manage` cannot open, close or cancel a vote.

    The guard used to return early on `"admin" in principal.roles`, so an agent token
    issued to an admin with only the `read` scope managed votes. `Principal.has` applies
    the cap; the raw role read did not.
    """
    svc = VotingService(fake_session())
    capped = Principal(
        sub="a", roles=["admin"], scope_permissions=frozenset({"application.read"})
    )
    with pytest.raises(ForbiddenError):
        await svc.assert_can_manage_group("stupa", None, capped)


async def test_assert_can_manage_allows_an_admin_session() -> None:
    """The cookie session of an admin is uncapped and still manages votes."""
    svc = VotingService(fake_session())
    await svc.assert_can_manage_group("stupa", None, Principal(sub="a", roles=["admin"]))


async def test_assert_can_read_sessionless_with_permission() -> None:
    svc = VotingService(fake_session())
    p = Principal(sub="u", permissions={"application.read"})
    await svc.assert_can_read(_vote(meeting_id=None), p)  # pyright: ignore[reportArgumentType]


async def test_assert_can_read_sessionless_denied_403() -> None:
    svc = VotingService(fake_session())
    with pytest.raises(ForbiddenError):
        await svc.assert_can_read(_vote(meeting_id=None), Principal(sub="u"))  # pyright: ignore[reportArgumentType]


async def test_assert_can_read_meeting_delegates_to_meeting_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class _FakeMeeting:
        def __init__(self, session: object) -> None:
            self.session = session

        async def assert_can_read(self, meeting_id: Any, _principal: Principal) -> None:
            seen["meeting_id"] = meeting_id

    monkeypatch.setattr("app.modules.livevote.service.MeetingService", _FakeMeeting)
    vote = _vote(meeting_id=uuid4())
    await VotingService(fake_session()).assert_can_read(vote, _voter())  # pyright: ignore[reportArgumentType]
    assert seen["meeting_id"] == vote.meeting_id


async def test_get_scoped_checks_then_returns_tally() -> None:
    vote = _vote(meeting_id=None)
    db = fake_session(result(vote), result(vote), result("yes"))
    p = Principal(sub="u", permissions={"application.read"})
    out = await VotingService(db).get_scoped(vote.id, p)
    assert out.tally.counts == {"yes": 1, "no": 0, "abstain": 0}


# DELETE /votes/{id}: a standalone draft vote that never ran. Everything further
# along stays with `cancel`, so the record keeps every vote that ever opened.


async def test_delete_standalone_draft_ok() -> None:
    from app.modules.audit.models import AuditEntry

    vote = _vote(meeting_id=None, status="draft")
    db = fake_session(result(vote))
    await VotingService(db).delete_standalone(vote.id, actor="mgr")
    assert vote in db.deleted
    assert db.committed == 1
    entries = [o for o in db.added if isinstance(o, AuditEntry)]
    assert [e.action for e in entries] == ["vote_delete"]
    assert entries[0].data["eligibleGroup"] == "stupa"


async def test_delete_standalone_without_application_records_null() -> None:
    vote = _vote(meeting_id=None, status="draft", application_id=None)
    db = fake_session(result(vote))
    await VotingService(db).delete_standalone(vote.id, actor="mgr")
    entry = db.added[0]
    assert entry.data["applicationId"] is None


async def test_delete_standalone_unknown_404() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await VotingService(db).delete_standalone(uuid4(), actor="mgr")


async def test_delete_standalone_meeting_bound_409() -> None:
    # The meeting route owns this vote and applies the meeting-scoped check.
    vote = _vote(meeting_id=uuid4(), status="draft")
    db = fake_session(result(vote))
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).delete_standalone(vote.id, actor="mgr")
    assert ei.value.code == "vote_meeting_bound"
    assert db.deleted == []


async def test_delete_standalone_open_vote_409() -> None:
    vote = _vote(meeting_id=None, status="open")
    db = fake_session(result(vote))
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).delete_standalone(vote.id, actor="mgr")
    assert ei.value.code == "vote_not_draft"
    assert db.deleted == []


async def test_delete_standalone_with_ballots_409() -> None:
    vote = _vote(meeting_id=None, status="draft")
    db = fake_session(result(vote))
    # An open ballot, no secret ballot, no marker: the first count already blocks.
    db.scalar_results = [1, 0, 0]
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).delete_standalone(vote.id, actor="mgr")
    assert ei.value.code == "vote_has_ballots"
    assert db.deleted == []


async def test_delete_standalone_with_secret_marker_409() -> None:
    vote = _vote(meeting_id=None, status="draft")
    db = fake_session(result(vote))
    # A secret vote leaves only the voted_marker as a trace, and that blocks too.
    db.scalar_results = [0, 0, 2]
    with pytest.raises(ConflictError):
        await VotingService(db).delete_standalone(vote.id, actor="mgr")
