"""Integration: decisions outside the platform, approved amounts and forced reasons.

Real Postgres. The tests cover specs 001600-001603 (a decision made outside the
platform fires the branch, cancels the open votes and shows in the timeline), 001610
(an approval names its amount), 001613 (the backfill of the migration), 001620-001622
(a later change of the approved amount) and 001650-001653 (the reason of a forced
status and the report).
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.service.forms import FormVersionWriter
from app.modules.application_types.models import ApplicationType
from app.modules.applications.amend import AmendIn, amend_approved_amount
from app.modules.applications.amend_mail import mail_facts
from app.modules.applications.decision import DecisionIn
from app.modules.applications.models import Application, ApplicationDecision, StatusEvent
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.flow.forced_report import forced_events, forced_report
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.flow.outside_decision import OutsideDecisionIn, record_outside_decision
from app.modules.flow.service import FlowService
from app.modules.forms.schemas import FormVersionCreate
from app.modules.gremien.models import Gremium
from app.modules.voting.models import Vote
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError, ValidationProblem

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "migrations"
    / "versions"
    / "c5e19a7d3b42_decisions_outside_and_amend.py"
)


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


def _clerk() -> Principal:
    return Principal(
        sub="clerk-1",
        roles=["finanzreferent"],
        permissions={
            "application.record_decision",
            "application.amend_decision",
            "application.force_status",
            "application.read_all",
        },
    )


class _World:
    def __init__(self, gremium: Gremium, app_type: ApplicationType, states: dict[str, State]):
        self.gremium = gremium
        self.app_type = app_type
        self.states = states


async def _seed(session: AsyncSession) -> _World:
    """Create a Gremium, a type with a form and a flow with a vote state.

    The flow: draft → vote (pass → approved, fail → rejected), draft → approved by
    hand, and a second vote state `stuck` without exits.
    """
    gremium = Gremium(name="Gremium der Kostenstelle", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{uuid.uuid4()}", name_i18n={}, has_budget=False
    )
    session.add(app_type)
    await session.commit()
    await FormVersionWriter(session).create_form_version(
        app_type.id,
        FormVersionCreate(
            fields=[FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True)],
            activate=True,
        ),
        "tester",
    )
    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    vote_config = {"gremiumId": str(gremium.id)}

    def _state(key: str, **kw: object) -> State:
        return State(
            flow_version_id=flow.id, key=key, label_i18n={"de": key}, edit_allowed=False, **kw
        )

    states = {
        "draft": _state("draft", is_initial=True),
        "vote": _state("vote", kind="vote", config=vote_config),
        "stuck": _state("stuck", kind="vote", config=vote_config),
        "approved": _state("approved", is_approved=True),
        "approved2": _state("approved2", is_approved=True),
        "rejected": _state("rejected", is_denied=True),
    }
    session.add_all(list(states.values()))
    await session.flush()

    def _move(a: str, b: str, order: int, branch: str | None = None) -> Transition:
        return Transition(
            flow_version_id=flow.id,
            from_state_id=states[a].id,
            to_state_id=states[b].id,
            label_i18n={"de": f"{a}→{b}"},
            order=order,
            branch=branch,
        )

    session.add_all(
        [
            _move("draft", "vote", 0),
            _move("draft", "approved", 1),
            _move("approved", "approved2", 0),
            _move("vote", "approved", 0, "pass"),
            _move("vote", "rejected", 1, "fail"),
        ]
    )
    await session.commit()
    return _World(gremium, app_type, states)


async def _app(
    session: AsyncSession, world: _World, state: str, amount: str = "100.00"
) -> Application:
    app, _ = await ApplicationsService(session).create(
        ApplicationCreate.model_validate(
            {
                "typeId": str(world.app_type.id),
                "data": {"title": "Exkursion"},
                "applicantEmail": "a@example.org",
            }
        )
    )
    await session.execute(
        update(Application)
        .where(Application.id == app.id)
        .values(
            current_state_id=world.states[state].id,
            amount=Decimal(amount),
            email_confirmed_at=datetime.now(UTC),
            vote_gremium_id=world.gremium.id if state in {"vote", "stuck"} else None,
        )
    )
    await session.commit()
    await session.refresh(app)
    return app


def _payload(world: _World, **kw: object) -> OutsideDecisionIn:
    return OutsideDecisionIn.model_validate(
        {
            "result": "passed",
            "meetingDate": date.today().isoformat(),
            "gremiumId": str(world.gremium.id),
            **kw,
        }
    )


async def _record(session: AsyncSession, app_id: uuid.UUID, payload: OutsideDecisionIn) -> None:
    flow = FlowService(session)
    staged = await record_outside_decision(flow, app_id, payload, _clerk())
    await session.commit()
    await flow.after_commit(staged)


async def test_outside_pass_approves_cancels_votes_and_audits(session: AsyncSession) -> None:
    """§ 001600, 001601: the pass branch fires, the vote is cancelled, the audit marks it."""
    world = await _seed(session)
    app = await _app(session, world, "vote")
    vote = Vote(application_id=app.id, eligible_group="grp", config={}, status="open")
    session.add(vote)
    await session.commit()

    await _record(
        session,
        app.id,
        _payload(world, yes=7, no=1, abstain=2, decision={"approvedAmount": "90.00"}),
    )

    await session.refresh(app)
    await session.refresh(vote)
    assert app.current_state_id == world.states["approved"].id
    assert app.approved_amount == Decimal("90.00")
    assert vote.status == "cancelled"
    event = (
        await session.execute(
            select(StatusEvent).where(
                StatusEvent.application_id == app.id,
                StatusEvent.to_state_id == world.states["approved"].id,
            )
        )
    ).scalar_one()
    assert event.note == "outside:passed"
    assert event.outside_decision is not None
    assert event.outside_decision["yes"] == 7
    audit = (
        (
            await session.execute(
                select(AuditEntry).where(
                    AuditEntry.action == "status_change", AuditEntry.target_id == str(app.id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert [a.data.get("outsideDecision") for a in audit].count(True) == 1

    timeline = await ApplicationsService(session).timeline(app.id)
    outside = next(e for e in timeline if e.outside_decision is not None)
    assert outside.outside_decision is not None
    assert outside.outside_decision.gremium_name == "Gremium der Kostenstelle"
    assert outside.outside_decision.result == "passed"
    seen = await ApplicationsService(session).timeline(app.id, applicant_view=True)
    shown = next(e.outside_decision for e in seen if e.outside_decision is not None)
    assert shown.meeting_id is None


async def test_outside_fail_rejects_without_a_decision(session: AsyncSession) -> None:
    world = await _seed(session)
    app = await _app(session, world, "vote")
    await _record(session, app.id, _payload(world, result="failed"))
    await session.refresh(app)
    assert app.current_state_id == world.states["rejected"].id
    assert app.approved_amount is None


async def test_outside_pass_into_an_approved_state_needs_the_amount(
    session: AsyncSession,
) -> None:
    """§ 001610: the pass into an approved state names the amount."""
    world = await _seed(session)
    app = await _app(session, world, "vote")
    with pytest.raises(ValidationProblem) as err:
        await record_outside_decision(FlowService(session), app.id, _payload(world), _clerk())
    assert err.value.code == "approved_amount_required"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"meetingDate": (date.today() + timedelta(days=2)).isoformat()}, "decision_date_invalid"),
        ({"gremiumId": str(uuid.uuid4())}, "gremium_unknown"),
        ({"meetingId": str(uuid.uuid4())}, "meeting_unknown"),
    ],
)
async def test_outside_refuses_bad_input(
    session: AsyncSession, change: dict[str, str], code: str
) -> None:
    world = await _seed(session)
    app = await _app(session, world, "vote")
    with pytest.raises(ValidationProblem) as err:
        await record_outside_decision(
            FlowService(session), app.id, _payload(world, **change), _clerk()
        )
    assert err.value.code == code


@pytest.mark.parametrize(
    ("state", "code"), [("draft", "not_in_vote_state"), ("stuck", "no_branch")]
)
async def test_outside_needs_a_vote_state_with_the_branch(
    session: AsyncSession, state: str, code: str
) -> None:
    world = await _seed(session)
    app = await _app(session, world, state)
    with pytest.raises(ConflictError) as err:
        await record_outside_decision(FlowService(session), app.id, _payload(world), _clerk())
    assert err.value.code == code


async def test_manual_approval_needs_the_amount_once(session: AsyncSession) -> None:
    """§ 001610: draft → approved asks for the amount, approved → approved2 does not."""
    world = await _seed(session)
    app = await _app(session, world, "draft")
    flow = FlowService(session)
    principal = Principal(sub="m", roles=[], permissions={"application.transition"})
    to_approved = await session.scalar(
        select(Transition.id).where(
            Transition.to_state_id == world.states["approved"].id,
            Transition.from_state_id == world.states["draft"].id,
        )
    )
    assert to_approved is not None
    offered = {t.id: t for t in await flow.available_transitions(app.id, principal)}
    assert offered[to_approved].requires_amount is True
    with pytest.raises(ValidationProblem) as err:
        await flow.fire(app.id, to_approved, principal)
    assert err.value.code == "approved_amount_required"
    await session.rollback()
    await flow.fire(
        app.id, to_approved, principal, decision=DecisionIn(approvedAmount=Decimal("100.00"))
    )
    onward = await flow.available_transitions(app.id, principal)
    assert [t.requires_amount for t in onward] == [False]


async def test_forced_approval_needs_the_amount(session: AsyncSession) -> None:
    """§ 001653: a forced move into an approved state names the approved amount."""
    world = await _seed(session)
    app = await _app(session, world, "draft")
    flow = FlowService(session)
    approved = world.states["approved"].id
    with pytest.raises(ValidationProblem) as err:
        await flow.force_status(app.id, approved, _clerk(), reason="outside_decision")
    assert err.value.code == "approved_amount_required"
    await session.rollback()
    await flow.force_status(
        app.id,
        approved,
        _clerk(),
        reason="outside_decision",
        decision=DecisionIn(approvedAmount=Decimal("80.00")),
    )
    await session.refresh(app)
    assert app.approved_amount == Decimal("80.00")
    row = await session.scalar(
        select(ApplicationDecision).where(ApplicationDecision.application_id == app.id)
    )
    assert row is not None
    assert row.status_event_id is not None


async def test_forced_move_elsewhere_drops_the_decision(session: AsyncSession) -> None:
    """§ 001653: a target that is not approved ignores the decision."""
    world = await _seed(session)
    app = await _app(session, world, "draft")
    await FlowService(session).force_status(
        app.id,
        world.states["rejected"].id,
        _clerk(),
        reason="applicant_error",
        decision=DecisionIn(approvedAmount=Decimal("80.00")),
    )
    await session.refresh(app)
    assert app.approved_amount is None


async def test_amend_writes_a_new_decision_and_keeps_the_state(session: AsyncSession) -> None:
    """§ 001620-001622: a new decision, the conditions kept, a higher amount allowed."""
    world = await _seed(session)
    app = await _app(session, world, "approved")
    session.add(
        ApplicationDecision(
            application_id=app.id, approved_amount=Decimal("100.00"), conditions=["Belege"]
        )
    )
    await session.execute(
        update(Application)
        .where(Application.id == app.id)
        .values(approved_amount=Decimal("100.00"))
    )
    await session.commit()
    payload = AmendIn.model_validate(
        {
            "approvedAmount": "122.00",
            "reason": "Mehrkosten beim Druck",
            "decisionDate": date.today().isoformat(),
            "gremiumId": str(world.gremium.id),
        }
    )
    out = await amend_approved_amount(
        session, app.id, payload, actor="clerk-1", now=datetime.now(UTC)
    )
    await session.commit()
    assert (out.previous_amount, out.approved_amount) == (Decimal("100.00"), Decimal("122.00"))
    await session.refresh(app)
    assert app.current_state_id == world.states["approved"].id
    assert app.approved_amount == Decimal("122.00")
    rows = (
        (
            await session.execute(
                select(ApplicationDecision).where(ApplicationDecision.application_id == app.id)
            )
        )
        .scalars()
        .all()
    )
    valid = [r for r in rows if r.superseded_at is None]
    assert len(rows) == 2
    assert valid[0].conditions == ["Belege"]
    assert valid[0].amend_reason == "Mehrkosten beim Druck"
    timeline = await ApplicationsService(session).timeline(app.id)
    change = next(e for e in timeline if e.kind == "amountChange")
    assert change.amount_change is not None
    assert change.amount_change.previous_amount == Decimal("100.00")
    assert change.amount_change.reason == "Mehrkosten beim Druck"
    seen = await ApplicationsService(session).timeline(app.id, applicant_view=True)
    hidden = next(e for e in seen if e.kind == "amountChange")
    assert hidden.amount_change is not None
    assert hidden.amount_change.reason is None
    facts = await mail_facts(session, app.id, world.gremium.id)
    assert facts is not None
    assert facts.gremium == world.gremium.name
    assert await mail_facts(session, uuid.uuid4(), world.gremium.id) is None


@pytest.mark.parametrize(
    ("state", "change", "error"),
    [
        ("draft", {}, ConflictError),
        ("approved", {"approvedAmount": "100.00"}, ValidationProblem),
        ("approved", {"gremiumId": str(uuid.uuid4())}, ValidationProblem),
        ("approved", {"approvedAmount": "-1.00"}, ValidationProblem),
    ],
)
async def test_amend_refuses(
    session: AsyncSession, state: str, change: dict[str, str], error: type[Exception]
) -> None:
    world = await _seed(session)
    app = await _app(session, world, state)
    payload = AmendIn.model_validate(
        {
            "approvedAmount": "50.00",
            "reason": "Mehrkosten beim Druck",
            "decisionDate": date.today().isoformat(),
            "gremiumId": str(world.gremium.id),
            **change,
        }
    )
    with pytest.raises(error):
        await amend_approved_amount(
            session, app.id, payload, actor="clerk-1", now=datetime.now(UTC)
        )


async def test_forced_report_counts_reasons_and_paths(session: AsyncSession) -> None:
    """§ 001650-001652: per reason and per path; an old change counts as `none`."""
    world = await _seed(session)
    first = await _app(session, world, "draft")
    second = await _app(session, world, "draft")
    third = await _app(session, world, "draft")
    flow = FlowService(session)
    await flow.force_status(
        first.id, world.states["rejected"].id, _clerk(), reason="applicant_error"
    )
    await flow.force_status(
        second.id, world.states["rejected"].id, _clerk(), reason="other", note="Antrag doppelt"
    )
    session.add(
        StatusEvent(
            application_id=third.id,
            from_state_id=world.states["draft"].id,
            to_state_id=world.states["approved"].id,
            note=".",
            forced=True,
        )
    )
    await session.commit()
    today = date.today()

    report = await forced_report(session, today - timedelta(days=1), today + timedelta(days=1))

    assert report.total == 3
    assert {r.reason: r.count for r in report.by_reason} == {
        "applicant_error": 1,
        "other": 1,
        "none": 1,
    }
    assert [(p.from_key, p.to_key, p.count) for p in report.by_path] == [
        ("draft", "rejected", 2),
        ("draft", "approved", 1),
    ]
    events = await forced_events(
        session,
        today - timedelta(days=1),
        today + timedelta(days=1),
        from_key="draft",
        to_key="rejected",
    )
    assert {e.application_id for e in events} == {first.id, second.id}
    old = await forced_events(
        session, today - timedelta(days=1), today + timedelta(days=1), reason="none"
    )
    assert [e.title for e in old] == ["Exkursion"]


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("backfill_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_migration_backfills_the_approved_amount(
    session: AsyncSession, engine: Engine
) -> None:
    """§ 001613: an approval without an amount gets the requested amount and a decision."""
    world = await _seed(session)
    bare = await _app(session, world, "approved", amount="70.00")
    kept = await _app(session, world, "approved", amount="80.00")
    session.add(ApplicationDecision(application_id=kept.id, approved_amount=None, conditions=["A"]))
    open_app = await _app(session, world, "draft", amount="90.00")
    await session.commit()
    module = _migration()

    with engine.begin() as conn:
        for statement in module._BACKFILL:
            conn.execute(text(statement))

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT application_id, approved_amount, conditions FROM application_decision "
                "WHERE superseded_at IS NULL"
            )
        ).all()
        amounts = dict(
            conn.execute(
                text("SELECT id, approved_amount FROM application WHERE id = ANY(:ids)"),
                {"ids": [bare.id, kept.id, open_app.id]},
            ).all()
        )
    valid = {r[0]: (r[1], r[2]) for r in rows}
    assert valid[bare.id] == (Decimal("70.00"), [])
    assert valid[kept.id] == (Decimal("80.00"), ["A"])
    assert open_app.id not in valid
    assert amounts == {bare.id: Decimal("70.00"), kept.id: Decimal("80.00"), open_app.id: None}
