"""Seed helpers for the vote lifecycle tests of P4 (real Postgres).

`seed_vote_flow` builds one gremium, one application type with an active form and one
flow: `review` -> `voting` (a vote state) with the exits `pass` -> `approved`,
`fail` -> `rejected` and the manual exit `abort` -> `review`. The application starts in
`voting`. A test can give the `pass` exit a guard or drop the `fail` exit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.livevote.models import Meeting
from app.modules.voting.models import Vote
from app.shared.config_schemas import FormFieldDef, VoteConfig


@dataclass
class VoteFlow:
    """Ids of the seeded rows. The ids stay valid after a rollback expires the ORM rows."""

    gremium_id: uuid.UUID
    app_id: uuid.UUID
    states: dict[str, uuid.UUID]
    transitions: dict[str, uuid.UUID]


async def seed_vote_flow(
    session: AsyncSession,
    *,
    pass_guard: dict[str, Any] | None = None,
    with_fail: bool = True,
    start: str = "voting",
) -> VoteFlow:
    tag = uuid.uuid4().hex[:8]
    gremium = Gremium(name="G", slug=f"g-{tag}")
    session.add(gremium)
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
        "review": State(flow_version_id=flow.id, key="review", label_i18n={},
                        edit_allowed=True, is_initial=True),
        "voting": State(flow_version_id=flow.id, key="voting", label_i18n={},
                        edit_allowed=False, kind="vote",
                        config={"gremiumId": str(gremium.id)}),
        "approved": State(flow_version_id=flow.id, key="approved", label_i18n={},
                          edit_allowed=False),
        "rejected": State(flow_version_id=flow.id, key="rejected", label_i18n={},
                          edit_allowed=False),
    }
    session.add_all(list(states.values()))
    await session.flush()
    transitions = {
        "start": Transition(flow_version_id=flow.id, from_state_id=states["review"].id,
                            to_state_id=states["voting"].id, label_i18n={}, actions=[],
                            order=0),
        "pass": Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                           to_state_id=states["approved"].id, label_i18n={},
                           branch="pass", guard=pass_guard, actions=[], order=0),
        "abort": Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                            to_state_id=states["review"].id, label_i18n={}, actions=[],
                            order=2),
    }
    if with_fail:
        transitions["fail"] = Transition(
            flow_version_id=flow.id, from_state_id=states["voting"].id,
            to_state_id=states["rejected"].id, label_i18n={}, branch="fail",
            actions=[], order=1,
        )
    session.add_all(list(transitions.values()))
    await session.commit()
    app, _ = await ApplicationsService(session).create(
        ApplicationCreate.model_validate(
            {"typeId": str(app_type.id), "data": {"title": "T"},
             "applicantEmail": "a@example.org"}
        )
    )
    row = await session.get(Application, app.id)
    assert row is not None
    row.current_state_id = states[start].id
    # The snapshot that the flow engine sets on entry into a vote state.
    row.vote_gremium_id = gremium.id if states[start].kind == "vote" else None
    await session.commit()
    return VoteFlow(
        gremium_id=gremium.id,
        app_id=app.id,
        states={k: v.id for k, v in states.items()},
        transitions={k: v.id for k, v in transitions.items()},
    )


async def add_meeting(session: AsyncSession, gremium_id: uuid.UUID) -> uuid.UUID:
    meeting = Meeting(gremium_id=gremium_id, title="Sitzung", status="live")
    session.add(meeting)
    await session.commit()
    return meeting.id


async def add_vote(
    session: AsyncSession,
    flow: VoteFlow,
    *,
    status: str = "open",
    meeting_id: uuid.UUID | None = None,
    opens_state: str | None = None,
    opens_at: datetime | None = None,
    secret: bool = False,
) -> uuid.UUID:
    config = VoteConfig.model_validate(
        {"options": ["yes", "no", "abstain"], "majorityRule": "simple", "secret": secret}
    ).model_dump(by_alias=True)
    vote = Vote(
        application_id=flow.app_id,
        meeting_id=meeting_id,
        eligible_group=str(flow.gremium_id),
        config=config,
        eligible_count=3,
        status=status,
        opens_at=opens_at,
        opens_state_id=flow.states[opens_state] if opens_state else None,
    )
    session.add(vote)
    await session.commit()
    return vote.id


def voter(sub: str, flow: VoteFlow) -> Principal:
    """A voter with the gremium `vote.cast` in the gremium of the flow."""
    return Principal(sub=sub, groups={vote_group_key(flow.gremium_id)})


def manager() -> Principal:
    return Principal(sub="mgr", roles=["admin"], permissions={"application.transition"})


async def audit_actions(session: AsyncSession, target_id: uuid.UUID) -> list[AuditEntry]:
    rows = await session.execute(
        select(AuditEntry)
        .where(AuditEntry.target_id == str(target_id))
        .order_by(AuditEntry.id)
    )
    return list(rows.scalars().all())


class RecordingPublisher:
    """A `MeetingPublisher` stand-in that records the cancelled votes."""

    def __init__(self) -> None:
        self.cancelled: list[uuid.UUID] = []

    async def vote_cancelled(self, vote: Any) -> None:
        self.cancelled.append(vote.id)
