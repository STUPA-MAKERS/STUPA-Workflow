"""Seed helpers for the agenda tests of the flow engine (A1, F3).

The flow has the states `review` (initial), `voting` (a vote state of the Gremium) and
`done`. The transition `review → voting` carries `addToNextSession` for the Gremium.
The transition `review → done` carries the same action but leads into a normal state,
which the engine must refuse with a meeting.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.principal import Principal
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.livevote.models import Meeting
from app.shared.config_schemas import FormFieldDef


@dataclass
class AgendaFlow:
    gremium: Gremium
    other_gremium: Gremium
    app_type: ApplicationType
    states: dict[str, State]
    to_vote: Transition
    to_done: Transition
    plain: Transition


def admin() -> Principal:
    return Principal(
        sub="admin-agenda", roles=["admin"], permissions={"application.transition"}
    )


async def seed_agenda_flow(session: AsyncSession) -> AgendaFlow:
    tag = uuid.uuid4().hex[:8]
    gremium = Gremium(name="StuPa", slug=f"stupa-{tag}")
    other = Gremium(name="AStA", slug=f"asta-{tag}")
    session.add_all([gremium, other])
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{tag}", name_i18n={}, has_budget=False
    )
    session.add(app_type)
    await session.commit()
    await FormsService(session).create_form_version(
        app_type.id,
        FormVersionCreate(
            fields=[FormFieldDef(key="title", type="text", label={"de": "Titel"},
                                 required=True)],
            activate=True,
        ),
        "tester",
    )
    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    states = {
        "review": State(flow_version_id=flow.id, key="review", label_i18n={"de": "Prüfung"},
                        edit_allowed=True, is_initial=True),
        "voting": State(flow_version_id=flow.id, key="voting", label_i18n={"de": "Abst."},
                        edit_allowed=False, kind="vote",
                        config={"gremiumId": str(gremium.id)}),
        "done": State(flow_version_id=flow.id, key="done", label_i18n={"de": "Fertig"},
                      edit_allowed=False),
    }
    session.add_all(list(states.values()))
    await session.flush()
    action = {"type": "addToNextSession", "gremiumId": str(gremium.id)}
    to_vote = Transition(
        flow_version_id=flow.id, from_state_id=states["review"].id,
        to_state_id=states["voting"].id, label_i18n={"de": "Auf TO"},
        actions=[action], order=0,
    )
    to_done = Transition(
        flow_version_id=flow.id, from_state_id=states["review"].id,
        to_state_id=states["done"].id, label_i18n={"de": "Fertig"},
        actions=[action], order=1,
    )
    plain = Transition(
        flow_version_id=flow.id, from_state_id=states["review"].id,
        to_state_id=states["voting"].id, label_i18n={"de": "Ohne TO"},
        actions=[], order=2,
    )
    session.add_all([to_vote, to_done, plain])
    await session.commit()
    return AgendaFlow(gremium, other, app_type, states, to_vote, to_done, plain)


async def make_application(session: AsyncSession, flow: AgendaFlow) -> Application:
    app, _ = await ApplicationsService(session).create(
        ApplicationCreate.model_validate(
            {"typeId": str(flow.app_type.id), "data": {"title": "Antrag"},
             "applicantEmail": "a@example.org"}
        )
    )
    row = await session.get(Application, app.id)
    assert row is not None
    return row


async def make_meeting(
    session: AsyncSession,
    gremium: Gremium,
    *,
    day: date | None,
    status: str = "planned",
    title: str = "Sitzung",
) -> Meeting:
    meeting = Meeting(gremium_id=gremium.id, title=title, date=day, status=status)
    session.add(meeting)
    await session.commit()
    return meeting
