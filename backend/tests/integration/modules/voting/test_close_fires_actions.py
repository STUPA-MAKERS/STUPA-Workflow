"""F2: a vote close runs the actions of the fired branch (real Postgres).

Before the fix the REST close `POST /votes/{id}/close` used a local dispatcher
dependency that `app.main` did not override. The branch then fired without its
actions. The worker had no `ctx['flow_dispatcher']` either and sent only the mails.

The tests seed a vote state whose `pass` and `fail` exits carry a `webhook` and an
`assignBudget` action. After the close:

* the application has the cost center of `assignBudget` (extras dispatcher),
* a `webhook_delivery` row is pending for the webhook (webhook dispatcher; without an
  arq pool the delivery stays pending),
* the notify dispatcher ran without an error (no pool: it only logs).

Both the REST route through the real `app.main` wiring and the worker auto-close run
the whole chain.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.main as main_mod
import worker.deadlines as wd
from app.db import get_session
from app.deps import get_current_principal
from app.main import create_app
from app.modules.admin.models import ApplicationType, Gremium, Webhook, WebhookDelivery
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import Budget
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.voting.models import Vote
from app.settings import get_settings, load_settings
from app.shared.config_schemas import FormFieldDef, VoteConfig

pytestmark = pytest.mark.integration


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


class _Seed:
    def __init__(self, app_id: uuid.UUID, vote_id: uuid.UUID, budget_id: uuid.UUID,
                 webhook_id: uuid.UUID) -> None:
        self.app_id = app_id
        self.vote_id = vote_id
        self.budget_id = budget_id
        self.webhook_id = webhook_id


async def _seed(
    maker: async_sessionmaker[AsyncSession], *, closes_at: datetime | None = None
) -> _Seed:
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        gremium = Gremium(name="G", slug=f"g-{tag}")
        session.add(gremium)
        await session.flush()
        app_type = ApplicationType(
            gremium_id=gremium.id, key=f"t-{tag}", name_i18n={}, has_budget=False
        )
        budget = Budget(parent_id=None, key=f"K{tag}", path_key=f"K{tag}", name="Topf")
        hook = Webhook(
            name=f"h-{tag}", url="https://hook.test/h", events=[], active=True,
            secret=b"k",
        )
        session.add_all([app_type, budget, hook])
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
        voting = State(flow_version_id=flow.id, key="voting", label_i18n={"de": "Abst."},
                       edit_allowed=False, is_initial=True, kind="vote",
                       config={"gremiumId": str(gremium.id)})
        approved = State(flow_version_id=flow.id, key="approved", label_i18n={},
                         edit_allowed=False)
        rejected = State(flow_version_id=flow.id, key="rejected", label_i18n={},
                         edit_allowed=False)
        session.add_all([voting, approved, rejected])
        await session.flush()
        actions: list[dict[str, Any]] = [
            {"type": "webhook", "webhookId": str(hook.id)},
            {"type": "assignBudget", "budgetId": str(budget.id)},
        ]
        session.add_all([
            Transition(flow_version_id=flow.id, from_state_id=voting.id,
                       to_state_id=approved.id, label_i18n={}, branch="pass",
                       actions=actions, order=0),
            Transition(flow_version_id=flow.id, from_state_id=voting.id,
                       to_state_id=rejected.id, label_i18n={}, branch="fail",
                       actions=actions, order=1),
        ])
        await session.commit()
        app, _ = await ApplicationsService(session).create(
            ApplicationCreate.model_validate(
                {"typeId": str(app_type.id), "data": {"title": "T"},
                 "applicantEmail": "a@example.org"}
            )
        )
        row = await session.get(Application, app.id)
        assert row is not None
        row.current_state_id = voting.id
        config = VoteConfig.model_validate(
            {"options": ["yes", "no", "abstain"], "majorityRule": "simple"}
        ).model_dump(by_alias=True)
        vote = Vote(application_id=app.id, eligible_group=str(gremium.id),
                    config=config, status="open", closes_at=closes_at)
        session.add(vote)
        await session.commit()
        return _Seed(app.id, vote.id, budget.id, hook.id)


async def _assert_actions_ran(
    maker: async_sessionmaker[AsyncSession], seed: _Seed
) -> None:
    async with maker() as session:
        app = await session.get(Application, seed.app_id)
        assert app is not None
        assert app.budget_id == seed.budget_id
        deliveries = (
            await session.scalars(
                select(WebhookDelivery).where(WebhookDelivery.webhook_id == seed.webhook_id)
            )
        ).all()
        assert len(deliveries) == 1
        assert deliveries[0].status == "pending"
        vote = await session.get(Vote, seed.vote_id)
        assert vote is not None
        assert vote.status == "closed"


@pytest.fixture
def api(
    migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastAPI]:
    settings = load_settings(
        database_url=migrated[1],
        session_secret="session-secret-close-actions-0",
        magic_link_secret="magic-link-secret-close-act0",
        cookie_secure=False,
    )

    # The TestClient runs the app on its own event loop. It gets its own engine without
    # a pool, so no connection crosses the loops.
    maker = async_sessionmaker(
        create_async_engine(migrated[1], poolclass=NullPool), expire_on_commit=False
    )

    async def _request_session() -> AsyncIterator[AsyncSession]:
        async with maker() as db:
            yield db

    # The real app wiring builds the dispatcher chain per request. Point its
    # sessionmaker at the test database.
    monkeypatch.setattr(main_mod, "get_sessionmaker", lambda: maker)
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_session] = _request_session
    application.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin-closer", roles=["admin"]
    )
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


async def test_rest_close_runs_branch_actions(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    seed = await _seed(maker)
    with TestClient(api) as client:
        resp = client.post(f"/api/votes/{seed.vote_id}/close")
    assert resp.status_code == 200, resp.text
    assert resp.json()["firedTransitionId"] is not None
    await _assert_actions_ran(maker, seed)


async def test_worker_auto_close_runs_branch_actions(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    seed = await _seed(maker, closes_at=now - timedelta(minutes=1))
    # No `flow_dispatcher` in the ctx: the worker builds the full chain itself.
    ctx: dict[str, Any] = {"settings": get_settings(), "deadlines_sessionmaker": maker}
    assert await wd._close_one(ctx, seed.vote_id, now) is True
    await _assert_actions_ran(maker, seed)
