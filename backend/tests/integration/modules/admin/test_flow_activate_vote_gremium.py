"""Flow variant B at the flow save (real Postgres).

* The save refuses an `assignBudgetFromMap` or `assignBudgetFromApplicantGremium`
  action that names an unknown cost center (422).
* The activation re-derives the snapshot `vote_gremium_id` of the moved applications:
  a non-vote state clears it, a fixed vote state sets its Gremium, a vote state with
  `gremiumSource: "budget"` keeps an existing snapshot and fills a missing one from the
  cost center.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import Gremium
from app.modules.admin.schemas import FlowVersionCreate
from app.modules.admin.service import ConfigService
from app.modules.applications.models import Application
from app.modules.budget.tree_models import Budget
from app.modules.flow.models import State
from app.modules.forms.models import FormVersion
from app.shared.errors import ValidationProblem
from tests.integration.modules.admin.test_admin_service import _make_type

pytestmark = pytest.mark.integration

_ACTOR = "oidc|admin"


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


def _graph(vote_config: dict[str, Any], actions: list[dict[str, Any]] | None = None) -> dict:
    return {
        "states": [
            {"key": "review", "label": {"de": "P"}, "isInitial": True},
            {"key": "gvote", "label": {"de": "GV"}, "kind": "vote", "config": vote_config},
            {"key": "fixed", "label": {"de": "FV"}, "kind": "vote",
             "config": vote_config if "gremiumId" in vote_config else {}},
            {"key": "done", "label": {"de": "OK"}},
        ],
        "transitions": [
            {"from": "review", "to": "gvote", "actions": actions or []},
            {"from": "review", "to": "fixed"},
            {"from": "gvote", "to": "done", "branch": "pass"},
            {"from": "gvote", "to": "done", "branch": "fail"},
            {"from": "fixed", "to": "done", "branch": "pass"},
            {"from": "fixed", "to": "done", "branch": "fail"},
        ],
    }


async def _save(session: AsyncSession, graph: dict[str, Any]) -> uuid.UUID:
    out = await ConfigService(session).create_global_flow_version(
        FlowVersionCreate.model_validate({"graph": graph}), _ACTOR
    )
    return out.id


async def _state(session: AsyncSession, version: uuid.UUID, key: str) -> uuid.UUID:
    return (
        await session.scalars(
            select(State.id).where(State.flow_version_id == version, State.key == key)
        )
    ).one()


async def _snapshot(session: AsyncSession, app_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(
        select(Application.vote_gremium_id)
        .where(Application.id == app_id)
        .execution_options(populate_existing=True)
    )


async def test_save_refuses_unknown_cost_centers(session: AsyncSession) -> None:
    g = Gremium(name="G", slug=f"g-{uuid.uuid4().hex[:8]}")
    session.add(g)
    await session.commit()
    fixed = {"gremiumId": str(g.id)}
    for action in (
        {"type": "assignBudgetFromMap", "field": "f", "map": {"a": str(uuid.uuid4())}},
        {"type": "assignBudgetFromMap", "field": "f", "map": {"a": "not-a-uuid"}},
        {"type": "assignBudgetFromApplicantGremium", "parentId": str(uuid.uuid4())},
    ):
        graph = _graph(fixed)
        graph["transitions"].append({"from": "review", "to": "done", "actions": [action]})
        with pytest.raises(ValidationProblem):
            await _save(session, graph)
    top = Budget(parent_id=None, key=f"K{uuid.uuid4().hex[:8]}", path_key="", name="T")
    top.path_key = top.key
    session.add(top)
    await session.commit()
    graph = _graph(fixed)
    graph["transitions"].append({"from": "review", "to": "done", "actions": [
        {"type": "assignBudgetFromMap", "field": "f", "map": {"a": str(top.id)}},
        {"type": "assignBudgetFromApplicantGremium", "parentId": str(top.id)},
    ]})
    await _save(session, graph)  # no raise


async def test_activation_rederives_the_snapshot(session: AsyncSession) -> None:
    tag = uuid.uuid4().hex[:8]
    g_a, g_b, g_old = (Gremium(name=n, slug=f"{n}-{tag}") for n in ("a", "b", "old"))
    session.add_all([g_a, g_b, g_old])
    await session.flush()
    budget = Budget(parent_id=None, key=f"K{tag}", path_key=f"K{tag}", name="T",
                    decision_gremium_id=g_b.id)
    session.add(budget)
    await session.commit()

    v1 = await _save(session, _graph({"gremiumId": str(g_old.id)}))
    app_type = await _make_type(session)
    fv = FormVersion(application_type_id=app_type.id, version=1)
    session.add(fv)
    await session.flush()

    def _app(
        state: uuid.UUID, snapshot: uuid.UUID | None, budget_id: uuid.UUID | None
    ) -> Application:
        return Application(
            type_id=app_type.id, form_version_id=fv.id, flow_version_id=v1,
            current_state_id=state, data={}, vote_gremium_id=snapshot, budget_id=budget_id,
        )

    keep = _app(await _state(session, v1, "gvote"), g_old.id, budget.id)
    fill = _app(await _state(session, v1, "gvote"), None, budget.id)
    empty = _app(await _state(session, v1, "gvote"), None, None)
    fixed = _app(await _state(session, v1, "fixed"), g_old.id, None)
    review = _app(await _state(session, v1, "review"), g_old.id, None)
    session.add_all([keep, fill, empty, fixed, review])
    await session.commit()

    # v2: `gvote` takes the cost center, `fixed` moves to Gremium A.
    graph = _graph({"gremiumSource": "budget"})
    graph["states"][2]["config"] = {"gremiumId": str(g_a.id)}
    await _save(session, graph)

    assert await _snapshot(session, keep.id) == g_old.id
    assert await _snapshot(session, fill.id) == g_b.id
    assert await _snapshot(session, empty.id) is None
    assert await _snapshot(session, fixed.id) == g_a.id
    assert await _snapshot(session, review.id) is None
