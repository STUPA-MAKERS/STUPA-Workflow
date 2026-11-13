"""Router tests for the Haushaltsplan: endpoint wiring without a DB.

A fake service stands in for `BudgetTreeService`. The integration suite covers the
database paths.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.budget.plan_schemas import (
    PlanLineOut,
    PlanOut,
    PlanStepsOut,
    PlanSwitchOut,
    PlanSwitchPreview,
    PlanVersionOut,
    SideOut,
)
from app.modules.budget.tree_router import get_budget_tree_service

_TOP = uuid.uuid4()
_NODE = uuid.uuid4()
_FY = uuid.uuid4()
_VERSION = uuid.uuid4()


def _plan() -> PlanOut:
    return PlanOut(
        id=uuid.uuid4(),
        budgetId=_TOP,
        fiscalYearId=_FY,
        versions=(
            PlanVersionOut(
                id=_VERSION,
                number=0,
                state="draft",
                createdAt=datetime(2026, 11, 12, tzinfo=UTC),
                lines=(PlanLineOut(budgetId=_NODE, amount=Decimal("10.00")),),
            ),
        ),
    )


class _Tx:
    """Stands in for the transaction of the service: it counts the commits."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _FakePlans:
    def __init__(self, *, visible: bool = True) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.session = _Tx()
        self.visible = visible

    async def can_view_node(self, budget_id: uuid.UUID, member: object) -> bool:
        return self.visible

    async def set_side(self, budget_id: uuid.UUID, side: str) -> SideOut:
        self.calls.append(("side", side))
        return SideOut(budgetId=budget_id, side="income")

    async def set_plan_switch(
        self, budget_id: uuid.UUID, enabled: bool, *, confirm_changes: bool
    ) -> PlanSwitchOut:
        self.calls.append(("switch", (enabled, confirm_changes)))
        return PlanSwitchOut(budgetId=budget_id, planEnabled=enabled)

    async def preview_plan_switch(
        self, budget_id: uuid.UUID, sides: dict[uuid.UUID, str] | None = None
    ) -> PlanSwitchPreview:
        self.calls.append(("preview", budget_id))
        self.calls.append(("preview_sides", sides))
        return PlanSwitchPreview(budgetId=budget_id)

    async def delete_version(self, version_id: uuid.UUID) -> None:
        self.calls.append(("delete_version", version_id))

    async def get_plan(self, budget_id: uuid.UUID, fiscal_year_id: uuid.UUID) -> PlanOut:
        self.calls.append(("get", fiscal_year_id))
        return _plan()

    async def plan_of_version(self, version_id: uuid.UUID) -> PlanOut:
        self.calls.append(("of_version", version_id))
        return _plan()

    async def create_plan(self, budget_id: uuid.UUID, fy: uuid.UUID, payload: Any) -> PlanOut:
        self.calls.append(("create", payload.copy_from_fiscal_year_id))
        return _plan()

    async def create_nachtrag(self, budget_id: uuid.UUID, fy: uuid.UUID) -> PlanOut:
        self.calls.append(("nachtrag", fy))
        return _plan()

    async def set_line(self, version_id: uuid.UUID, budget_id: uuid.UUID, payload: Any) -> PlanOut:
        self.calls.append(("line", payload.amount))
        return _plan()

    async def delete_line(self, version_id: uuid.UUID, budget_id: uuid.UUID) -> PlanOut:
        self.calls.append(("delete_line", budget_id))
        return _plan()

    async def set_plan_state(self, version_id: uuid.UUID, payload: Any) -> PlanOut:
        self.calls.append(("state", payload.state))
        return _plan()


    async def get_plan_steps(self, budget_id: uuid.UUID) -> PlanStepsOut:
        self.calls.append(("steps", budget_id))
        return PlanStepsOut(budgetId=budget_id)

    async def set_plan_steps(self, budget_id: uuid.UUID, payload: Any) -> PlanStepsOut:
        self.calls.append(("set_steps", tuple(step.name for step in payload.steps)))
        return PlanStepsOut(budgetId=budget_id)

    async def pass_next_step(
        self, version_id: uuid.UUID, *, expected: int | None = None
    ) -> PlanOut:
        self.calls.append(("next", version_id if expected is None else (version_id, expected)))
        return _plan()

    async def create_step_vote(self, version_id: uuid.UUID) -> PlanOut:
        self.calls.append(("vote", version_id))
        return _plan()

    async def create_plan_node(self, version_id: uuid.UUID, payload: Any) -> PlanOut:
        self.calls.append(("node", payload.key))
        return _plan()


def _client(fake: _FakePlans, *permissions: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_budget_tree_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions=set(permissions)
    )
    app.dependency_overrides[get_current_applicant] = lambda: None
    return TestClient(app)


@pytest.fixture
def fake() -> _FakePlans:
    return _FakePlans()


@pytest.fixture
def client(fake: _FakePlans) -> TestClient:
    return _client(fake, "budget.structure")


_WRITES: tuple[tuple[str, str, dict[str, Any] | None, tuple[str, Any]], ...] = (
    ("PUT", f"/api/budgets/{_NODE}/side", {"side": "income"}, ("side", "income")),
    ("PUT", f"/api/budgets/{_TOP}/plan-switch", {"enabled": True}, ("switch", (True, False))),
    ("PUT", f"/api/budgets/{_TOP}/plan-switch", {"enabled": True, "confirmChanges": True},
     ("switch", (True, True))),
    ("DELETE", f"/api/budget-plan-versions/{_VERSION}", None, ("delete_version", _VERSION)),
    ("POST", f"/api/budgets/{_TOP}/fiscal-years/{_FY}/plan", {}, ("create", None)),
    ("POST", f"/api/budgets/{_TOP}/fiscal-years/{_FY}/plan/versions", None, ("nachtrag", _FY)),
    (
        "PUT",
        f"/api/budget-plan-versions/{_VERSION}/lines/{_NODE}",
        {"amount": "10.00"},
        ("line", Decimal("10.00")),
    ),
    ("DELETE", f"/api/budget-plan-versions/{_VERSION}/lines/{_NODE}", None, ("delete_line", _NODE)),
    ("POST", f"/api/budget-plan-versions/{_VERSION}/state", {"state": "in_force"},
     ("state", "in_force")),
    ("PUT", f"/api/budgets/{_TOP}/plan-steps", {"steps": [{"name": "Beschluss"}]},
     ("set_steps", ("Beschluss",))),
    ("POST", f"/api/budget-plan-versions/{_VERSION}/steps/next", None, ("next", _VERSION)),
    ("POST", f"/api/budget-plan-versions/{_VERSION}/steps/next/vote", None, ("vote", _VERSION)),
    ("POST", f"/api/budget-plan-versions/{_VERSION}/cost-centres",
     {"parentId": str(_TOP), "key": "9", "name": "Sport"}, ("node", "9")),
)


@pytest.mark.parametrize(("method", "url", "body", "call"), _WRITES)
def test_write_route_calls_the_service_and_commits(
    client: TestClient,
    fake: _FakePlans,
    method: str,
    url: str,
    body: dict[str, Any] | None,
    call: tuple[str, Any],
) -> None:
    resp = client.request(method, url, json=body)
    assert resp.status_code in (200, 201, 204), resp.text
    assert fake.calls == [call]
    assert fake.session.commits == 1


@pytest.mark.parametrize(("method", "url", "body", "call"), _WRITES)
def test_write_route_needs_budget_structure(
    method: str, url: str, body: dict[str, Any] | None, call: tuple[str, Any]
) -> None:
    """§F/finance/budget/000800: each plan write needs budget.structure."""
    fake = _FakePlans()
    resp = _client(fake, "budget.view", "budget.book").request(method, url, json=body)
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert fake.calls == []
    assert fake.session.commits == 0


def test_preview_of_the_plan_switch(client: TestClient, fake: _FakePlans) -> None:
    """The preview route returns the allocations that the switch changes.

    Rule: §F/finance/budget/000803.
    """
    resp = client.get(f"/api/budgets/{_TOP}/plan-switch/preview")
    assert resp.status_code == 200
    assert resp.json() == {"budgetId": str(_TOP), "changes": []}
    assert fake.calls == [("preview", _TOP), ("preview_sides", {})]
    assert (fake.session.commits, fake.session.rollbacks) == (0, 1)
    child, other = uuid.uuid4(), uuid.uuid4()
    client.get(
        f"/api/budgets/{_TOP}/plan-switch/preview", params={"income": child, "expense": other}
    )
    assert fake.calls[-1] == ("preview_sides", {child: "income", other: "expense"})
    denied = _client(_FakePlans(), "budget.view").get(f"/api/budgets/{_TOP}/plan-switch/preview")
    assert denied.status_code == 403


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("PUT", f"/api/budgets/{_TOP}/plan-switch", {"enabled": True, "bogus": 1}),
        ("PUT", f"/api/budgets/{_TOP}/plan-steps", {"steps": [{"name": "A", "junk": True}]}),
        ("PUT", f"/api/budgets/{_TOP}/plan-steps", {"steps": [{"name": "   "}]}),
        ("POST", f"/api/budgets/{_TOP}/fiscal-years/{_FY}/plan", {"extra": "x"}),
        ("PUT", f"/api/budget-plan-versions/{_VERSION}/lines/{_NODE}", {"amount": "1", "z": 1}),
    ],
)
def test_a_plan_input_refuses_unknown_fields_and_blank_names(
    client: TestClient, fake: _FakePlans, method: str, url: str, body: dict[str, Any]
) -> None:
    """An input schema refuses unknown fields.

    Rules: §S/shared/api/000040, §F/finance/budget/000823.
    """
    resp = client.request(method, url, json=body)
    assert resp.status_code == 422
    assert fake.calls == []


def test_a_line_amount_has_two_decimal_places(client: TestClient, fake: _FakePlans) -> None:
    resp = client.put(
        f"/api/budget-plan-versions/{_VERSION}/lines/{_NODE}", json={"amount": "1E+3"}
    )
    assert resp.status_code == 200
    assert str(fake.calls[0][1]) == "1000.00"


def test_get_plan_with_the_full_view() -> None:
    fake = _FakePlans(visible=False)
    resp = _client(fake, "budget.view").get(f"/api/budgets/{_TOP}/fiscal-years/{_FY}/plan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["fiscalYearId"] == str(_FY)
    assert body["versions"][0]["lines"][0] == {
        "budgetId": str(_NODE), "amount": "10.00", "note": None, "name": None,
        "pathKey": None, "transferable": False, "coverable": False, "blocked": "0",
    }
    assert fake.session.commits == 0


def test_get_plan_steps() -> None:
    fake = _FakePlans()
    resp = _client(fake, "budget.view").get(f"/api/budgets/{_TOP}/plan-steps")
    assert resp.status_code == 200
    assert resp.json() == {"budgetId": str(_TOP), "steps": []}
    assert fake.calls == [("steps", _TOP)]


def test_get_plan_follows_the_read_rule_of_the_cost_centre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§F/finance/budget/000800: a read follows the read rule of the Kostenstelle."""

    async def _no_gremien(_service: object, _sub: str) -> set[uuid.UUID]:
        return set()

    monkeypatch.setattr("app.modules.budget.tree_router._member_gremium_ids", _no_gremien)
    url = f"/api/budgets/{_TOP}/fiscal-years/{_FY}/plan"
    assert _client(_FakePlans(visible=True)).get(url).status_code == 200
    denied = _client(_FakePlans(visible=False)).get(url)
    assert denied.status_code == 403


def test_the_plan_of_a_version_follows_the_read_rule_of_its_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read by version follows the read rule of the budget of the plan.

    Rule: §F/finance/budget/000800.
    """

    async def _no_gremien(_service: object, _sub: str) -> set[uuid.UUID]:
        return set()

    monkeypatch.setattr("app.modules.budget.tree_router._member_gremium_ids", _no_gremien)
    url = f"/api/budget-plan-versions/{_VERSION}/plan"
    shown = _client(_FakePlans(visible=True)).get(url)
    assert (shown.status_code, shown.json()["budgetId"]) == (200, str(_TOP))
    assert _client(_FakePlans(visible=False)).get(url).status_code == 403


def test_line_amount_is_validated(client: TestClient, fake: _FakePlans) -> None:
    url = f"/api/budget-plan-versions/{_VERSION}/lines/{_NODE}"
    for amount in ("-1", "99999999999.00", "1.234"):
        assert client.put(url, json={"amount": amount}).status_code == 422
    assert client.post(
        f"/api/budget-plan-versions/{_VERSION}/state", json={"state": "nope"}
    ).status_code == 422
    assert fake.calls == []


def test_the_step_route_passes_the_named_step(client: TestClient, fake: _FakePlans) -> None:
    """Rule: §F/finance/budget/000841."""
    resp = client.post(f"/api/budget-plan-versions/{_VERSION}/steps/next", json={"step": 1})
    assert resp.status_code == 200
    assert ("next", (_VERSION, 1)) in fake.calls
    assert (
        client.post(
            f"/api/budget-plan-versions/{_VERSION}/steps/next", json={"step": -1}
        ).status_code
        == 422
    )


def test_the_steps_route_needs_its_list(client: TestClient) -> None:
    """A body without `steps` must not empty the list of a budget.

    Rule: §F/finance/budget/000824.
    """
    assert client.put(f"/api/budgets/{_TOP}/plan-steps", json={}).status_code == 422


def test_the_node_schemas_refuse_what_they_cannot_store() -> None:
    """Rules: §F/finance/budget/000246, §F/finance/budget/000831."""
    from pydantic import ValidationError

    from app.modules.budget.plan_schemas import PlanLineSet
    from app.modules.budget.tree_schemas import BudgetNodeCreate, BudgetNodeUpdate

    for body in (
        {"name": None},
        {"active": None},
        {"key": None},
        {"fiscalStartDay": None},
        {"name": "   "},
        {"name": "x", "unknown": 1},
    ):
        with pytest.raises(ValidationError):
            BudgetNodeUpdate.model_validate(body)
    assert BudgetNodeUpdate.model_validate({"name": "  Sport "}).name == "Sport"
    assert BudgetNodeUpdate.model_validate({"color": None}).color is None
    with pytest.raises(ValidationError):
        BudgetNodeUpdate.model_validate([])
    with pytest.raises(ValidationError):
        BudgetNodeCreate.model_validate({"key": "1", "name": " "})
    with pytest.raises(ValidationError):
        PlanLineSet.model_validate({"transferable": "yes"})


def test_an_amount_of_minus_zero_is_zero() -> None:
    """An amount of "-0" has no sign in the answer and in the audit entry.

    Rule: §F/finance/budget/000794.
    """
    from app.modules.budget.plan_schemas import PlanLineSet

    line = PlanLineSet.model_validate({"amount": "-0", "blocked": "-0.00"})
    assert (str(line.amount), str(line.blocked)) == ("0.00", "0.00")
    assert str(PlanLineSet.model_validate({"amount": "7"}).amount) == "7.00"


@pytest.mark.parametrize("name", ["​", " ​  ", "⁠﻿"])
def test_a_name_needs_a_visible_character(name: str) -> None:
    """A name of zero-width characters is empty for a reader.

    Rules: §F/finance/budget/000823, §F/finance/budget/000831.
    """
    from pydantic import ValidationError

    from app.modules.budget.plan_schemas import PlanStepIn
    from app.modules.budget.tree_schemas import BudgetNodeUpdate

    with pytest.raises(ValidationError):
        PlanStepIn(name=name)
    with pytest.raises(ValidationError):
        BudgetNodeUpdate(name=name)
    assert PlanStepIn(name=" Beschluss​ ").name == "Beschluss​"
