"""Tests for the Haushaltsplan tools.

Each tool must call the correct plan route with the correct method and body.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tools import _common, budget, budget_plan, register_all


class _FakeApi:
    """Record each call and answer with a fixed body."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def _call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append((method, path, kw.get("json")))
        return {"status": "ok"}

    async def get(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("GET", path, **kw)

    async def put(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("PUT", path, **kw)

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("POST", path, **kw)

    async def delete(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("DELETE", path, **kw)


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_plan_tools_are_registered() -> None:
    server = FastMCP("test")
    register_all(server)
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert {
        "set_plan_switch",
        "get_plan_steps",
        "set_plan_steps",
        "get_budget_plan",
        "create_budget_plan",
        "create_plan_nachtrag",
        "delete_plan_version",
        "set_plan_line",
        "delete_plan_line",
        "create_plan_cost_centre",
        "pass_plan_step",
        "request_plan_step",
        "set_plan_state",
    } <= names


def test_each_plan_tool_calls_its_route(fake_api: _FakeApi) -> None:
    calls = (
        budget_plan.set_plan_switch("b1", True),
        budget_plan.get_plan_steps("b1"),
        budget_plan.set_plan_steps("b1", [S.PlanStep(name="Beschluss", gremiumId="g1")]),
        budget_plan.get_budget_plan("b1", "fy1"),
        budget_plan.create_budget_plan("b1", "fy1"),
        budget_plan.create_budget_plan("b1", "fy1", copy_from_fiscal_year_id="fy0"),
        budget_plan.create_plan_nachtrag("b1", "fy1"),
        budget_plan.delete_plan_version("v1"),
        budget_plan.set_plan_line("v1", "n1", S.PlanLineSet(amount="10.00", side="income")),
        budget_plan.delete_plan_line("v1", "n1"),
        budget_plan.create_plan_cost_centre(
            "v1", S.PlanNodeCreate(parentId="b1", key="9", name="Sport", side="expense")
        ),
        budget_plan.pass_plan_step("v1"),
        budget_plan.request_plan_step("v1"),
        budget_plan.set_plan_state("v1", "in_force"),
    )
    for call in calls:
        asyncio.run(call)
    assert fake_api.calls == [
        ("PUT", "/budgets/b1/plan-switch", {"enabled": True}),
        ("GET", "/budgets/b1/plan-steps", None),
        ("PUT", "/budgets/b1/plan-steps", {"steps": [{"name": "Beschluss", "gremiumId": "g1"}]}),
        ("GET", "/budgets/b1/fiscal-years/fy1/plan", None),
        ("POST", "/budgets/b1/fiscal-years/fy1/plan", {}),
        ("POST", "/budgets/b1/fiscal-years/fy1/plan", {"copyFromFiscalYearId": "fy0"}),
        ("POST", "/budgets/b1/fiscal-years/fy1/plan/versions", None),
        ("DELETE", "/budget-plan-versions/v1", None),
        ("PUT", "/budget-plan-versions/v1/lines/n1", {"side": "income", "amount": "10.00"}),
        ("DELETE", "/budget-plan-versions/v1/lines/n1", None),
        (
            "POST",
            "/budget-plan-versions/v1/cost-centres",
            {"parentId": "b1", "key": "9", "name": "Sport", "side": "expense", "amount": "0"},
        ),
        ("POST", "/budget-plan-versions/v1/steps/next", None),
        ("POST", "/budget-plan-versions/v1/steps/next/request", None),
        ("POST", "/budget-plan-versions/v1/state", {"state": "in_force"}),
    ]


def test_a_step_is_named_and_a_vote_finds_its_plan(fake_api: _FakeApi) -> None:
    """Rules: §F/finance/budget/000838, §F/finance/budget/000841."""
    asyncio.run(budget_plan.pass_plan_step("v1", step=1))
    asyncio.run(budget_plan.get_plan_of_version("v1"))
    assert fake_api.calls == [
        ("POST", "/budget-plan-versions/v1/steps/next", {"step": 1}),
        ("GET", "/budget-plan-versions/v1/plan", None),
    ]


def test_a_fiscal_year_closes_reopens_and_goes(fake_api: _FakeApi) -> None:
    """Rule: §F/finance/budget/000836."""
    asyncio.run(budget.close_fiscal_year("b1", "fy1"))
    asyncio.run(budget.reopen_fiscal_year("b1", "fy1"))
    asyncio.run(budget.delete_fiscal_year("b1", "fy1"))
    assert fake_api.calls == [
        ("POST", "/budgets/b1/fiscal-years/fy1/close", None),
        ("POST", "/budgets/b1/fiscal-years/fy1/reopen", None),
        ("DELETE", "/budgets/b1/fiscal-years/fy1", None),
    ]
