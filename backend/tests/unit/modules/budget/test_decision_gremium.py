"""Flow variant B in the budget module: the deciding Gremium of a cost center.

`tree_rules.resolve_decision_gremium` is the pure rule (own value, else the nearest
ancestor, else none). `budget.decision` loads the ancestor chain, the node CRUD
validates and exposes the field, and the assignment refuses a change of the cost
center while a vote takes its Gremium from it.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.budget import decision, tree_rules
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_schemas import (
    AssignBudgetRequest,
    BudgetNodeCreate,
    BudgetNodeUpdate,
)
from app.modules.flow.models import State
from app.shared.errors import ConflictError, ValidationProblem
from tests.unit.modules.budget.test_tree_service_cov import _budget, fake_session, result


def test_resolve_own_value_wins() -> None:
    parent_of = {"top": None, "mid": "top", "leaf": "mid"}
    own_of = {"top": "g-top", "mid": "g-mid", "leaf": None}
    assert tree_rules.resolve_decision_gremium("mid", parent_of, own_of) == ("g-mid", "mid")


def test_resolve_inherits_the_nearest_ancestor() -> None:
    parent_of = {"top": None, "mid": "top", "leaf": "mid"}
    own_of = {"top": "g-top", "mid": None, "leaf": None}
    assert tree_rules.resolve_decision_gremium("leaf", parent_of, own_of) == ("g-top", "top")


def test_resolve_none() -> None:
    parent_of = {"top": None, "leaf": "top"}
    assert tree_rules.resolve_decision_gremium("leaf", parent_of, {}) == (None, None)
    # An unknown node ends the walk at once.
    assert tree_rules.resolve_decision_gremium("x", parent_of, {}) == (None, None)


def test_resolve_survives_a_cycle() -> None:
    parent_of = {"a": "b", "b": "a"}
    assert tree_rules.resolve_decision_gremium("a", parent_of, {}) == (None, None)


def _node(nid: str, parent: str | None, path: str, decision_gremium: object = None) -> tuple:
    return (nid, parent, None, path.split("-")[-1], path, "N", "EUR", True, None, [], [],
            1, 1, False, None, decision_gremium)


def test_build_forest_exposes_the_effective_gremium() -> None:
    g = uuid.uuid4()
    forest = tree_rules.build_forest(
        [_node("top", None, "VS"), _node("mid", "top", "VS-8", g),
         _node("leaf", "mid", "VS-8-1")],
        [], [],
    )
    top = forest[0]
    mid = top["children"][0]
    leaf = mid["children"][0]
    assert (top["decision_gremium_id"], top["effective_decision_gremium_id"]) == (None, None)
    assert (mid["effective_decision_gremium_id"], mid["decision_gremium_source_id"]) == (g, "mid")
    assert leaf["decision_gremium_id"] is None
    assert (leaf["effective_decision_gremium_id"], leaf["decision_gremium_source_id"]) == (
        g, "mid",
    )


async def test_decision_gremium_of_loads_the_ancestors() -> None:
    top, mid, leaf = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    g = uuid.uuid4()
    sess = fake_session(
        result("VS-8-1"), result((top, None, None), (mid, top, g), (leaf, mid, None))
    )
    assert await decision.decision_gremium_of(sess, leaf) == (g, mid)
    assert await decision.effective_decision_gremium(
        fake_session(result("VS"), result((top, None, g))), top
    ) == g


async def test_decision_gremium_of_unknown_node() -> None:
    assert await decision.decision_gremium_of(fake_session(result()), uuid.uuid4()) == (
        None, None,
    )
    assert await decision.effective_decision_gremium(fake_session(), None) is None


async def test_create_node_with_a_decision_gremium() -> None:
    g = uuid.uuid4()
    # Queue: the sibling check (none), the Gremium lookup.
    sess = fake_session(result(), result(g))
    out = await BudgetTreeService(sess).create_node(
        BudgetNodeCreate(key="VS", name="VS", decisionGremiumId=g)
    )
    assert out.decision_gremium_id == g
    assert (out.effective_decision_gremium_id, out.decision_gremium_source_id) == (g, out.id)


async def test_create_node_refuses_an_unknown_gremium() -> None:
    sess = fake_session(result(), result())
    with pytest.raises(ValidationProblem) as err:
        await BudgetTreeService(sess).create_node(
            BudgetNodeCreate(key="VS", name="VS", decisionGremiumId=uuid.uuid4())
        )
    assert err.value.code == "decision_gremium_invalid"


async def test_create_child_inherits_in_the_response() -> None:
    g = uuid.uuid4()
    parent = _budget(path_key="VS", key="VS")
    # Queue: the parent, the sibling check, then the ancestors of the parent.
    sess = fake_session(
        result(parent), result(), result("VS"), result((parent.id, None, g))
    )
    out = await BudgetTreeService(sess).create_node(
        BudgetNodeCreate(key="8", name="Ressort", parentId=parent.id)
    )
    assert out.decision_gremium_id is None
    assert (out.effective_decision_gremium_id, out.decision_gremium_source_id) == (
        g, parent.id,
    )


async def test_update_node_sets_and_clears_the_gremium() -> None:
    g = uuid.uuid4()
    node = _budget(path_key="VS", key="VS")
    # Queue: the node, the Gremium lookup.
    sess = fake_session(result(node), result(g))
    out = await BudgetTreeService(sess).update_node(
        node.id, BudgetNodeUpdate(decisionGremiumId=g)
    )
    assert node.decision_gremium_id == g
    assert out.effective_decision_gremium_id == g
    # null clears it; a top-level node then has no effective value.
    sess = fake_session(result(node))
    out = await BudgetTreeService(sess).update_node(
        node.id, BudgetNodeUpdate(decisionGremiumId=None)
    )
    assert node.decision_gremium_id is None
    assert (out.effective_decision_gremium_id, out.decision_gremium_source_id) == (None, None)


def _app_in(state_id: uuid.UUID | None) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(), current_state_id=state_id, budget_id=None, fiscal_year_id=None,
        vote_gremium_id=uuid.uuid4(),
    )


async def test_assign_budget_refused_in_a_budget_vote_state() -> None:
    state = State(kind="vote", config={"gremiumSource": "budget"})
    app = _app_in(uuid.uuid4())
    sess = fake_session(result(app))
    sess._gets = [state]  # noqa: SLF001 - the State lookup goes through `get`
    with pytest.raises(ConflictError) as err:
        await BudgetTreeService(sess).assign_budget(
            app.id, AssignBudgetRequest(budgetId=None)
        )
    assert err.value.code == "budget_locked_by_vote"


async def test_assign_budget_allowed_in_a_fixed_vote_state() -> None:
    state = State(kind="vote", config={"gremiumId": str(uuid.uuid4())})
    app = _app_in(uuid.uuid4())
    sess = fake_session(result(app))
    sess._gets = [state]  # noqa: SLF001
    out = await BudgetTreeService(sess).assign_budget(app.id, AssignBudgetRequest(budgetId=None))
    assert out.budget_id is None
