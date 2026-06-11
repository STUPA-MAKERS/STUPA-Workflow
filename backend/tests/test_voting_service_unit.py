"""TDD: VotingService (T-15) — Lebenszyklus + RBAC + Race-Branches ohne DB.

Die echten DB-Constraints (UNIQUE-Doppelstimme, ON CONFLICT) liegen in der
Integration; hier wird jede Service-Verzweigung über einen Ergebnis-Queue-Fake
deterministisch getroffen (Branch-Abdeckung)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, ClassVar
from uuid import uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.flow.schemas import TransitionOut, TransitionResult
from app.modules.voting import service as voting_service
from app.modules.voting.schemas import VoteCreate
from app.modules.voting.service import VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationProblem,
)
from tests.flow_fakes import fake_session, result

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


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #
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
    """Prozent-Quorum ohne maßgebliche Stimmberechtigten-Zahl → 422 (fail-closed)."""
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


# --------------------------------------------------------------------------- #
# open
# --------------------------------------------------------------------------- #
async def test_open_sets_window_keeps_roster_eligible() -> None:
    # eligible_count stammt aus dem Roster (beim Anlegen gesetzt), NICHT aus
    # eingeloggten Usern → open zählt nichts nach.
    vote = _vote(status="draft", eligible_count=20)
    db = fake_session(result(vote))  # nur _get_vote, kein Count-Query
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


# --------------------------------------------------------------------------- #
# cast — guards
# --------------------------------------------------------------------------- #
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
    # #delegation-rework: ausgehende Stimm-Delegation für DIESE Sitzung
    # (is_delegator=True, delegate_voting=True) → eigene Stimme verboten.
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(result(vote), result((True, True)))
    with pytest.raises(ForbiddenError, match="delegated"):
        await VotingService(db).cast(
            vote.id, _voter(group=str(gid)), "yes", now=NOW
        )
    assert db.committed == 0


async def test_cast_nonvoting_delegation_does_not_block_member() -> None:
    # Eine Nicht-Stimm-Delegation (z. B. reine Sitzungs-Vertretung) blockt das
    # eigene Stimmrecht eines Mitglieds nicht.
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(
        result(vote),
        result((True, False)),  # ausgehende NICHT-Stimm-Delegation
        result(SimpleNamespace(inserted=True)),  # ballot insert
    )
    out = await VotingService(db).cast(vote.id, _voter(group=str(gid)), "yes", now=NOW)
    assert out.status == "cast"
    assert db.committed == 1


async def test_cast_exercising_delegated_vote_is_audited() -> None:
    # Externer Stellvertreter: NICHT in der eligible_group, aber Empfänger einer
    # Stimm-Delegation der Sitzung → stimmberechtigt + DELEGATION_USE-Audit.
    gid = uuid4()
    vote = _vote(meeting_id=uuid4(), eligible_group=str(gid))
    db = fake_session(
        result(vote),
        result((False, True)),  # eingehende Stimm-Delegation → exercised
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        result(SimpleNamespace(inserted=True)),  # ballot insert (allowChange → xmax)
    )
    out = await VotingService(db).cast(
        vote.id, _voter(group="somewhere-else"), "yes", now=NOW
    )
    assert out.status == "cast"
    assert db.committed == 1
    assert any(type(a).__name__ == "AuditEntry" for a in db.added)


async def test_cast_vote_without_meeting_skips_delegation_check() -> None:
    # Votes ohne Sitzung kennen keine Delegation — kein Delegations-Query.
    vote = _vote()  # meeting_id=None
    db = fake_session(result(vote), result(SimpleNamespace(inserted=True)))
    out = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert out.status == "cast"


async def test_cast_unknown_option_422() -> None:
    vote = _vote()
    db = fake_session(result(vote))
    with pytest.raises(ValidationProblem):
        await VotingService(db).cast(vote.id, _voter(), "maybe", now=NOW)


# --------------------------------------------------------------------------- #
# cast — open ballot (allowChange on/off)
# --------------------------------------------------------------------------- #
async def test_cast_open_first_vote() -> None:
    vote = _vote(config=_config(allowChange=False))
    db = fake_session(result(vote), result(SimpleNamespace(id=uuid4())))
    out = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert out.status == "cast"
    assert db.committed == 1


async def test_cast_open_double_no_change_409() -> None:
    vote = _vote(config=_config(allowChange=False))
    db = fake_session(result(vote), result())  # leeres RETURNING → Konflikt
    with pytest.raises(ConflictError, match="Already voted"):
        await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    # ON CONFLICT DO NOTHING schrieb nichts → kein Commit (get_session rollt zurück).
    assert db.committed == 0


async def test_cast_open_allowchange_first_vote_is_cast() -> None:
    # allowChange + Erst-Stimme (INSERT, xmax=0) → "cast", nicht "changed".
    vote = _vote(config=_config(allowChange=True))
    db = fake_session(result(vote), result(SimpleNamespace(inserted=True)))
    out = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert out.status == "cast"
    assert db.committed == 1


async def test_cast_open_change_updates() -> None:
    # allowChange + bestehende Stimme (UPDATE via ON CONFLICT) → "changed".
    vote = _vote(config=_config(allowChange=True))
    db = fake_session(result(vote), result(SimpleNamespace(inserted=False)))
    out = await VotingService(db).cast(vote.id, _voter(), "no", now=NOW)
    assert out.status == "changed"
    assert db.committed == 1


async def test_cast_open_allowchange_empty_returning_is_changed() -> None:
    # Defensiv: leeres RETURNING (kein row) → kein Insert erkannt → "changed".
    vote = _vote(config=_config(allowChange=True))
    db = fake_session(result(vote), result())
    out = await VotingService(db).cast(vote.id, _voter(), "no", now=NOW)
    assert out.status == "changed"


# --------------------------------------------------------------------------- #
# cast — secret ballot
# --------------------------------------------------------------------------- #
async def test_cast_secret_first_vote_writes_anonymous() -> None:
    vote = _vote(config=_config(secret=True))
    db = fake_session(result(vote), result(SimpleNamespace(id=uuid4())))
    out = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert out.status == "cast"
    # secret_ballot ohne Identität hinzugefügt, kein Ballot.
    assert len(db.added) == 1
    assert type(db.added[0]).__name__ == "SecretBallot"
    assert db.committed == 1


async def test_cast_secret_double_409() -> None:
    vote = _vote(config=_config(secret=True))
    db = fake_session(result(vote), result())  # marker existiert → Konflikt
    with pytest.raises(ConflictError, match="Already voted"):
        await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert db.committed == 0


# --------------------------------------------------------------------------- #
# get
# --------------------------------------------------------------------------- #
async def test_get_open_aggregates_tally() -> None:
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes", "no"))
    out = await VotingService(db).get(vote.id)
    assert out.tally.counts == {"yes": 2, "no": 1, "abstain": 0}
    assert out.tally.result is None  # offen → kein Endergebnis


async def test_get_closed_includes_result() -> None:
    vote = _vote(status="closed", result="passed")
    db = fake_session(result(vote), result("yes", "yes", "no"))
    out = await VotingService(db).get(vote.id)
    assert out.result == "passed"
    assert out.tally.result == "passed"


async def test_get_secret_hides_counts_until_close() -> None:
    # Geheim ⇒ keine Choice-Counts vor dem Schließen (nur Teilnahme); #vote-progress.
    vote = _vote(config=_config(secret=True))
    db = fake_session(result(vote), result("yes", "no", "yes"))
    out = await VotingService(db).get(vote.id)
    assert out.secret is True
    assert out.tally.revealed is False
    assert out.tally.counts == {}
    assert out.tally.voted == 3  # Teilnahme bleibt sichtbar


# --------------------------------------------------------------------------- #
# close — count → result → flow.fire(branch)
# --------------------------------------------------------------------------- #
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
    """#28: bei einem ``vote``-State feuert close() den ``pass``-Branch direkt —
    ohne den Guard-basierten ``available_transitions``-Pfad."""
    branch_t = TransitionOut(id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={})
    _patch_flow.branch = branch_t
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes", "yes", "no"))
    out = await VotingService(db).close(vote.id, _voter())
    assert out.result == "passed"
    assert out.fired_transition_id == branch_t.id
    assert _patch_flow.branch_calls == ["pass"]  # passed → pass
    assert _patch_flow.calls == []  # Guard-Pfad NICHT benutzt


async def test_close_application_vote_without_branch_raises_conflict(
    _patch_flow: type[_FakeFlow],
) -> None:
    """Antragsgebundener Vote ohne passenden Branch-Übergang ⇒ fail-closed (409),
    NICHT still schließen — sonst stünde das Ergebnis fest, der Antrag bliebe aber
    ewig im Vor-Vote-State (Vote-Ergebnis und Flow-State driften auseinander)."""
    _patch_flow.available = []  # kein passender Übergang
    vote = _vote()  # application_id gesetzt
    db = fake_session(result(vote), result("no", "no", "yes"))
    with pytest.raises(ConflictError):
        await VotingService(db).close(vote.id, _voter())
    assert db.committed == 0  # kein stiller Teil-Commit


async def test_close_generic_vote_without_application_just_closes(
    _patch_flow: type[_FakeFlow],
) -> None:
    """Generische Beschlussfrage (ohne Antrag) feuert KEINEN Branch — sie hält nur
    das Ergebnis fürs Protokoll und committet den Schluss selbst."""
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
    """`fire`-Fehler beim Schließen ⇒ KEIN Commit → Vote bleibt offen/wiederholbar
    (kein »zu, aber Branch nie gefeuert«). Der Vote-Close ist mit `fire` atomar."""
    branch_t = TransitionOut(
        id=uuid4(), fromStateId=uuid4(), toStateId=uuid4(), label={}
    )
    _patch_flow.branch = branch_t
    _patch_flow.fire_raises = ConflictError("guard", code="guard_failed")
    vote = _vote()
    db = fake_session(result(vote), result("yes", "yes"))
    with pytest.raises(ConflictError):
        await VotingService(db).close(vote.id, _voter())
    # close hat selbst NICHT committet — die Vote-Änderung hängt nur ungespeichert
    # in der Session; get_session rollt bei der Exception zurück.
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
