"""Integration (real Postgres, testcontainers): the vote auto-close of the cron.

The arq task `process_deadlines` counts an open vote with an expired `closes_at`. It
then fires the result branch of the vote state.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.voting.models import Ballot, Vote
from app.settings import load_settings
from app.shared.config_schemas import FormFieldDef, VoteConfig
from worker.deadlines import process_deadlines

pytestmark = pytest.mark.integration


class _Recorder:
    """Fake flow dispatcher that keeps Redis out of the cron-fired actions."""

    def __init__(self) -> None:
        self.actions: list[DispatchedAction] = []

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        self.actions.extend(actions)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


async def _seed_flow(session: AsyncSession) -> tuple[ApplicationType, dict[str, State]]:
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
            fields=[FormFieldDef(key="title", type="text", label={"de": "T"}, required=True)],
            activate=True,
        ), "tester")
    flow = FlowVersion(
        version=1, active=True, editor_layout={}
    )
    session.add(flow)
    await session.flush()
    states = {
        "voting": State(flow_version_id=flow.id, key="voting", label_i18n={},
                        edit_allowed=False, is_initial=True),
        "approved": State(flow_version_id=flow.id, key="approved", label_i18n={},
                          edit_allowed=False),
        "rejected": State(flow_version_id=flow.id, key="rejected", label_i18n={},
                          edit_allowed=False),
    }
    session.add_all(list(states.values()))
    await session.flush()
    session.add_all([
        Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                   to_state_id=states["approved"].id, label_i18n={},
                   branch="pass", actions=[], order=0),
        Transition(flow_version_id=flow.id, from_state_id=states["voting"].id,
                   to_state_id=states["rejected"].id, label_i18n={},
                   branch="fail", actions=[], order=1),
    ])
    await session.commit()
    return app_type, states


async def _make_app(session: AsyncSession, app_type: ApplicationType, state: State) -> Application:
    app, _ = await ApplicationsService(session).create(
        ApplicationCreate.model_validate(
            {"typeId": str(app_type.id), "data": {"title": "T"},
             "applicantEmail": "a@example.org"}
        )
    )
    row = await session.get(Application, app.id)
    assert row is not None
    row.current_state_id = state.id
    # The cron skips unconfirmed guest applications (O14). Confirm the email, as the
    # magic-link verify does.
    row.email_confirmed_at = datetime.now(UTC)
    await session.commit()
    return row


def _ctx(maker: async_sessionmaker[AsyncSession]) -> dict[str, object]:
    return {
        "settings": load_settings(),
        "deadlines_sessionmaker": maker,
        "flow_dispatcher": _Recorder(),
    }


async def test_vote_auto_close_fires_branch(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as s:
        app_type, states = await _seed_flow(s)
        app = await _make_app(s, app_type, states["voting"])
        config = VoteConfig.model_validate(
            {"options": ["yes", "no"], "majorityRule": "simple"}
        ).model_dump(by_alias=True)
        vote = Vote(
            application_id=app.id, eligible_group="grp", config=config,
            eligible_count=1, status="open", opens_at=datetime.now(UTC),
            closes_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        s.add(vote)
        await s.flush()
        s.add(Ballot(vote_id=vote.id, voter_sub="v1", choice="yes"))
        await s.commit()
        vote_id = vote.id

    out = await process_deadlines(_ctx(maker))
    assert "votes=1" in out

    async with maker() as s:
        closed = await s.get(Vote, vote_id)
        assert closed is not None
        assert closed.status == "closed"
        assert closed.result == "passed"
        moved = await s.get(Application, app.id)
        assert moved is not None
        assert moved.current_state_id == states["approved"].id  # the result branch fired
