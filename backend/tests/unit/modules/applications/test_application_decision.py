"""Tests of the decision module (F1): validation, record, revert and reads."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications import decision as mod
from app.modules.applications.decision import (
    CODE_AMOUNT_EXCEEDS,
    CODE_AMOUNT_INVALID,
    CODE_NOT_ALLOWED,
    MAX_CONDITION_LENGTH,
    MAX_CONDITIONS,
    DecisionIn,
    DecisionSwap,
    accepted_state_keys,
    amount_deviates,
    check_approved_amount,
    check_decision_target,
    committed_amount,
    decision_source,
    decisions_by_event,
    record_decision,
    redo_decision_swap,
    revert_decision_for_event,
    valid_decision,
)
from app.modules.applications.models import Application, ApplicationDecision
from app.modules.audit.actions import AuditAction
from app.shared.errors import ValidationProblem

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _Session:
    """A FIFO fake: `execute`, `scalar` and `scalars` answer from their own queues."""

    def __init__(
        self,
        *,
        executes: list[Any] | None = None,
        scalar: list[Any] | None = None,
        scalars: list[list[Any]] | None = None,
        objects: dict[Any, Any] | None = None,
    ) -> None:
        self._executes = list(executes or [])
        self._scalar = list(scalar or [])
        self._scalars = list(scalars or [])
        self._objects = objects or {}
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.flushed = 0

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self._executes.pop(0) if self._executes else None)

    async def scalar(self, stmt: Any) -> Any:
        self.statements.append(stmt)
        return self._scalar.pop(0)

    async def scalars(self, stmt: Any) -> list[Any]:
        self.statements.append(stmt)
        return self._scalars.pop(0)

    async def get(self, model: type, ident: Any) -> Any:
        return self._objects.get((model.__name__, ident))

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _record(_session: Any, **kw: Any) -> None:
        calls.append(kw)

    monkeypatch.setattr(mod, "audit_record", _record)
    return calls


def _s(session: _Session) -> AsyncSession:
    return cast("AsyncSession", session)


def _app(**kw: Any) -> Application:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "amount": Decimal("1000.00"),
        "approved_amount": None,
        "budget_id": uuid.uuid4(),
        "gremium_id": None,
    }
    base.update(kw)
    return cast("Application", SimpleNamespace(**base))


def _row(**kw: Any) -> ApplicationDecision:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "approved_amount": Decimal("800.00"),
        "conditions": ["A"],
        "vote_id": None,
        "status_event_id": None,
        "decided_at": NOW,
        "superseded_at": None,
    }
    base.update(kw)
    return cast("ApplicationDecision", SimpleNamespace(**base))


# --- DecisionIn -------------------------------------------------------------------


def test_decision_in_trims_conditions_and_reads_alias() -> None:
    d = DecisionIn.model_validate({"approvedAmount": "800.5", "conditions": ["  A  "]})
    assert d.approved_amount == Decimal("800.5")
    assert d.conditions == ["A"]
    assert d.to_json() == {"approvedAmount": "800.5", "conditions": ["A"]}
    assert DecisionIn().to_json() == {"approvedAmount": None, "conditions": []}


@pytest.mark.parametrize(
    "conditions",
    [
        ["x"] * (MAX_CONDITIONS + 1),
        ["   "],
        ["x" * (MAX_CONDITION_LENGTH + 1)],
    ],
)
def test_decision_in_refuses_bad_conditions(conditions: list[str]) -> None:
    with pytest.raises(ValidationError):
        DecisionIn.model_validate({"conditions": conditions})


def test_decision_in_refuses_extra_and_nan() -> None:
    with pytest.raises(ValidationError):
        DecisionIn.model_validate({"other": 1})
    with pytest.raises(ValidationError):
        DecisionIn.model_validate({"approvedAmount": "NaN"})


def test_from_stored_tolerates_bad_values() -> None:
    assert DecisionIn.from_stored(None) is None
    assert DecisionIn.from_stored({"conditions": "x"}) is None
    stored = DecisionIn.from_stored({"approvedAmount": "5", "conditions": []})
    assert stored is not None
    assert stored.approved_amount == Decimal("5")


# --- pure amount rules --------------------------------------------------------------


def test_check_approved_amount_accepts_none_and_equal() -> None:
    check_approved_amount(None, None)
    check_approved_amount(Decimal("10"), Decimal("10"))
    check_approved_amount(Decimal("10"), Decimal("0.01"))


@pytest.mark.parametrize(
    ("requested", "approved"),
    [
        (Decimal("10"), Decimal("0")),
        (Decimal("10"), Decimal("-1")),
        (Decimal("10"), Decimal("1.001")),
        (Decimal("1e12"), Decimal("1e11")),
        (None, Decimal("5")),
    ],
)
def test_check_approved_amount_invalid(requested: Decimal | None, approved: Decimal) -> None:
    with pytest.raises(ValidationProblem) as exc:
        check_approved_amount(requested, approved)
    assert exc.value.code == CODE_AMOUNT_INVALID


def test_check_approved_amount_exceeds() -> None:
    with pytest.raises(ValidationProblem) as exc:
        check_approved_amount(Decimal("10"), Decimal("10.01"))
    assert exc.value.code == CODE_AMOUNT_EXCEEDS


def test_amount_deviates_and_committed_amount() -> None:
    assert amount_deviates(Decimal("10"), None) is False
    assert amount_deviates(Decimal("10"), Decimal("10")) is False
    assert amount_deviates(Decimal("10"), Decimal("8")) is True
    assert committed_amount(Decimal("10"), None) == Decimal("10")
    assert committed_amount(Decimal("10"), Decimal("8")) == Decimal("8")


# --- accepted states --------------------------------------------------------------


async def test_accepted_state_keys_without_budget() -> None:
    assert await accepted_state_keys(_s(_Session()), None) == frozenset()


async def test_accepted_state_keys_filters_non_strings() -> None:
    session = _Session(scalar=[["approved", 3, "paid"]])
    keys = await accepted_state_keys(_s(session), uuid.uuid4())
    assert keys == frozenset({"approved", "paid"})


async def test_accepted_state_keys_with_no_top_budget() -> None:
    session = _Session(scalar=[None])
    assert await accepted_state_keys(_s(session), uuid.uuid4()) == frozenset()


async def test_check_decision_target_admits_an_accepted_state() -> None:
    session = _Session(scalar=[["approved"]])
    await check_decision_target(_s(session), _app(), "approved")


@pytest.mark.parametrize("target", [None, "rejected"])
async def test_check_decision_target_refuses(target: str | None) -> None:
    session = _Session(scalar=[["approved"]])
    with pytest.raises(ValidationProblem) as exc:
        await check_decision_target(_s(session), _app(), target)
    assert exc.value.code == CODE_NOT_ALLOWED


# --- record ---------------------------------------------------------------------------


async def test_record_decision_supersedes_adds_and_audits(
    audits: list[dict[str, Any]],
) -> None:
    session = _Session()
    app = _app(approved_amount=Decimal("900.00"))
    vote_id, event_id = uuid.uuid4(), uuid.uuid4()
    row = await record_decision(
        _s(session),
        app,
        DecisionIn(approvedAmount=Decimal("800.00"), conditions=["A", "B"]),
        actor="sub-1",
        decided_by=None,
        old_approved=Decimal("900.00"),
        vote_id=vote_id,
        status_event_id=event_id,
        now=NOW,
    )
    assert len(session.statements) == 2  # the row lock and the supersede UPDATE
    assert session.added == [row]
    assert row.decided_at == NOW
    assert row.conditions == ["A", "B"]
    assert app.approved_amount == Decimal("800.00")
    assert session.flushed == 1
    (call,) = audits
    assert call["action"] == AuditAction.APPLICATION_DECISION
    assert call["data"] == {
        "applicationId": str(app.id),
        "decisionId": str(row.id),
        "requestedAmount": "1000.00",
        "approvedAmountOld": "900.00",
        "approvedAmountNew": "800.00",
        "conditionCount": 2,
        "voteId": str(vote_id),
        "statusEventId": str(event_id),
    }


async def test_record_decision_as_requested_without_links(
    audits: list[dict[str, Any]],
) -> None:
    session = _Session()
    app = _app(amount=None)
    row = await record_decision(
        _s(session), app, DecisionIn(), actor=None, decided_by="sub-1", old_approved=None
    )
    assert row.decided_by == "sub-1"
    assert row.decided_at is not None
    assert app.approved_amount is None
    data = audits[0]["data"]
    assert data["requestedAmount"] is None
    assert data["approvedAmountNew"] is None
    assert data["voteId"] is None
    assert data["statusEventId"] is None


# --- revert ---------------------------------------------------------------------------


async def test_revert_without_event_does_nothing(audits: list[dict[str, Any]]) -> None:
    session = _Session()
    assert await revert_decision_for_event(_s(session), _app(), None, actor=None) is None
    assert session.statements == []
    assert audits == []


async def test_revert_without_valid_decision_does_nothing(
    audits: list[dict[str, Any]],
) -> None:
    session = _Session(executes=[None, None])
    out = await revert_decision_for_event(_s(session), _app(), uuid.uuid4(), actor=None)
    assert out is None
    assert audits == []
    # The first statement locks the application row.
    assert "FOR UPDATE" in str(session.statements[0])


async def test_revert_restores_the_previous_decision(audits: list[dict[str, Any]]) -> None:
    undone = _row(approved_amount=Decimal("500.00"))
    previous = _row(
        approved_amount=Decimal("700.00"), conditions=["X", "Y"], superseded_at=NOW
    )
    session = _Session(executes=[None, undone, previous])
    app = _app(approved_amount=Decimal("500.00"))
    event_id = uuid.uuid4()
    later = datetime(2026, 6, 1, tzinfo=UTC)
    out = await revert_decision_for_event(
        _s(session), app, event_id, actor="admin", now=later
    )
    assert out == DecisionSwap(undone_id=undone.id, restored_id=previous.id)
    assert undone.superseded_at == later
    assert previous.superseded_at is None
    assert app.approved_amount == Decimal("700.00")
    data = audits[0]["data"]
    assert data["restoredDecisionId"] == str(previous.id)
    assert data["approvedAmountOld"] == "500.00"
    assert data["approvedAmountNew"] == "700.00"
    assert data["conditionCount"] == 2
    assert data["statusEventId"] == str(event_id)
    assert data["reverted"] is True


async def test_revert_of_the_first_decision_clears_the_amount(
    audits: list[dict[str, Any]],
) -> None:
    undone = _row()
    session = _Session(executes=[None, undone, None])
    app = _app(approved_amount=Decimal("800.00"))
    out = await revert_decision_for_event(_s(session), app, uuid.uuid4(), actor=None)
    assert out == DecisionSwap(undone_id=undone.id, restored_id=None)
    assert undone.superseded_at is not None
    assert app.approved_amount is None
    data = audits[0]["data"]
    assert data["restoredDecisionId"] is None
    assert data["conditionCount"] == 0
    assert data["approvedAmountNew"] is None


# --- redo (revert of a revert) --------------------------------------------------------


async def test_redo_makes_the_undone_decision_valid_again(
    audits: list[dict[str, Any]],
) -> None:
    app = _app(approved_amount=None)
    undone = _row(application_id=app.id, approved_amount=Decimal("500.00"), superseded_at=NOW)
    # The revert undid `undone` and restored nothing; no decision is valid now.
    session = _Session(executes=[None, None], objects={("ApplicationDecision", undone.id): undone})
    later = datetime(2026, 6, 1, tzinfo=UTC)
    out = await redo_decision_swap(
        _s(session),
        app,
        DecisionSwap(undone_id=undone.id, restored_id=None),
        actor="admin",
        now=later,
    )
    assert out == DecisionSwap(undone_id=None, restored_id=undone.id)
    assert undone.superseded_at is None
    assert app.approved_amount == Decimal("500.00")
    data = audits[0]["data"]
    assert data["restoredDecisionId"] == str(undone.id)
    assert data["decisionId"] is None
    assert data["approvedAmountNew"] == "500.00"


async def test_redo_supersedes_the_restored_decision(audits: list[dict[str, Any]]) -> None:
    app = _app(approved_amount=Decimal("700.00"))
    restored = _row(application_id=app.id, approved_amount=Decimal("700.00"))
    undone = _row(application_id=app.id, approved_amount=Decimal("500.00"), superseded_at=NOW)
    session = _Session(
        executes=[None, restored], objects={("ApplicationDecision", undone.id): undone}
    )
    later = datetime(2026, 6, 1, tzinfo=UTC)
    out = await redo_decision_swap(
        _s(session),
        app,
        DecisionSwap(undone_id=undone.id, restored_id=restored.id),
        actor=None,
        now=later,
    )
    assert out == DecisionSwap(undone_id=restored.id, restored_id=undone.id)
    assert restored.superseded_at == later
    assert undone.superseded_at is None
    assert app.approved_amount == Decimal("500.00")
    assert len(audits) == 1


async def test_redo_skips_when_a_newer_decision_is_valid(
    audits: list[dict[str, Any]],
) -> None:
    app = _app()
    newer = _row(application_id=app.id)
    session = _Session(executes=[None, newer])
    out = await redo_decision_swap(
        _s(session), app, DecisionSwap(undone_id=uuid.uuid4(), restored_id=None), actor=None
    )
    assert out is None
    assert newer.superseded_at is None
    assert audits == []


@pytest.mark.parametrize("foreign", [True, False])
async def test_redo_skips_a_missing_or_foreign_decision(
    audits: list[dict[str, Any]], foreign: bool
) -> None:
    app = _app()
    other = _row(application_id=uuid.uuid4(), superseded_at=NOW)
    objects = {("ApplicationDecision", other.id): other} if foreign else {}
    session = _Session(executes=[None, None], objects=objects)
    out = await redo_decision_swap(
        _s(session), app, DecisionSwap(undone_id=other.id, restored_id=None), actor=None
    )
    assert out is None
    assert audits == []


async def test_redo_without_any_decision_ids_writes_nothing_valid(
    audits: list[dict[str, Any]],
) -> None:
    # A swap of (None, None) cannot occur from a revert, but stays harmless.
    app = _app(approved_amount=None)
    session = _Session(executes=[None, None])
    out = await redo_decision_swap(
        _s(session), app, DecisionSwap(undone_id=None, restored_id=None), actor=None
    )
    assert out == DecisionSwap(undone_id=None, restored_id=None)
    assert app.approved_amount is None


async def test_record_decision_locks_the_application_first(
    audits: list[dict[str, Any]],
) -> None:
    session = _Session()
    await record_decision(
        _s(session), _app(), DecisionIn(), actor=None, decided_by=None, old_approved=None
    )
    assert "FOR UPDATE" in str(session.statements[0])
    assert "UPDATE application_decision" in str(session.statements[1])


# --- reads ----------------------------------------------------------------------------


async def test_valid_decision_returns_the_row() -> None:
    row = _row()
    assert await valid_decision(_s(_Session(executes=[row])), uuid.uuid4()) is row


async def test_decisions_by_event_skips_rows_without_event() -> None:
    event_id = uuid.uuid4()
    linked = _row(status_event_id=event_id)
    session = _Session(scalars=[[linked, _row()]])
    assert await decisions_by_event(_s(session), uuid.uuid4()) == {event_id: linked}


def _vote(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "meeting_id": None,
        "agenda_item_id": None,
        "eligible_group": "not-a-uuid",
    }
    base.update(kw)
    return SimpleNamespace(**base)


async def test_source_of_a_manual_decision_names_the_app_gremium() -> None:
    gremium_id = uuid.uuid4()
    session = _Session(scalar=["StuPa"])
    out = await decision_source(_s(session), _app(gremium_id=gremium_id), _row())
    assert out == mod.DecisionSource(gremium_name="StuPa")


async def test_source_without_any_gremium() -> None:
    out = await decision_source(_s(_Session()), _app(), _row())
    assert out == mod.DecisionSource()


async def test_source_of_a_meeting_vote_with_agenda_number() -> None:
    meeting_id, item_id, gremium_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    vote = _vote(meeting_id=meeting_id, agenda_item_id=item_id)
    meeting = SimpleNamespace(gremium_id=gremium_id, title="Sitzung 3")
    session = _Session(
        scalar=[4, "AStA"],
        objects={("Vote", vote.id): vote, ("Meeting", meeting_id): meeting},
    )
    out = await decision_source(_s(session), _app(), _row(vote_id=vote.id))
    assert out == mod.DecisionSource(
        gremium_name="AStA", meeting_title="Sitzung 3", agenda_position=4
    )


async def test_source_of_a_meeting_vote_without_agenda_rank() -> None:
    meeting_id, gremium_id = uuid.uuid4(), uuid.uuid4()
    vote = _vote(meeting_id=meeting_id, agenda_item_id=uuid.uuid4())
    meeting = SimpleNamespace(gremium_id=gremium_id, title="S")
    session = _Session(
        scalar=[None, "AStA"],
        objects={("Vote", vote.id): vote, ("Meeting", meeting_id): meeting},
    )
    out = await decision_source(_s(session), _app(), _row(vote_id=vote.id))
    assert out.agenda_position is None


async def test_source_of_a_vote_without_meeting_reads_eligible_group() -> None:
    gremium_id = uuid.uuid4()
    vote = _vote(eligible_group=str(gremium_id))
    session = _Session(scalar=["FSR"], objects={("Vote", vote.id): vote})
    out = await decision_source(_s(session), _app(), _row(vote_id=vote.id))
    assert out == mod.DecisionSource(gremium_name="FSR")


async def test_source_of_a_vote_with_a_deleted_meeting_and_bad_group() -> None:
    vote = _vote(meeting_id=uuid.uuid4(), agenda_item_id=None, eligible_group="all")
    session = _Session(objects={("Vote", vote.id): vote})
    out = await decision_source(
        _s(session), _app(gremium_id=uuid.uuid4()), _row(vote_id=vote.id)
    )
    assert out == mod.DecisionSource()


async def test_source_of_a_deleted_vote_falls_back_to_the_app() -> None:
    session = _Session(scalar=["StuPa"])
    out = await decision_source(
        _s(session), _app(gremium_id=uuid.uuid4()), _row(vote_id=uuid.uuid4())
    )
    assert out.gremium_name == "StuPa"
