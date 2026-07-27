"""Integration test for the privileged force-status override (real Postgres).

The tests run against a real schema. `FlowService.force_status` moves an application
into any state of the same flow, without a transition and without a guard. It writes a
`status_event` that has no transition. It records the change as `forced` in the audit
log. It cancels the open votes. It also keeps the limits: the same state gives 409 and
a state of a foreign flow gives 404. `list_states` returns the options for the picker.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application, StatusEvent
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.flow.service import FlowService
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.voting.models import Vote
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError, NotFoundError

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


def _forcer() -> Principal:
    return Principal(
        sub="forcer-1", roles=["reviewer"], permissions={"application.force_status"}
    )


async def _seed(session: AsyncSession) -> tuple[ApplicationType, dict[str, State]]:
    """Create the type, the active form and the flow (draft→review plus terminal `done`)."""
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{uuid.uuid4()}", name_i18n={}, has_budget=False
    )
    session.add(app_type)
    await session.commit()

    await FormsService(session).create_form_version(
        app_type.id,
        FormVersionCreate(
            fields=[
                FormFieldDef(
                    key="title", type="text", label={"de": "Titel"}, required=True
                )
            ],
            activate=True,
        ),
        "tester",
    )

    flow = FlowVersion(version=1, active=True, editor_layout={})
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
        "done": State(
            flow_version_id=flow.id, key="done", label_i18n={"de": "Fertig"},
            edit_allowed=False, is_terminal=True,
        ),
    }
    session.add_all(list(states.values()))
    await session.flush()
    # draft→review is the only *normal* transition. No path leads to `done` on purpose.
    # The override must still reach that state. That is the point of force_status.
    session.add(
        Transition(
            flow_version_id=flow.id, from_state_id=states["draft"].id,
            to_state_id=states["review"].id, label_i18n={"de": "Einreichen"},
            guard={"roleIs": "reviewer"}, order=0,
        )
    )
    await session.commit()
    return app_type, states


async def _make_application(
    session: AsyncSession, app_type: ApplicationType
) -> Application:
    app, _ = await ApplicationsService(session).create(
        ApplicationCreate.model_validate(
            {
                "typeId": str(app_type.id),
                "data": {"title": "Mein Antrag"},
                "applicantEmail": "a@example.org",
            }
        )
    )
    return app


async def test_force_status_moves_state_writes_event_and_audit(
    session: AsyncSession,
) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)

    res = await FlowService(session).force_status(
        app.id, states["done"].id, _forcer(), note="admin override"
    )
    assert res.new_state_id == states["done"].id
    assert res.dispatched_actions == []  # silent: no notifications and no webhooks

    refreshed = await session.get(Application, app.id)
    assert refreshed is not None
    await session.refresh(refreshed)
    assert refreshed.current_state_id == states["done"].id

    # The status_event on the timeline has no transition. It keeps the reason and actor.
    event = (
        await session.execute(
            select(StatusEvent).where(
                StatusEvent.application_id == app.id,
                StatusEvent.to_state_id == states["done"].id,
            )
        )
    ).scalar_one()
    assert event.transition_id is None
    assert event.from_state_id == states["draft"].id
    assert event.actor == "forcer-1"
    assert event.note == "admin override"

    # The audit holds a forced status_change. It is revertable: it has from and to ids.
    audit = (
        await session.execute(
            select(AuditEntry).where(
                AuditEntry.action == "status_change",
                AuditEntry.target_id == str(app.id),
            )
        )
    ).scalars().all()
    forced = [a for a in audit if a.data.get("forced") is True]
    assert len(forced) == 1
    assert forced[0].actor == "forcer-1"
    assert forced[0].data["fromStateId"] == str(states["draft"].id)
    assert forced[0].data["toStateId"] == str(states["done"].id)
    assert forced[0].data["transitionId"] is None


async def test_force_status_cancels_open_votes(session: AsyncSession) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)
    vote = Vote(application_id=app.id, eligible_group="grp", config={}, status="open")
    session.add(vote)
    await session.commit()

    await FlowService(session).force_status(
        app.id, states["review"].id, _forcer(), note="pull out of vote"
    )
    await session.refresh(vote)
    assert vote.status == "cancelled"


async def test_force_status_same_state_conflicts(session: AsyncSession) -> None:
    app_type, states = await _seed(session)
    app = await _make_application(session, app_type)
    # The application starts in the initial `draft` state. Forcing draft is a no-op 409.
    with pytest.raises(ConflictError):
        await FlowService(session).force_status(
            app.id, states["draft"].id, _forcer(), note="noop"
        )


async def test_force_status_foreign_flow_state_not_found(
    session: AsyncSession,
) -> None:
    app_type, _ = await _seed(session)
    app = await _make_application(session, app_type)
    # A state of a DIFFERENT flow version gives 404. The service must never write it as
    # the current state, because that would be a cross-graph FK inconsistency.
    other_flow = FlowVersion(version=2, active=False, editor_layout={})
    session.add(other_flow)
    await session.flush()
    foreign = State(
        flow_version_id=other_flow.id, key="foreign", label_i18n={"de": "Fremd"}
    )
    session.add(foreign)
    await session.commit()
    with pytest.raises(NotFoundError):
        await FlowService(session).force_status(
            app.id, foreign.id, _forcer(), note="cross-flow"
        )


async def test_list_states_returns_flow_states(session: AsyncSession) -> None:
    app_type, _ = await _seed(session)
    app = await _make_application(session, app_type)
    out = await FlowService(session).list_states(app.id)
    assert {s.key for s in out} == {"draft", "review", "done"}
    # The initial state comes first. The order is is_initial desc, then key.
    assert out[0].key == "draft"
