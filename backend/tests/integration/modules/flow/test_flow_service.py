"""Integration test for the flow and status engine (real Postgres, testcontainers, T-12).

The tests run against a real schema. See flows section 3 and 9, data-model section 1
and 5.2. `available_transitions` filters by guard. `fire` changes the state atomically,
writes a `status_event` and dispatches the actions. The edit lock blocks the T-12
`patch` with 409. A failed guard gives 409. The vote result picks the branch
(`voteResult` passed, rejected or tie). Optimistic locking turns a concurrent
transition into 409.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application, StatusEvent
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.flow.schemas import TransitionResult
from app.modules.flow.service import FlowService
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError

pytestmark = pytest.mark.integration


class _Recorder:
    def __init__(self) -> None:
        self.actions: list[DispatchedAction] = []

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        self.actions.extend(actions)


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


def _manager() -> Principal:
    return Principal(
        sub="mgr-1",
        roles=["reviewer"],
        permissions={"application.manage"},
    )


async def _seed(session: AsyncSession) -> tuple[ApplicationType, dict[str, State]]:
    """Create the type, the active form and the flow (draft→review→voting→approved/rejected)."""
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{uuid.uuid4()}", name_i18n={}, has_budget=False
    )
    session.add(app_type)
    await session.commit()

    forms = FormsService(session)
    await forms.create_form_version(
        app_type.id,
        FormVersionCreate(
            fields=[
                FormFieldDef(
                    key="title", type="text", label={"de": "Titel"}, required=True
                )
            ],
            activate=True,
        ), "tester")

    flow = FlowVersion(
        version=1, active=True, editor_layout={}
    )
    session.add(flow)
    await session.flush()

    states = {
        "draft": State(
            flow_version_id=flow.id, key="draft", label_i18n={"de": "Entwurf"},
            edit_allowed=True, is_initial=True,
        ),
        "review": State(
            flow_version_id=flow.id, key="review", label_i18n={"de": "Prüfung"},
            edit_allowed=True,
        ),
        "voting": State(
            flow_version_id=flow.id, key="voting", label_i18n={"de": "Abstimmung"},
            edit_allowed=False,
        ),
        "approved": State(
            flow_version_id=flow.id, key="approved", label_i18n={"de": "Bewilligt"},
            edit_allowed=False,
        ),
        "rejected": State(
            flow_version_id=flow.id, key="rejected", label_i18n={"de": "Abgelehnt"},
            edit_allowed=False,
        ),
    }
    session.add_all(list(states.values()))
    await session.flush()

    transitions = [
        Transition(
            flow_version_id=flow.id, from_state_id=states["draft"].id,
            to_state_id=states["review"].id, label_i18n={"de": "Einreichen"},
            guard={"and": [{"hasField": "title"}, {"roleIs": "reviewer"}]},
            actions=[{"type": "notify", "recipients": [{"kind": "applicant"}]}],
            order=0,
        ),
        Transition(
            flow_version_id=flow.id, from_state_id=states["review"].id,
            to_state_id=states["voting"].id, label_i18n={"de": "Zur Abstimmung"},
            guard={"roleIs": "treasurer"},  # the manager is NOT a treasurer, so this blocks
            actions=[], order=0,
        ),
        # Vote outcomes: fire_branch fires the pass and fail branch on vote close.
        Transition(
            flow_version_id=flow.id, from_state_id=states["voting"].id,
            to_state_id=states["approved"].id, label_i18n={"de": "Bewilligen"},
            branch="pass", actions=[{"type": "assignBudget", "budgetId": "b-1"}], order=0,
        ),
        Transition(
            flow_version_id=flow.id, from_state_id=states["voting"].id,
            to_state_id=states["rejected"].id, label_i18n={"de": "Ablehnen"},
            branch="fail", order=1,
        ),
    ]
    session.add_all(transitions)
    await session.commit()
    return app_type, states


async def _make_application(
    session: AsyncSession, app_type: ApplicationType
) -> Application:
    svc = ApplicationsService(session)
    app, _ = await svc.create(
        ApplicationCreate.model_validate(
            {
                "typeId": str(app_type.id),
                "data": {"title": "Mein Antrag"},
                "applicantEmail": "a@example.org",
            }
        )
    )
    return app


async def test_available_transitions_filters_by_guard(session: AsyncSession) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)

    out = await FlowService(session).available_transitions(app.id, _manager())
    # draft has exactly one transition and its guard passes: title set, actor is reviewer.
    assert [t.to_state_id for t in out] == [states["review"].id]


async def test_fire_moves_state_writes_event_dispatches(session: AsyncSession) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)
    transition = (
        await session.execute(
            select(Transition).where(Transition.from_state_id == states["draft"].id)
        )
    ).scalar_one()
    rec = _Recorder()

    res = await FlowService(session, rec).fire(
        app.id, transition.id, _manager(), note="ok"
    )
    assert res.new_state_id == states["review"].id
    # The fire() call also dispatches the implicit `taskNotify` mail, besides the
    # configured `notify` action. The mail goes to the principals who may act on
    # the new state (#4-3, build_implicit_notifications).
    assert res.dispatched_actions == ["notify", "taskNotify"]
    assert rec.actions[0].type == "notify"
    assert rec.actions[0].idempotency_key.endswith(":0:notify")

    refreshed = await session.get(Application, app.id)
    assert refreshed is not None
    await session.refresh(refreshed)
    assert refreshed.current_state_id == states["review"].id

    events = (
        await session.execute(
            select(StatusEvent).where(StatusEvent.application_id == app.id)
        )
    ).scalars().all()
    # The timeline holds the initial create event plus the transition event.
    fire_event = [e for e in events if e.transition_id == transition.id]
    assert len(fire_event) == 1
    assert fire_event[0].from_state_id == states["draft"].id
    assert fire_event[0].actor == "mgr-1"


async def test_fire_into_locked_state_blocks_t12_patch(session: AsyncSession) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)
    apps = ApplicationsService(session)
    flow = FlowService(session)

    # review still allows edits, so the T-12 patch passes.
    t_review = (
        await session.execute(
            select(Transition).where(
                Transition.from_state_id == states["draft"].id,
                Transition.to_state_id == states["review"].id,
            )
        )
    ).scalar_one()
    await flow.fire(app.id, t_review.id, _manager())
    await apps.patch(app.id, {"title": "Aktualisiert"}, changed_by="mgr-1")

    # Put the application into `voting` (no manager path leads there), then move into
    # the locked `approved` state (edit_allowed=False) with fire_branch. The lock then
    # comes from the transition itself, not from a state that the test sets by hand.
    # `voting` → `approved` is a `pass` branch. Only a vote result fires
    # a branch transition, through fire_branch. A manual `fire` blocks with 409 on purpose.
    app_row = await session.get(Application, app.id)
    assert app_row is not None
    app_row.current_state_id = states["voting"].id
    await session.commit()

    res = await flow.fire_branch(app.id, "pass", _manager())
    assert res.new_state_id == states["approved"].id

    # The transition now blocks the T-12 patch with 409.
    with pytest.raises(ConflictError):
        await apps.patch(app.id, {"title": "Verboten"}, changed_by="mgr-1")


async def test_fire_guard_failed_409(session: AsyncSession) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)
    flow = FlowService(session)

    # review → voting needs roleIs treasurer, which the manager does not have.
    t_review = (
        await session.execute(
            select(Transition).where(
                Transition.from_state_id == states["draft"].id,
                Transition.to_state_id == states["review"].id,
            )
        )
    ).scalar_one()
    await flow.fire(app.id, t_review.id, _manager())
    t_voting = (
        await session.execute(
            select(Transition).where(Transition.to_state_id == states["voting"].id)
        )
    ).scalar_one()
    with pytest.raises(ConflictError) as exc:
        await flow.fire(app.id, t_voting.id, _manager())
    assert exc.value.code == "guard_failed"


@pytest.mark.parametrize(
    ("branch", "target"),
    [("pass", "approved"), ("fail", "rejected")],
)
async def test_fire_branch_routes_to_target(
    session: AsyncSession, branch: str, target: str
) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)
    app_row = await session.get(Application, app.id)
    assert app_row is not None
    app_row.current_state_id = states["voting"].id
    await session.commit()

    flow = FlowService(session)
    res = await flow.fire_branch(app.id, branch, _manager())
    assert res.new_state_id == states[target].id


async def test_fire_wrong_from_state_conflict(session: AsyncSession) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)
    flow = FlowService(session)
    t_review = (
        await session.execute(
            select(Transition).where(
                Transition.from_state_id == states["draft"].id,
                Transition.to_state_id == states["review"].id,
            )
        )
    ).scalar_one()
    await flow.fire(app.id, t_review.id, _manager())
    # Fire the same transition again: from(draft) != current(review) → 409.
    with pytest.raises(ConflictError) as exc:
        await flow.fire(app.id, t_review.id, _manager())
    assert exc.value.code == "conflict"


async def test_fire_concurrent_race_exactly_one_wins(
    migrated: tuple[str, str], session: AsyncSession
) -> None:
    """Race two concurrent `fire` calls on the same from-state.

    Both calls use a **separate** session and connection. Exactly one call wins. The
    other one gets 409.

    The test hits the real `rowcount == 0` path, not a fake or sequential one. The
    second transaction waits on the row lock. After the first transaction commits, the
    second one sees `current != from` and gets rowcount 0.
    """
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)
    transition = (
        await session.execute(
            select(Transition).where(
                Transition.from_state_id == states["draft"].id,
                Transition.to_state_id == states["review"].id,
            )
        )
    ).scalar_one()

    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    try:

        async def _fire() -> TransitionResult | ConflictError:
            async with maker() as s:
                try:
                    return await FlowService(s).fire(app.id, transition.id, _manager())
                except ConflictError as exc:
                    return exc

        first, second = await asyncio.gather(_fire(), _fire())
    finally:
        await eng.dispose()

    winner = second if isinstance(first, ConflictError) else first
    loser = first if isinstance(first, ConflictError) else second
    assert isinstance(winner, TransitionResult)
    assert isinstance(loser, ConflictError)
    assert loser.code == "conflict"
    assert winner.new_state_id == states["review"].id

    refreshed = await session.get(Application, app.id)
    assert refreshed is not None
    await session.refresh(refreshed)
    assert refreshed.current_state_id == states["review"].id
