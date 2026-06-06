"""Integration (echte Postgres, testcontainers): Flow-/Status-Engine gegen T-12.

Beweist gegen ein echtes Schema (flows §3/§9, data-model §1/§5.2):
``available_transitions`` (Guard-Filter), ``fire`` (atomarer State-Wechsel +
``status_event`` + Action-Dispatch), Edit-Lock-Wirkung auf T-12 ``patch`` (409),
Guard-Fail (409), ergebnis-abhängige Verzweigung (``voteResult`` passed/rejected/tie)
und optimistisches Locking (konkurrierende Transition → 409).
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
    """Typ + aktive Form + Flow (draft→review→voting→approved/rejected) anlegen."""
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
        ),
    )

    flow = FlowVersion(
        application_type_id=app_type.id, version=1, active=True, editor_layout={}
    )
    session.add(flow)
    await session.flush()

    states = {
        "draft": State(
            flow_version_id=flow.id, key="draft", label_i18n={"de": "Entwurf"},
            category="open", edit_allowed=True, is_initial=True,
        ),
        "review": State(
            flow_version_id=flow.id, key="review", label_i18n={"de": "Prüfung"},
            category="open", edit_allowed=True,
        ),
        "voting": State(
            flow_version_id=flow.id, key="voting", label_i18n={"de": "Abstimmung"},
            category="running", edit_allowed=False,
        ),
        "approved": State(
            flow_version_id=flow.id, key="approved", label_i18n={"de": "Bewilligt"},
            category="closed", edit_allowed=False,
        ),
        "rejected": State(
            flow_version_id=flow.id, key="rejected", label_i18n={"de": "Abgelehnt"},
            category="closed", edit_allowed=False,
        ),
    }
    session.add_all(list(states.values()))
    await session.flush()

    transitions = [
        Transition(
            flow_version_id=flow.id, from_state_id=states["draft"].id,
            to_state_id=states["review"].id, label_i18n={"de": "Einreichen"},
            guard={"and": [{"fieldsComplete": True}, {"roleIs": "reviewer"}]},
            actions=[{"type": "notify", "group": "gremium"},
                     {"type": "setEditLock", "locked": False}],
            order=0,
        ),
        Transition(
            flow_version_id=flow.id, from_state_id=states["review"].id,
            to_state_id=states["voting"].id, label_i18n={"de": "Zur Abstimmung"},
            guard={"roleIs": "treasurer"},  # mgr ist NICHT treasurer → blockiert
            actions=[{"type": "openVote"}], order=0,
        ),
        Transition(
            flow_version_id=flow.id, from_state_id=states["voting"].id,
            to_state_id=states["approved"].id, label_i18n={"de": "Bewilligen"},
            guard={"voteResult": "passed"}, actions=[{"type": "budgetBook"}], order=0,
        ),
        Transition(
            flow_version_id=flow.id, from_state_id=states["voting"].id,
            to_state_id=states["rejected"].id, label_i18n={"de": "Ablehnen"},
            guard={"voteResult": "rejected"}, order=1,
        ),
        Transition(
            flow_version_id=flow.id, from_state_id=states["voting"].id,
            to_state_id=states["review"].id, label_i18n={"de": "Zurück"},
            guard={"voteResult": "tie"}, order=2,
        ),
    ]
    session.add_all(transitions)
    app_type.active_flow_version_id = flow.id
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


# --------------------------------------------------------------------------- #
# available_transitions
# --------------------------------------------------------------------------- #
async def test_available_transitions_filters_by_guard(session: AsyncSession) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)

    out = await FlowService(session).available_transitions(app.id, _manager())
    # draft hat genau einen Übergang; Guard (fieldsComplete & roleIs reviewer) erfüllt.
    assert [t.to_state_id for t in out] == [states["review"].id]


# --------------------------------------------------------------------------- #
# fire — happy path + status_event + dispatch
# --------------------------------------------------------------------------- #
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
    assert res.dispatched_actions == ["notify"]  # setEditLock inline
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
    # Initial-Event (create) + Übergangs-Event.
    fire_event = [e for e in events if e.transition_id == transition.id]
    assert len(fire_event) == 1
    assert fire_event[0].from_state_id == states["draft"].id
    assert fire_event[0].actor == "mgr-1"


# --------------------------------------------------------------------------- #
# Edit-Lock-Wirkung auf T-12 (setEditLock → state.edit_allowed → patch 409)
# --------------------------------------------------------------------------- #
async def test_fire_into_locked_state_blocks_t12_patch(session: AsyncSession) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)
    apps = ApplicationsService(session)
    flow = FlowService(session)

    # draft → review (editierbar): T-12 patch erlaubt.
    t_review = (
        await session.execute(
            select(Transition).where(
                Transition.from_state_id == states["draft"].id,
                Transition.to_state_id == states["review"].id,
            )
        )
    ).scalar_one()
    await flow.fire(app.id, t_review.id, _manager())
    await apps.patch(app.id, {"title": "Aktualisiert"}, changed_by="mgr-1")  # ok

    # Position auf `voting` (kein Manager-Pfad dorthin), dann **per fire** in den
    # gesperrten `approved`-State (edit_allowed=False) übergehen — der Lock entsteht
    # also end-to-end aus dem Übergang, nicht aus manuellem State-Setzen.
    app_row = await session.get(Application, app.id)
    assert app_row is not None
    app_row.current_state_id = states["voting"].id
    await session.commit()

    t_approved = (
        await session.execute(
            select(Transition).where(
                Transition.from_state_id == states["voting"].id,
                Transition.to_state_id == states["approved"].id,
            )
        )
    ).scalar_one()
    res = await flow.fire(app.id, t_approved.id, _manager(), vote_result="passed")
    assert res.new_state_id == states["approved"].id

    # Folge des Übergangs: T-12 patch sperrt jetzt mit 409.
    with pytest.raises(ConflictError):
        await apps.patch(app.id, {"title": "Verboten"}, changed_by="mgr-1")


# --------------------------------------------------------------------------- #
# Guard-Fail → 409 guard_failed
# --------------------------------------------------------------------------- #
async def test_fire_guard_failed_409(session: AsyncSession) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)
    flow = FlowService(session)

    # nach review wechseln, dann review→voting (Guard roleIs treasurer) feuern → Fail.
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


# --------------------------------------------------------------------------- #
# ergebnis-abhängige Verzweigung (voteResult)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("vote_result", "target"),
    [("passed", "approved"), ("rejected", "rejected"), ("tie", "review")],
)
async def test_fire_vote_result_branches(
    session: AsyncSession, vote_result: str, target: str
) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)
    # Antrag direkt in `voting` setzen.
    app_row = await session.get(Application, app.id)
    assert app_row is not None
    app_row.current_state_id = states["voting"].id
    await session.commit()

    flow = FlowService(session)
    target_state = states[target]
    transition = (
        await session.execute(
            select(Transition).where(
                Transition.from_state_id == states["voting"].id,
                Transition.to_state_id == target_state.id,
            )
        )
    ).scalar_one()
    res = await flow.fire(app.id, transition.id, _manager(), vote_result=vote_result)
    assert res.new_state_id == target_state.id


# --------------------------------------------------------------------------- #
# optimistisches Locking — konkurrierende Transition → 409
# --------------------------------------------------------------------------- #
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
    # Erstes Feuern verschiebt draft→review.
    await flow.fire(app.id, t_review.id, _manager())
    # Zweites Feuern desselben Übergangs: from(draft) != current(review) → 409.
    with pytest.raises(ConflictError) as exc:
        await flow.fire(app.id, t_review.id, _manager())
    assert exc.value.code == "conflict"


async def test_fire_concurrent_race_exactly_one_wins(
    migrated: tuple[str, str], session: AsyncSession
) -> None:
    """Echter UPDATE-Race: zwei nebenläufige ``fire`` auf denselben from-State über
    **separate** Sessions/Verbindungen → genau einer gewinnt, der andere 409.

    Trifft den realen ``rowcount==0``-Pfad (nicht nur Fake/sequenziell): die zweite
    Transaktion blockiert am Row-Lock, sieht nach dem Commit der ersten ``current !=
    from`` und liefert rowcount 0."""
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
