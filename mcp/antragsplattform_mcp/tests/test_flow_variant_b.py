"""Tests for the flow keys of variant B and the deciding Gremium of a cost center.

The flow tools pass the new keys to the server unchanged: a vote state with
`gremiumSource: "budget"`, `addToNextSession` without `gremiumId`, the recipient kinds
`voteGremium` and `budgetGremium`, the guards `isInVoteGremium` and
`budgetHasDecisionGremium`, and the actions `assignBudgetFromApplicantGremium` and
`assignBudgetFromMap`. The budget tools write `decisionGremiumId`.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import pytest
from pydantic import ValidationError

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tools import _common, budget, flow_forms

_G = "11111111-1111-1111-1111-111111111111"
_B = "22222222-2222-2222-2222-222222222222"

_BASE_GRAPH: dict[str, Any] = {
    "states": [
        {"key": "draft", "label": {"de": "Entwurf"}, "isInitial": True},
        {"key": "hhb", "label": {"de": "HHB"}},
    ],
    "transitions": [{"from": "draft", "to": "hhb"}],
    "layout": {},
}


class _FakeApi:
    """Serve one flow graph and record every write."""

    def __init__(self) -> None:
        self.graph = copy.deepcopy(_BASE_GRAPH)
        self.posts: list[tuple[str, Any]] = []
        self.patches: list[tuple[str, Any]] = []

    async def get(self, path: str, **_kw: Any) -> Any:
        assert path == "/admin/flow-versions/global"
        return copy.deepcopy(self.graph)

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        self.posts.append((path, kw.get("json")))
        return {"id": "v1"}

    async def patch(self, path: str, **kw: Any) -> dict[str, Any]:
        self.patches.append((path, kw.get("json")))
        return {"id": "b1"}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def _saved_graph(fake: _FakeApi) -> dict[str, Any]:
    path, body = fake.posts[-1]
    assert path == "/admin/flow-versions/global"
    return body["graph"]


def test_vote_state_with_budget_source_passes_through(fake_api: _FakeApi) -> None:
    state = S.StateDef(
        key="gremium_vote",
        label={"de": "Gremium-Abstimmung"},
        kind="vote",
        config={"gremiumSource": "budget"},
    )
    asyncio.run(flow_forms.flow_add_state(state))
    added = _saved_graph(fake_api)["states"][-1]
    assert added["kind"] == "vote"
    assert added["config"] == {"gremiumSource": "budget"}


def test_vote_state_with_fixed_gremium_still_works() -> None:
    state = S.StateDef(key="v", label={"de": "V"}, kind="vote", config={"gremiumId": _G})
    assert S.dump_create(state)["config"] == {"gremiumId": _G}


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"gremiumId": _G, "gremiumSource": "budget"},
        {"gremiumSource": "applicant"},
        {"gremiumId": ""},
    ],
)
def test_vote_state_needs_exactly_one_gremium_key(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        S.StateDef(key="v", label={"de": "V"}, kind="vote", config=config)


def test_normal_state_ignores_the_gremium_rule() -> None:
    state = S.StateDef(key="n", label={"de": "N"})
    assert S.dump_create(state)["config"] == {}


def test_state_patch_with_budget_source(fake_api: _FakeApi) -> None:
    patch = S.StateDefPatch(kind="vote", config={"gremiumSource": "budget"})
    asyncio.run(flow_forms.flow_update_state("hhb", patch))
    state = _saved_graph(fake_api)["states"][1]
    assert state["kind"] == "vote"
    assert state["config"] == {"gremiumSource": "budget"}


def test_state_patch_refuses_unknown_source() -> None:
    with pytest.raises(ValidationError):
        S.StateDefPatch(config={"gremiumSource": "applicant"})


def test_transition_with_new_guards_and_actions_passes_through(fake_api: _FakeApi) -> None:
    guard = {
        "and": [
            {"budgetHasDecisionGremium": True},
            {"isInVoteGremium": True},
        ]
    }
    actions = [
        {"type": "addToNextSession"},
        {"type": "notify", "recipients": [{"kind": "voteGremium"}, {"kind": "budgetGremium"}]},
        {"type": "assignBudgetFromApplicantGremium", "parentId": _B},
        {"type": "assignBudgetFromMap", "field": "we", "map": {"winter": _B}},
    ]
    transition = S.TransitionDef.model_validate(
        {"from": "hhb", "to": "draft", "guard": guard, "actions": actions}
    )
    asyncio.run(flow_forms.flow_add_transition(transition))
    added = _saved_graph(fake_api)["transitions"][-1]
    assert added["guard"] == guard
    assert added["actions"] == actions


def test_transition_patch_replaces_actions(fake_api: _FakeApi) -> None:
    patch = S.TransitionDefPatch(actions=[{"type": "addToNextSession"}])
    asyncio.run(flow_forms.flow_update_transition(0, patch))
    assert _saved_graph(fake_api)["transitions"][0]["actions"] == [
        {"type": "addToNextSession"}
    ]


def test_set_global_flow_passes_graph_unchanged(fake_api: _FakeApi) -> None:
    graph = copy.deepcopy(_BASE_GRAPH)
    graph["states"][1]["kind"] = "vote"
    graph["states"][1]["config"] = {"gremiumSource": "budget"}
    asyncio.run(flow_forms.set_global_flow(graph))
    assert fake_api.posts == [
        ("/admin/flow-versions/global", {"graph": graph, "activate": True})
    ]


def test_update_budget_sets_and_clears_decision_gremium(fake_api: _FakeApi) -> None:
    asyncio.run(budget.update_budget("b1", S.BudgetNodeUpdate(decisionGremiumId=_G)))
    asyncio.run(budget.update_budget("b1", S.BudgetNodeUpdate(decisionGremiumId=None)))
    assert fake_api.patches == [
        ("/budgets/b1", {"decisionGremiumId": _G}),
        ("/budgets/b1", {"decisionGremiumId": None}),
    ]


def test_update_budget_leaves_decision_gremium_unset(fake_api: _FakeApi) -> None:
    asyncio.run(budget.update_budget("b1", S.BudgetNodeUpdate(name="X")))
    assert fake_api.patches == [("/budgets/b1", {"name": "X"})]


def test_create_budget_with_decision_gremium(fake_api: _FakeApi) -> None:
    node = S.BudgetNodeCreate(key="k", name="K", parentId=_B, decisionGremiumId=_G)
    asyncio.run(budget.create_budget(node))
    path, body = fake_api.posts[-1]
    assert path == "/budgets"
    assert body["decisionGremiumId"] == _G
    assert body["parentId"] == _B
