"""VotingService: lifecycle, RBAC and race branches without a database.

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
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteCreate, VoteCreateInternal
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
#: The gremium of the default vote. A vote names a gremium UUID as its eligible group.
GID = UUID("00000000-0000-0000-0000-00000000a1b2")


def _config(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "options": OPTIONS,
        "majorityRule": "simple",
        "quorum": None,
        "abstainCountsQuorum": True,
        "secret": False,
        "tieBreak": "rejected",
    }
    base.update(over)
    return VoteConfig.model_validate(base).model_dump(by_alias=True)


def _vote(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "application_id": uuid4(),
        "meeting_id": None,
        "agenda_item_id": None,
        "eligible_group": str(GID),
        "config": _config(),
        "eligible_count": 10,
        "opens_at": None,
        "closes_at": None,
        "closed_at": None,
        "status": "open",
        "result": None,
        "result_branch_transition_id": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _voter(*, group: str = vote_group_key(GID), sub: str = "v1") -> Principal:
    return Principal(sub=sub, groups={group})


def _create_body(**over: Any) -> VoteCreate:
    body: dict[str, Any] = {
        "config": VoteConfig.model_validate(
            {"options": OPTIONS, "majorityRule": "simple"}
        ).model_dump(by_alias=True),
        "eligibleGroup": str(GID),
    }
    body.update(over)
    return VoteCreate.model_validate(body)


async def test_create_ok() -> None:
    """The gremium exists and matches the application; the roster sets the count.

    The scalar is the id of the existing gremium.
    """
    app = SimpleNamespace(id=uuid4(), current_state_id=None, gremium_id=GID, vote_gremium_id=None)
    roster = [(uuid4(), ["vote.cast"]), (uuid4(), ["vote.cast"]), (uuid4(), ["session.manage"])]
    db = fake_session(result(app), result(*roster))
    db.scalar_results = [GID]
    out = await VotingService(db).create(app.id, _create_body(), Principal(sub="m"))
    assert out.status == "draft"
    assert out.eligible_group == str(GID)
    assert out.tally.counts == {"yes": 0, "no": 0, "abstain": 0}
    assert out.tally.eligible == 2
    assert db.committed == 1


def test_votecreate_internal_percent_quorum_requires_eligible_count() -> None:
    """A percent quorum without an eligible count fails closed."""
    with pytest.raises(ValueError, match="eligibleCount"):
        VoteCreateInternal.model_validate(
            {
                "config": _config(quorum={"type": "percent", "value": 50}),
                "eligibleGroup": str(GID),
            }
        )


def test_votecreate_internal_percent_quorum_with_eligible_count_ok() -> None:
    payload = VoteCreateInternal.model_validate(
        {
            "config": _config(quorum={"type": "percent", "value": 50}),
            "eligibleGroup": str(GID),
            "eligibleCount": 12,
        }
    )
    assert payload.eligible_count == 12


async def test_create_unknown_application_404() -> None:
    """An unknown application gives 404, even when the gremium exists."""
    db = fake_session(result())
    db.scalar_results = [GID]
    with pytest.raises(NotFoundError):
        await VotingService(db).create(uuid4(), _create_body(), Principal(sub="m"))


async def test_create_reads_only_a_confirmed_application() -> None:
    """The application query of `create` hides an unconfirmed guest application.

    The scalar is the id of the existing gremium.
    """
    db = fake_session(result())
    db.scalar_results = [GID]
    with pytest.raises(NotFoundError):
        await VotingService(db).create(uuid4(), _create_body(), Principal(sub="m"))
    assert "email_confirmed_at IS NOT NULL" in str(db.statements[0])


async def test_create_internal_unknown_application_404() -> None:
    db = fake_session(result())
    payload = VoteCreateInternal.model_validate(
        {"config": _config(), "eligibleGroup": str(GID), "eligibleCount": 3}
    )
    with pytest.raises(NotFoundError):
        await VotingService(db).create_internal(uuid4(), payload)


async def test_open_sets_window_keeps_roster_eligible() -> None:
    """The open sets the window and keeps the eligible count of the roster.

    The roster sets eligible_count at create time and never counts logged-in users, so
    the open reads only the vote and recounts nothing. The open writes a vote_open audit
    entry with id references only.
    """
    vote = _vote(status="draft", eligible_count=20)
    db = fake_session(result(vote))
    out = await VotingService(db).open(vote.id, now=NOW, actor="mgr")
    assert out.status == "open"
    assert out.opens_at == NOW
    assert out.opened_at == NOW
    assert out.closed_at is None
    assert out.tally.eligible == 20
    entries = [a for a in db.added if type(a).__name__ == "AuditEntry"]
    assert [e.action for e in entries] == ["vote_open"]
    assert entries[0].actor == "mgr"
    assert entries[0].data["applicationId"] == str(vote.application_id)
    assert entries[0].data["meetingId"] is None


async def test_open_non_draft_409() -> None:
    vote = _vote(status="open")
    db = fake_session(result(vote))
    with pytest.raises(ConflictError):
        await VotingService(db).open(vote.id, now=NOW)


async def test_open_unknown_vote_404() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await VotingService(db).open(uuid4(), now=NOW)


async def test_open_meeting_vote_in_a_closed_meeting_409() -> None:
    """The open re-reads the meeting status under the meeting row lock.

    The scalars are the meeting of the vote and its locked status.
    """
    mid = uuid4()
    vote = _vote(status="draft", meeting_id=mid)
    db = fake_session(result(vote))
    db.scalar_results = [mid, "closed"]
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).open(vote.id, now=NOW)
    assert ei.value.code == "meeting_closed"
    assert vote.status == "draft"


async def test_open_meeting_vote_in_a_live_meeting() -> None:
    mid = uuid4()
    vote = _vote(status="draft", meeting_id=mid)
    db = fake_session(result(vote))
    db.scalar_results = [mid, "live"]
    out = await VotingService(db).open(vote.id, now=NOW)
    assert out.status == "open"


async def test_open_prepared_meeting_vote_takes_the_new_roster_count() -> None:
    """A prepared draft waited while the roster changed: the caller recounts it."""
    mid = uuid4()
    vote = _vote(status="draft", meeting_id=mid, eligible_count=20)
    db = fake_session(result(vote))
    db.scalar_results = [mid, "live"]
    out = await VotingService(db).open(vote.id, now=NOW, eligible_count=23)
    assert out.status == "open"
    assert vote.eligible_count == 23
    assert out.tally.eligible == 23


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
    """An outgoing vote delegation for THIS meeting forbids an own ballot.

    The delegation has is_delegator=True and delegate_voting=True.
    """
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(result(vote), result((True, True, _voter().sub)))
    with pytest.raises(ForbiddenError, match="delegated"):
        await VotingService(db).cast(
            vote.id, _voter(group=str(gid)), "yes", now=NOW
        )
    assert db.committed == 0


@pytest.fixture
def marks(monkeypatch: pytest.MonkeyPatch) -> mock.AsyncMock:
    """Stub the attendance mark of a meeting ballot and record its calls."""
    from app.modules.livevote.attendance_service import AttendanceService

    stub = mock.AsyncMock()
    monkeypatch.setattr(AttendanceService, "mark_present_on_cast", stub)
    return stub


async def test_cast_nonvoting_delegation_does_not_block_member(marks: mock.AsyncMock) -> None:
    """A non-voting delegation does not block the own voting right of a member.

    The outgoing delegation is a pure meeting delegation. The right to vote comes from
    the namespaced key that a real vote.cast membership sets, not from the bare UUID
    string. The own ballot of a meeting vote marks the member present.
    """
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(
        result(vote),
        result((True, False, _voter().sub)),
        result(SimpleNamespace(inserted=True)),
    )
    out = await VotingService(db).cast(
        vote.id, _voter(group=vote_group_key(gid)), "yes", now=NOW
    )
    assert out.status == "cast"
    assert db.committed == 1
    marks.assert_awaited_once_with(vote.meeting_id, _voter().sub)


async def test_cast_exercising_delegated_vote_is_audited() -> None:
    """A delegated ballot runs under the sub of the delegator and is audited.

    The external substitute is not in eligible_group, but receives a vote delegation of
    the meeting. The ballot with as_delegation=True writes a DELEGATION_USE audit entry.
    The fake session serves the incoming delegation, the audit advisory lock, the audit
    prev-hash and the ballot insert.
    """
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(
        result(vote),
        result((False, True, "delegator-1")),
        result(),
        result(),
        result(SimpleNamespace(inserted=True)),
    )
    out = await VotingService(db).cast(
        vote.id, _voter(group="somewhere-else"), "yes", now=NOW, as_delegation=True
    )
    assert out.status == "cast"
    assert db.committed == 1
    assert any(type(a).__name__ == "AuditEntry" for a in db.added)


async def test_cast_own_vote_unaffected_by_incoming_delegation(
    marks: mock.AsyncMock,
) -> None:
    """A member with an incoming delegation still casts the own ballot separately.

    Without as_delegation the service writes no audit entry, and the ballot uses the own
    sub.
    """
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(
        result(vote),
        result((False, True, "delegator-1")),
        result(SimpleNamespace(inserted=True)),
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
    """A vote without a meeting runs no delegation query."""
    vote = _vote()
    db = fake_session(result(vote), result(SimpleNamespace(inserted=True)))
    out = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert out.status == "cast"


async def test_cast_unknown_option_422() -> None:
    vote = _vote()
    db = fake_session(result(vote))
    with pytest.raises(ValidationProblem):
        await VotingService(db).cast(vote.id, _voter(), "maybe", now=NOW)


async def test_cast_open_first_vote() -> None:
    """The first open ballot is inserted. The insert never updates an existing ballot."""
    vote = _vote()
    db = fake_session(result(vote), result(SimpleNamespace(id=uuid4())))
    out = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert out.status == "cast"
    assert db.committed == 1
    insert = str(db.statements[-1])
    assert "ON CONFLICT" in insert and "DO NOTHING" in insert
    assert "DO UPDATE" not in insert


async def test_cast_open_double_409_already_voted() -> None:
    """A second cast never changes the ballot. It gives 409 ``already_voted``.

    An empty RETURNING means a conflict. ON CONFLICT DO NOTHING wrote nothing, so there
    is no commit, and ``get_session`` rolls the transaction back.
    """
    vote = _vote()
    db = fake_session(result(vote), result())
    with pytest.raises(ConflictError, match="Already voted") as ei:
        await VotingService(db).cast(vote.id, _voter(), "no", now=NOW)
    assert ei.value.code == "already_voted"
    assert db.committed == 0


async def test_cast_secret_first_vote_writes_anonymous() -> None:
    """The first secret cast adds a secret_ballot without an identity and no ballot."""
    vote = _vote(config=_config(secret=True))
    db = fake_session(result(vote), result(SimpleNamespace(id=uuid4())))
    out = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert out.status == "cast"
    assert len(db.added) == 1
    assert type(db.added[0]).__name__ == "SecretBallot"
    assert db.committed == 1


async def test_cast_secret_double_409() -> None:
    """A second secret cast finds the voted marker and gives 409."""
    vote = _vote(config=_config(secret=True))
    db = fake_session(result(vote), result())
    with pytest.raises(ConflictError, match="Already voted") as ei:
        await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert ei.value.code == "already_voted"
    assert db.committed == 0


async def test_get_open_aggregates_tally() -> None:
    """An open vote aggregates the tally but has no final result yet."""
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes", "no"))
    out = await VotingService(db).get(vote.id)
    assert out.tally.counts == {"yes": 2, "no": 1, "abstain": 0}
    assert out.tally.result is None


async def test_get_closed_includes_result() -> None:
    vote = _vote(status="closed", result="passed")
    db = fake_session(result(vote), result("yes", "yes", "no"))
    out = await VotingService(db).get(vote.id)
    assert out.result == "passed"
    assert out.tally.result == "passed"


async def test_get_secret_hides_counts_until_close() -> None:
    """A secret vote shows no choice counts before the close, only the participation."""
    vote = _vote(config=_config(secret=True))
    db = fake_session(result(vote), result("yes", "no", "yes"))
    out = await VotingService(db).get(vote.id)
    assert out.secret is True
    assert out.tally.revealed is False
    assert out.tally.counts == {}
    assert out.tally.voted == 3


class _FakeFlow:
    """Stand-in for `FlowService` on the close path.

    `branch` None means that the current state has no such branch: `stage_branch` then
    raises NotFoundError, as the real engine does. `fire_raises` makes the stage fail
    with another error (a guard, a lost race).
    """

    available: ClassVar[list[TransitionOut]] = []
    calls: ClassVar[list[str | None]] = []
    new_state: ClassVar[Any] = uuid4()
    fire_raises: ClassVar[Exception | None] = None
    branch: ClassVar[Any] = None
    branch_calls: ClassVar[list[str]] = []
    notes: ClassVar[list[str | None]] = []
    vote_ids: ClassVar[list[UUID | None]] = []
    after: ClassVar[list[bool]] = []

    def __init__(self, session: object, dispatcher: object) -> None:
        self._available: list[TransitionOut] = _FakeFlow.available

    async def available_transitions(self, application_id, principal):
        _FakeFlow.calls.append("called")
        return self._available

    async def stage_branch(self, application_id, branch, principal, *, note=None, vote_id=None):
        _FakeFlow.branch_calls.append(branch)
        _FakeFlow.notes.append(note)
        _FakeFlow.vote_ids.append(vote_id)
        if _FakeFlow.fire_raises is not None:
            raise _FakeFlow.fire_raises
        if _FakeFlow.branch is None:
            raise NotFoundError(f"no '{branch}' transition")
        return SimpleNamespace(transition=SimpleNamespace(id=_FakeFlow.branch.id))

    async def after_commit(self, staged):
        _FakeFlow.after.append(True)
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
    _FakeFlow.notes = []
    _FakeFlow.vote_ids = []
    _FakeFlow.after = []
    monkeypatch.setattr(voting_service, "FlowService", _FakeFlow)
    return _FakeFlow


def _audits(db: Any) -> list[Any]:
    return [a for a in db.added if type(a).__name__ == "AuditEntry"]


async def test_close_fires_matching_branch(_patch_flow: type[_FakeFlow]) -> None:
    """The close fires the branch of the result and commits once.

    The branch runs in a SAVEPOINT, and ``after_commit`` runs after the commit. The
    status event of the branch names the vote, for the timeline link. The vote_close
    entry holds the result and the counts, never a voter.
    """
    branch_t = TransitionOut(
        id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={}
    )
    _patch_flow.branch = branch_t
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes", "yes", "no"))
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.result == "passed"
    assert out.tally.result == "passed"
    assert out.fired_transition_id == branch_t.id
    assert out.new_state_id == _patch_flow.new_state
    assert out.branch_fired is True
    assert out.application_id == vote.application_id
    assert out.closed_at == NOW
    assert vote.closed_at == NOW
    assert vote.result_branch_transition_id == branch_t.id
    assert _patch_flow.branch_calls == ["pass"]
    assert _patch_flow.notes == ["vote:passed"]
    assert _patch_flow.vote_ids == [vote.id]
    assert db.savepoints == 1
    assert db.savepoint_rollbacks == 0
    assert db.committed == 1
    assert _patch_flow.after == [True]
    entries = _audits(db)
    assert [e.action for e in entries] == ["vote_close"]
    assert entries[0].data["result"] == "passed"
    assert entries[0].data["counts"] == {"yes": 3, "no": 1, "abstain": 0}
    assert entries[0].data["quorumMet"] is True


async def test_close_without_now_stamps_the_current_time(
    _patch_flow: type[_FakeFlow],
) -> None:
    _patch_flow.branch = TransitionOut(id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={})
    vote = _vote()
    db = fake_session(result(vote), result("yes"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.closed_at is not None
    assert vote.closed_at == out.closed_at


async def test_close_prefers_global_flow_branch(_patch_flow: type[_FakeFlow]) -> None:
    """Fire the `pass` branch directly from a `vote` state.

    The close path never uses the guard-based `available_transitions` path.

    The guard path stays unused.
    """
    branch_t = TransitionOut(id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={})
    _patch_flow.branch = branch_t
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes", "yes", "no"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.result == "passed"
    assert out.fired_transition_id == branch_t.id
    assert _patch_flow.branch_calls == ["pass"]
    assert _patch_flow.calls == []


async def test_close_application_vote_without_branch_closes_and_audits(
    _patch_flow: type[_FakeFlow],
) -> None:
    """A missing branch transition does not block the close.

    The vote closes, the audit log gets ``vote_branch_blocked`` with the reason
    ``no_branch``, and ``branchFired`` is False. A person moves the application.

    The vote has an application, and the state has no ``fail`` branch.
    """
    vote = _vote()
    db = fake_session(result(vote), result("no", "no", "yes"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.result == "rejected"
    assert out.branch_fired is False
    assert out.fired_transition_id is None
    assert out.new_state_id is None
    assert vote.status == "closed"
    assert vote.closed_at is not None
    assert db.committed == 1
    assert db.savepoint_rollbacks == 1
    assert _patch_flow.after == []
    entries = _audits(db)
    assert [e.action for e in entries] == ["vote_close", "vote_branch_blocked"]
    assert entries[1].data["branch"] == "fail"
    assert entries[1].data["reason"] == "no_branch"
    assert entries[1].target_id == str(vote.id)


async def test_close_generic_vote_without_application_just_closes(
    _patch_flow: type[_FakeFlow],
) -> None:
    """A generic vote without an application fires NO branch.

    The vote only holds the result for the protocol. The close commits itself.

    No branch was due, so nothing is blocked.
    """
    _patch_flow.available = []
    vote = _vote(application_id=None)
    db = fake_session(result(vote), result("no", "no", "yes"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.result == "rejected"
    assert out.fired_transition_id is None
    assert out.new_state_id is None
    assert out.branch_fired is False
    assert db.committed == 1
    assert db.savepoints == 0
    assert [e.action for e in _audits(db)] == ["vote_close"]


async def test_close_guard_failure_keeps_the_vote_closed(
    _patch_flow: type[_FakeFlow],
) -> None:
    """A guard failure rolls back only the SAVEPOINT.

    The vote stays closed, the close commits, and the audit log records the reason.
    There is no 409, so the cron never retries the vote.
    """
    _patch_flow.branch = TransitionOut(
        id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={}
    )
    _patch_flow.fire_raises = ConflictError("guard", code="guard_failed")
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.result == "passed"
    assert out.branch_fired is False
    assert out.fired_transition_id is None
    assert vote.status == "closed"
    assert vote.result_branch_transition_id is None
    assert db.committed == 1
    assert db.savepoint_rollbacks == 1
    blocked = _audits(db)[-1]
    assert blocked.action == "vote_branch_blocked"
    assert blocked.data == {
        "applicationId": str(vote.application_id),
        "meetingId": None,
        "eligibleGroup": str(GID),
        "branch": "pass",
        "reason": "guard_failed",
    }


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
    """Return 409 when the quorum fails, instead of a silent "rejected".

    The vote stays open. The caller collects more ballots or cancels the vote.

    2 of 10 ballots miss the quorum.
    """
    vote = _vote(
        config=_config(quorum={"type": "percent", "value": 50}), eligible_count=10
    )
    db = fake_session(result(vote), result("yes", "no"))
    with pytest.raises(ConflictError):
        await VotingService(db).close(vote.id, _voter())
    assert db.committed == 0
    assert vote.status == "open"


async def test_close_expired_unmet_quorum_fires_fail_branch(
    _patch_flow: type[_FakeFlow],
) -> None:
    """Close a timed vote for good when the window expired and the quorum failed.

    The cron passes `now`. The service fires the `fail` branch and closes the vote,
    so the vote never stays stuck.

    2 of 10 ballots miss the quorum.
    """
    branch_t = TransitionOut(id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={})
    _patch_flow.branch = branch_t
    vote = _vote(
        config=_config(quorum={"type": "percent", "value": 50}),
        eligible_count=10,
        closes_at=NOW - timedelta(minutes=1),
    )
    db = fake_session(result(vote), result("yes", "no"))
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
    out = await VotingService(db).cancel(vote.id, now=NOW, actor="mgr")
    assert vote.status == "cancelled"
    assert out.status == "cancelled"
    assert out.closed_at == NOW
    assert db.committed == 1
    entries = _audits(db)
    assert [e.action for e in entries] == ["vote_cancel"]
    assert entries[0].data["reason"] == "manual"
    assert entries[0].data["previousStatus"] == "open"


async def test_cancel_without_now_stamps_the_current_time() -> None:
    vote = _vote()
    db = fake_session(result(vote), result())
    await VotingService(db).cancel(vote.id)
    assert vote.closed_at is not None


async def test_cancel_for_application_cancels_open_and_drafts() -> None:
    """The open vote and the drafts of the left state go to cancelled.

    The method does not commit. A draft for another state stays.
    """
    app_id, leaving, entering = uuid4(), uuid4(), uuid4()
    running = _vote(application_id=app_id)
    stale = _vote(application_id=app_id, status="draft", opens_state_id=leaving)
    kept = _vote(application_id=app_id, status="draft", opens_state_id=entering)
    later = _vote(application_id=app_id, status="draft", opens_state_id=uuid4())
    db = fake_session(result(running, stale, kept, later))
    out = await VotingService(db).cancel_for_application(
        app_id, now=NOW, actor="mgr", left_state_id=leaving, entered_state_id=entering
    )
    assert out == [running, stale]
    assert running.status == "cancelled" and running.closed_at == NOW
    assert stale.status == "cancelled" and stale.closed_at == NOW
    assert kept.status == "draft" and kept.closed_at is None
    assert later.status == "draft" and later.closed_at is None
    assert db.committed == 0
    entries = _audits(db)
    assert [e.data["previousStatus"] for e in entries] == ["open", "draft"]
    assert {e.data["reason"] for e in entries} == {"state_left"}
    stmt = str(db.statements[0])
    assert "FOR UPDATE" in stmt


async def test_cancel_for_application_without_left_state_keeps_drafts() -> None:
    app_id = uuid4()
    draft = _vote(application_id=app_id, status="draft", opens_state_id=uuid4())
    db = fake_session(result(draft))
    out = await VotingService(db).cancel_for_application(app_id, now=NOW)
    assert out == []
    assert draft.status == "draft"


async def test_cancel_for_application_same_state_keeps_drafts() -> None:
    app_id, state = uuid4(), uuid4()
    draft = _vote(application_id=app_id, status="draft", opens_state_id=state)
    db = fake_session(result(draft))
    out = await VotingService(db).cancel_for_application(
        app_id, now=NOW, left_state_id=state, entered_state_id=state
    )
    assert out == []
    assert draft.status == "draft"


async def test_cancel_for_application_unbound_draft_of_vote_state() -> None:
    """A draft without opens_state_id goes when the app leaves a vote state."""
    app_id = uuid4()
    draft = _vote(application_id=app_id, status="draft", opens_state_id=None)
    db = fake_session(result(draft))
    db.scalar_results = ["vote"]
    out = await VotingService(db).cancel_for_application(
        app_id, now=NOW, left_state_id=uuid4(), entered_state_id=uuid4()
    )
    assert out == [draft]
    assert draft.status == "cancelled"


async def test_cancel_for_application_unbound_draft_of_branch_state() -> None:
    """A normal state with a pass/fail exit counts as a vote state too."""
    app_id = uuid4()
    draft = _vote(application_id=app_id, status="draft", opens_state_id=None)
    db = fake_session(result(draft))
    db.scalar_results = ["normal", uuid4()]
    out = await VotingService(db).cancel_for_application(
        app_id, now=NOW, left_state_id=uuid4(), entered_state_id=uuid4()
    )
    assert out == [draft]


async def test_cancel_for_application_unbound_draft_of_normal_state_stays() -> None:
    """A draft without opens_state_id survives a transition out of a normal state.

    The state kind is read once for all drafts, so "vote" stays unread.
    """
    app_id = uuid4()
    first = _vote(application_id=app_id, status="draft", opens_state_id=None)
    second = _vote(application_id=app_id, status="draft", opens_state_id=None)
    db = fake_session(result(first, second))
    db.scalar_results = ["normal", None, "vote"]
    out = await VotingService(db).cancel_for_application(
        app_id, now=NOW, left_state_id=uuid4(), entered_state_id=uuid4()
    )
    assert out == []
    assert first.status == second.status == "draft"
    assert db.scalar_results == ["vote"]


async def test_cancel_drafts_for_meeting() -> None:
    mid = uuid4()
    first = _vote(meeting_id=mid, status="draft")
    second = _vote(meeting_id=mid, status="draft", application_id=None)
    db = fake_session(result(first, second))
    out = await VotingService(db).cancel_drafts_for_meeting(mid, now=NOW, actor="mgr")
    assert out == [first, second]
    assert first.status == second.status == "cancelled"
    assert first.closed_at == second.closed_at == NOW
    entries = _audits(db)
    assert [e.data["reason"] for e in entries] == ["meeting_closed", "meeting_closed"]
    assert entries[1].data["applicationId"] is None
    assert entries[0].data["meetingId"] == str(mid)
    assert db.committed == 0


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
    """A vote without an application runs no ``_get_application`` query.

    The only scalar is the locked status of the meeting.
    """
    db = fake_session()
    db.scalar_results = ["live"]
    payload = VoteCreateInternal.model_validate(
        {"config": _config(), "eligibleGroup": str(GID), "eligibleCount": 4}
    )
    out = await VotingService(db).create_internal(None, payload, meeting_id=uuid4())
    assert out.status == "draft"
    assert out.application_id is None
    assert out.tally.eligible == 4
    assert db.committed == 1


@pytest.mark.parametrize(
    ("status", "code"), [("planned", "meeting_not_started"), ("closed", "meeting_closed")]
)
async def test_create_in_a_meeting_that_is_not_live_conflicts(status: str, code: str) -> None:
    """A meeting vote needs a live meeting, read under the meeting row lock."""
    db = fake_session()
    db.scalar_results = [status]
    payload = VoteCreateInternal.model_validate(
        {"config": _config(), "eligibleGroup": str(GID), "eligibleCount": 4}
    )
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).create_internal(None, payload, meeting_id=uuid4())
    assert ei.value.code == code
    assert db.added == []


async def test_create_prepared_draft_in_a_planned_meeting() -> None:
    """A prepared question waits as a draft before the meeting starts."""
    db = fake_session()
    db.scalar_results = ["planned"]
    payload = VoteCreateInternal.model_validate(
        {"config": _config(), "eligibleGroup": str(GID), "eligibleCount": 4}
    )
    out = await VotingService(db).create_internal(
        None, payload, meeting_id=uuid4(), planned_ok=True
    )
    assert out.status == "draft"


async def test_create_prepared_draft_in_a_closed_meeting_conflicts() -> None:
    db = fake_session()
    db.scalar_results = ["closed"]
    payload = VoteCreateInternal.model_validate(
        {"config": _config(), "eligibleGroup": str(GID), "eligibleCount": 4}
    )
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).create_internal(
            None, payload, meeting_id=uuid4(), planned_ok=True
        )
    assert ei.value.code == "meeting_closed"


async def test_create_with_a_missing_meeting_or_agenda_item_is_404() -> None:
    """A missing meeting or a missing agenda item gives 404."""
    payload = VoteCreateInternal.model_validate(
        {"config": _config(), "eligibleGroup": str(GID), "eligibleCount": 4}
    )
    db = fake_session()
    with pytest.raises(NotFoundError):
        await VotingService(db).create_internal(None, payload, meeting_id=uuid4())
    db = fake_session()
    db.scalar_results = ["live", None]
    with pytest.raises(NotFoundError, match="agenda item"):
        await VotingService(db).create_internal(
            None, payload, meeting_id=uuid4(), agenda_item_id=uuid4()
        )
    assert db.added == []


async def test_create_on_an_agenda_item_of_the_live_meeting() -> None:
    """The agenda item exists in the live meeting: the draft binds to it."""
    payload = VoteCreateInternal.model_validate(
        {"config": _config(), "eligibleGroup": str(GID), "eligibleCount": 4}
    )
    mid, item = uuid4(), uuid4()
    db = fake_session()
    db.scalar_results = ["live", item]
    out = await VotingService(db).create_internal(
        None, payload, meeting_id=mid, agenda_item_id=item
    )
    assert out.status == "draft"
    [vote] = [o for o in db.added if isinstance(o, Vote)]
    assert vote.meeting_id == mid
    assert vote.agenda_item_id == item
    assert db.committed == 1


@pytest.mark.parametrize("status", ["draft", "cancelled"])
async def test_delete_vote_in_meeting_removes_audits_and_commits(status: str) -> None:
    """Every delete of a meeting vote goes into the audit log."""
    mid, item = uuid4(), uuid4()
    vote = _vote(meeting_id=mid, agenda_item_id=item, status=status)
    db = fake_session(result(vote))
    await VotingService(db).delete(vote.id, meeting_id=mid, actor="mgr")
    assert vote in db.deleted
    assert db.committed == 1
    [entry] = _audits(db)
    assert entry.action == "vote_delete"
    assert entry.actor == "mgr"
    assert entry.data["meetingId"] == str(mid)
    assert entry.data["agendaItemId"] == str(item)
    assert entry.data["status"] == status


@pytest.mark.parametrize("status", ["open", "closed"])
async def test_delete_open_or_closed_vote_in_meeting_conflicts(status: str) -> None:
    """An open or closed vote is part of the record; it also keeps its TOP."""
    mid = uuid4()
    vote = _vote(meeting_id=mid, agenda_item_id=uuid4(), status=status)
    db = fake_session(result(vote))
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).delete(vote.id, meeting_id=mid, actor="mgr")
    assert ei.value.code == "vote_not_deletable"
    assert db.deleted == []
    assert db.committed == 0
    assert _audits(db) == []


async def test_delete_vote_from_other_meeting_404() -> None:
    vote = _vote(meeting_id=uuid4())
    db = fake_session(result(vote))
    with pytest.raises(NotFoundError, match="not found in this meeting"):
        await VotingService(db).delete(vote.id, meeting_id=uuid4(), actor="mgr")
    assert db.deleted == []
    assert _audits(db) == []


async def test_delete_for_agenda_item_deletes_drafts_and_cancelled() -> None:
    """The agenda-item remove deletes the draft and cancelled votes with audit.

    The caller commits together with the agenda-item remove.
    """
    item = uuid4()
    draft = _vote(meeting_id=uuid4(), agenda_item_id=item, status="draft")
    cancelled = _vote(meeting_id=uuid4(), agenda_item_id=item, status="cancelled")
    db = fake_session(result(draft, cancelled))
    out = await VotingService(db).delete_for_agenda_item(item, actor="mgr", may_delete=True)
    assert out == [draft.id, cancelled.id]
    assert db.deleted == [draft, cancelled]
    assert [e.data["status"] for e in _audits(db)] == ["draft", "cancelled"]
    assert db.committed == 0


async def test_delete_for_agenda_item_without_votes_is_empty() -> None:
    """Without votes the agenda right alone is enough: nothing is deleted."""
    db = fake_session(result())
    out = await VotingService(db).delete_for_agenda_item(uuid4(), actor="mgr", may_delete=False)
    assert out == []
    assert db.deleted == []


async def test_delete_for_agenda_item_needs_the_vote_right() -> None:
    """The agenda right alone does not delete a vote, not even a cancelled one."""
    item = uuid4()
    cancelled = _vote(agenda_item_id=item, status="cancelled")
    db = fake_session(result(cancelled))
    with pytest.raises(ForbiddenError):
        await VotingService(db).delete_for_agenda_item(item, actor="pw", may_delete=False)
    assert db.deleted == []
    assert _audits(db) == []


@pytest.mark.parametrize("blocking", ["open", "closed"])
async def test_delete_for_agenda_item_refuses_open_or_closed_vote(blocking: str) -> None:
    """An open or closed vote is part of the record and blocks the remove."""
    item = uuid4()
    draft = _vote(agenda_item_id=item, status="draft")
    kept = _vote(agenda_item_id=item, status=blocking)
    db = fake_session(result(draft, kept))
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).delete_for_agenda_item(item, actor="mgr", may_delete=True)
    assert ei.value.code == "agenda_item_has_vote"
    assert db.deleted == []
    assert _audits(db) == []


async def test_delete_for_meeting_deletes_every_vote_in_order() -> None:
    """The meeting delete takes every vote along, in any status, without a commit.

    The order is the lock, the protocol references, the secret ballots, the voted
    markers and the ballots, then the status events lose the vote reference. The audit
    holds id references and the status only, never a choice or a voter.
    """
    mid = uuid4()
    votes = [
        _vote(meeting_id=mid, status="draft"),
        _vote(meeting_id=mid, status="cancelled", application_id=None),
        _vote(meeting_id=mid, status="closed", result="passed"),
        _vote(meeting_id=mid, status="closed", config=_config(secret=True)),
    ]
    db = fake_session(result(*votes))
    out = await VotingService(db).delete_for_meeting(mid, actor="mgr")
    assert out == [v.id for v in votes]
    assert db.deleted == votes
    assert db.committed == 0
    tables = [
        getattr(getattr(stmt, "table", None), "name", None) for stmt in db.statements[1:6]
    ]
    assert tables == [
        "protocol_vote_ref",
        "secret_ballot",
        "voted_marker",
        "ballot",
        "status_event",
    ]
    entries = _audits(db)
    assert [e.action for e in entries] == ["vote_delete"] * 4
    assert [e.data["status"] for e in entries] == ["draft", "cancelled", "closed", "closed"]
    assert {e.data["reason"] for e in entries} == {"meeting_deleted"}
    assert entries[1].data["applicationId"] is None
    assert all(set(e.data) == {
        "applicationId", "meetingId", "eligibleGroup", "agendaItemId", "status", "reason"
    } for e in entries)


async def test_delete_for_meeting_without_votes_runs_no_delete() -> None:
    """A meeting without votes runs only the locking select."""
    db = fake_session(result())
    assert await VotingService(db).delete_for_meeting(uuid4(), actor="mgr") == []
    assert len(db.statements) == 1
    assert db.deleted == []
    assert _audits(db) == []


async def test_delete_for_meeting_refuses_an_open_vote() -> None:
    mid = uuid4()
    db = fake_session(result(_vote(meeting_id=mid, status="draft"), _vote(meeting_id=mid)))
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).delete_for_meeting(mid, actor="mgr")
    assert ei.value.code == "open_vote"
    assert len(db.statements) == 1
    assert db.deleted == []
    assert _audits(db) == []


async def test_lock_for_gremium_delete_locks_all_votes_in_one_statement() -> None:
    """The meeting votes and the votes without a meeting, in id order, before any write."""
    gid, mid = uuid4(), uuid4()
    votes = [_vote(meeting_id=mid, status="closed"), _vote(status="cancelled")]
    db = fake_session(result(*votes))
    out = await VotingService(db).lock_for_gremium_delete(gid, [mid])
    assert out == votes
    [lock] = db.statements
    sql = str(lock)
    assert "vote.meeting_id IN" in sql
    assert "vote.eligible_group = " in sql and "vote.meeting_id IS NULL" in sql
    assert "ORDER BY vote.id" in sql and "FOR UPDATE" in sql
    assert db.deleted == []
    assert _audits(db) == []


async def test_lock_for_gremium_delete_refuses_an_open_vote() -> None:
    db = fake_session(result(_vote(status="draft"), _vote()))
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).lock_for_gremium_delete(uuid4(), [])
    assert ei.value.code == "open_vote"
    assert "Gremium" in str(ei.value)
    assert db.deleted == []
    assert _audits(db) == []


async def test_delete_locked_votes_deletes_with_the_reason() -> None:
    """The delete of locked votes writes the reason and deletes the child rows first.

    It takes no lock, because the caller locked the rows.
    """
    votes = [
        _vote(status="closed", result="passed"),
        _vote(status="cancelled", config=_config(secret=True)),
    ]
    db = fake_session()
    out = await VotingService(db).delete_locked_votes(
        votes,  # type: ignore[arg-type]
        actor="admin",
        reason="gremium_deleted",
    )
    assert out == [v.id for v in votes]
    assert db.deleted == votes
    assert db.committed == 0
    assert getattr(getattr(db.statements[0], "table", None), "name", None) == (
        "protocol_vote_ref"
    )
    entries = _audits(db)
    assert [e.action for e in entries] == ["vote_delete"] * 2
    assert {e.data["reason"] for e in entries} == {"gremium_deleted"}


async def test_delete_locked_votes_without_votes_writes_nothing() -> None:
    db = fake_session()
    assert await VotingService(db).delete_locked_votes([], actor="a", reason="r") == []
    assert db.statements == []
    assert _audits(db) == []


async def test_get_meeting_open_reveals_when_all_present_voted() -> None:
    """An open meeting vote reveals the tally when both present members voted."""
    vote = _vote(meeting_id=uuid4())
    db = fake_session(result(vote), result("yes", "yes"))
    db.scalar_results = [2]
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is True
    assert out.tally.counts == {"yes": 2, "no": 0, "abstain": 0}


async def test_get_meeting_open_hidden_until_all_present_voted() -> None:
    """3 present and 2 voted keep the tally hidden."""
    vote = _vote(meeting_id=uuid4())
    db = fake_session(result(vote), result("yes", "yes"))
    db.scalar_results = [3]
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is False
    assert out.tally.counts == {}
    assert out.tally.voted == 2


async def test_get_meeting_open_without_attendance_stays_hidden() -> None:
    """Without present members the tally stays hidden."""
    vote = _vote(meeting_id=uuid4())
    db = fake_session(result(vote), result())
    db.scalar_results = [0]
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is False


def test_open_tally_revealed_rule() -> None:
    """Present must be above 0 AND voted must reach expected."""
    assert open_tally_revealed(present=2, voted=2, expected=2) is True
    assert open_tally_revealed(present=2, voted=3, expected=2) is True
    assert open_tally_revealed(present=2, voted=1, expected=2) is False
    assert open_tally_revealed(present=0, voted=0, expected=0) is False


async def test_get_meeting_open_hidden_until_proxy_voted() -> None:
    """The tally stays hidden while the proxy ballot of an absent delegator is missing.

    2 present members, no admitted guests and 1 vote delegation of an ABSENT delegator
    give expected=3. Only the 2 own ballots arrived.
    """
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(result(vote), result("yes", "yes"))
    db.scalar_results = [2, 0, 1]
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is False
    assert out.tally.counts == {}


async def test_get_meeting_open_reveals_when_proxy_also_voted() -> None:
    """2 present, no guests and 1 proxy give expected=3; voted=3 reveals the tally."""
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(result(vote), result("yes", "yes", "no"))
    db.scalar_results = [2, 0, 1]
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is True
    assert out.tally.counts == {"yes": 2, "no": 1, "abstain": 0}


async def test_absent_delegated_count_no_meeting_is_zero() -> None:
    vote = _vote(meeting_id=None)
    svc = VotingService(fake_session())
    assert await svc._absent_delegated_count(vote) == 0  # pyright: ignore[reportArgumentType]


async def test_absent_delegated_count_non_uuid_group_is_zero() -> None:
    """An eligible_group that is not UUID text, "stupa" for example, runs no delegation query."""
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
    """A COUNT of None becomes 0 through the or-default."""
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session()
    db.scalar_results = [None]
    assert await VotingService(db)._absent_delegated_count(vote) == 0  # pyright: ignore[reportArgumentType]


async def test_assert_can_read_meeting_vote_goes_through_the_meeting_guard() -> None:
    """Even an admin reads a meeting-bound vote through the meeting guard.

    An early return on a raw `principal.roles` read would skip `Principal.has`, which is
    where the OAuth scope cap lives, so a narrowly scoped token issued to an admin would
    read as a full admin.
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

    An early return on `"admin" in principal.roles` would let an agent token issued to an
    admin with only the `read` scope manage votes. `Principal.has` applies the cap, and a
    raw role read does not.
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
    """The scoped read checks access, then returns the tally. The caller holds no ballot."""
    vote = _vote(meeting_id=None)
    db = fake_session(result(vote), result(vote), result("yes"))
    p = Principal(sub="u", permissions={"application.read"})
    out = await VotingService(db).get_scoped(vote.id, p)
    assert out.tally.counts == {"yes": 1, "no": 0, "abstain": 0}
    assert out.my_ballot is not None
    assert out.my_ballot.cast is False
    assert out.my_ballot.choice is None
    assert out.represented_cast is False
    assert out.majority_rule == "simple"
    assert out.quorum is None


async def test_my_ballot_open_vote_returns_the_choice() -> None:
    vote = _vote()
    db = fake_session(result(SimpleNamespace(choice="no")))
    mine = await VotingService(db).my_ballot(vote, "v1", secret=False)  # pyright: ignore[reportArgumentType]
    assert mine.cast is True
    assert mine.choice == "no"


async def test_my_ballot_secret_vote_never_returns_a_choice() -> None:
    """A secret vote never returns the choice, even when the voted marker exists."""
    vote = _vote(config=_config(secret=True))
    db = fake_session()
    db.scalar_results = [uuid4()]
    mine = await VotingService(db).my_ballot(vote, "v1", secret=True)  # pyright: ignore[reportArgumentType]
    assert mine.cast is True
    assert mine.choice is None
    db.scalar_results = [None]
    mine = await VotingService(db).my_ballot(vote, "v1", secret=True)  # pyright: ignore[reportArgumentType]
    assert mine.cast is False


async def test_represented_cast_reads_the_ballot_of_the_delegator() -> None:
    """The represented flag reads the ballot of the delegator of an incoming delegation."""
    vote = _vote(meeting_id=uuid4())
    db = fake_session(
        result((False, True, "delegator-1")),
        result(SimpleNamespace(choice="yes")),
    )
    assert await VotingService(db).represented_cast(vote, "proxy", secret=False) is True  # pyright: ignore[reportArgumentType]


async def test_represented_cast_without_delegation_is_false() -> None:
    """Without a delegation row the represented flag is False."""
    vote = _vote(meeting_id=uuid4())
    db = fake_session(result())
    assert await VotingService(db).represented_cast(vote, "proxy", secret=False) is False  # pyright: ignore[reportArgumentType]


async def test_delete_standalone_draft_ok() -> None:
    from app.modules.audit.models import AuditEntry

    vote = _vote(meeting_id=None, status="draft")
    db = fake_session(result(vote))
    await VotingService(db).delete_standalone(vote.id, actor="mgr")
    assert vote in db.deleted
    assert db.committed == 1
    entries = [o for o in db.added if isinstance(o, AuditEntry)]
    assert [e.action for e in entries] == ["vote_delete"]
    assert entries[0].data["eligibleGroup"] == str(GID)


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
    """A meeting vote gives 409, because the meeting route owns it with its own check."""
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
    """An open ballot blocks the delete at the first count."""
    vote = _vote(meeting_id=None, status="draft")
    db = fake_session(result(vote))
    db.scalar_results = [1, 0, 0]
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).delete_standalone(vote.id, actor="mgr")
    assert ei.value.code == "vote_has_ballots"
    assert db.deleted == []


async def test_delete_standalone_with_secret_marker_409() -> None:
    """A secret vote leaves only the voted_marker as a trace, and that blocks too."""
    vote = _vote(meeting_id=None, status="draft")
    db = fake_session(result(vote))
    db.scalar_results = [0, 0, 2]
    with pytest.raises(ConflictError):
        await VotingService(db).delete_standalone(vote.id, actor="mgr")


async def test_vote_gremium_mismatch_rules() -> None:
    """The vote of the snapshot Gremium matches. Another Gremium, or no snapshot, is a mismatch.

    Without an application row, or outside a vote state, there is nothing to compare.
    """
    svc = VotingService(fake_session())
    assert await svc.vote_gremium_mismatch(_vote(application_id=None)) is False  # type: ignore[arg-type]
    assert await VotingService(fake_session(result())).vote_gremium_mismatch(_vote()) is False  # type: ignore[arg-type]
    db = fake_session(result((GID, "normal")))
    assert await VotingService(db).vote_gremium_mismatch(_vote()) is False  # type: ignore[arg-type]
    db = fake_session(result((GID, "vote")))
    assert await VotingService(db).vote_gremium_mismatch(_vote()) is False  # type: ignore[arg-type]
    db = fake_session(result((uuid4(), "vote")))
    assert await VotingService(db).vote_gremium_mismatch(_vote()) is True  # type: ignore[arg-type]
    db = fake_session(result((None, "vote")))
    assert await VotingService(db).vote_gremium_mismatch(_vote()) is True  # type: ignore[arg-type]


async def test_open_refuses_a_vote_of_another_gremium() -> None:
    vote = _vote(status="draft")
    db = fake_session(result(vote), result((uuid4(), "vote")))
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).open(vote.id, now=NOW)
    assert ei.value.code == "vote_gremium_mismatch"
    assert vote.status == "draft"


async def test_close_blocks_the_branch_of_another_gremium(
    _patch_flow: type[_FakeFlow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A vote of another Gremium closes, but the flow never runs."""
    _patch_flow.branch = TransitionOut(
        id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={}
    )

    async def _mismatch(_self: object, _vote: object) -> bool:
        return True

    monkeypatch.setattr(VotingService, "vote_gremium_mismatch", _mismatch)
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes", "no"))
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.branch_fired is False
    assert _patch_flow.branch_calls == []
    blocked = [a for a in _audits(db) if a.action == "vote_branch_blocked"]
    assert blocked[0].data["reason"] == "vote_gremium_mismatch"
