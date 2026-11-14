"""Haushaltsplan tools.

This group covers the plan switch and the steps of a budget,
and the plan of a fiscal year with its versions, lines and state changes.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api

group = ToolGroup()


@group.tool
async def set_plan_switch(budget_id: str, enabled: bool) -> dict:
    """Set the plan switch of a top-level cost center.

    On: each open fiscal year without a plan gets a draft from its allocations, and
    no allocation changes. Off: possible only while each plan is one draft, and it
    deletes those plans; otherwise 409 `plan_switch_has_plans`. Requires
    budget.structure.
    """
    return await api().put(f"/budgets/{budget_id}/plan-switch", json={"enabled": enabled})


@group.tool
async def get_plan_steps(budget_id: str) -> dict:
    """List the steps that a plan version of a budget passes before it is in force."""
    return await api().get(f"/budgets/{budget_id}/plan-steps")


@group.tool
async def set_plan_steps(budget_id: str, steps: list[S.PlanStep]) -> dict:
    """Replace the ordered steps of a budget, at most 10. The list can be empty.

    A version that left the draft keeps the steps it started with. Requires
    budget.structure.
    """
    return await api().put(
        f"/budgets/{budget_id}/plan-steps", json={"steps": [dump_create(s) for s in steps]}
    )


@group.tool
async def list_budget_years() -> list:
    """List the pairs of a budget and a fiscal year that a new booking can take.

    A booking, a transfer and the assignment of an application take a cost center
    only with a fiscal year of this list: not past, not closed, and with a plan in
    force when the budget has plans. Another year gives 422
    `fiscal_year_not_choosable`.
    """
    return await api().get("/budget-years")


@group.tool
async def get_budget_plan(budget_id: str, fiscal_year_id: str) -> dict:
    """Read the Haushaltsplan of a fiscal year with every version, its steps and lines.

    The call gives 404 `plan_not_found` for a year without a plan.
    """
    return await api().get(f"/budgets/{budget_id}/fiscal-years/{fiscal_year_id}/plan")


@group.tool
async def get_plan_of_version(version_id: str) -> dict:
    """Read the Haushaltsplan that a version belongs to, with every version.

    Use it with the `planVersionId` of a vote of a plan step. The call gives 404 for
    a version that does not exist and 403 without the view of the budget.
    """
    return await api().get(f"/budget-plan-versions/{version_id}/plan")


@group.tool
async def create_budget_plan(
    budget_id: str, fiscal_year_id: str, copy_from_fiscal_year_id: str | None = None
) -> dict:
    """Create the Haushaltsplan of a fiscal year with a Stammplan in draft.

    `copy_from_fiscal_year_id` starts it with the lines of the version in force of
    another year of the same budget. Requires budget.structure.
    """
    body = (
        {"copyFromFiscalYearId": copy_from_fiscal_year_id} if copy_from_fiscal_year_id else {}
    )
    return await api().post(f"/budgets/{budget_id}/fiscal-years/{fiscal_year_id}/plan", json=body)


@group.tool
async def create_plan_nachtrag(budget_id: str, fiscal_year_id: str) -> dict:
    """Add a Nachtrag in draft with a copy of the lines of the version in force.

    The call gives 409 `plan_draft_exists` while a version is not in force yet.
    Requires budget.structure.
    """
    return await api().post(f"/budgets/{budget_id}/fiscal-years/{fiscal_year_id}/plan/versions")


@group.tool
async def delete_plan_version(version_id: str) -> dict:
    """Delete a draft version, and the plan with it when it has no other version.

    Requires budget.structure.
    """
    return await api().delete(f"/budget-plan-versions/{version_id}")


@group.tool
async def set_plan_line(version_id: str, budget_id: str, line: S.PlanLineSet) -> dict:
    """Set the line of one cost center in a draft version.

    A field that you leave out keeps its value. A line makes the cost center part of the
    plan of that year. `side` sets the side of a Titel, a direct child of the top-level
    cost center; any other line gives 422 `side_not_settable`. A cost center with a
    child line holds the sum of its children. The first child line of a parent takes the
    Ansatz of the parent when you give no amount above 0. The call gives 422
    `plan_amount_too_large` when a sum of Ansätze passes 9,999,999,999.99. Requires
    budget.structure.
    """
    return await api().put(
        f"/budget-plan-versions/{version_id}/lines/{budget_id}", json=dump_patch(line)
    )


@group.tool
async def rename_plan_line(version_id: str, budget_id: str, rename: S.PlanLineRename) -> dict:
    """Give a cost center a new name or key in a draft version.

    In a budget with a plan, this is the only way to change them below the top level.
    The draft shows the new values. Every other place shows the old ones until the
    version is in force. A field that you leave out keeps its value. The call gives 409
    `plan_version_locked` for a version that is not a draft and 409 `budget_key_exists`
    for a key that a sibling has or takes in the draft. Requires budget.structure.
    """
    return await api().put(
        f"/budget-plan-versions/{version_id}/lines/{budget_id}/name", json=dump_patch(rename)
    )


@group.tool
async def delete_plan_line(version_id: str, budget_id: str) -> dict:
    """Remove the line of one cost center from a draft version.

    The call gives 422 `plan_line_has_children` while a child has a line. Requires
    budget.structure.
    """
    return await api().delete(f"/budget-plan-versions/{version_id}/lines/{budget_id}")


@group.tool
async def create_plan_cost_centre(version_id: str, node: S.PlanNodeCreate) -> dict:
    """Create a cost center and its line in a draft version. Requires budget.structure."""
    return await api().post(
        f"/budget-plan-versions/{version_id}/cost-centres", json=dump_create(node)
    )


@group.tool
async def pass_plan_step(version_id: str, step: int | None = None) -> dict:
    """Record the next step of a version as passed.

    `step` names the step that you mean, by its place in the list from 0. Give it, so
    a repeated call does not pass the step after it: the call then gives 409
    `plan_step_not_next`. The first step needs a version with a line (422
    `plan_empty`) in which every Titel has a side (422 `plan_side_missing`), that is
    balanced (422 `plan_not_balanced`) and whose side sums the
    platform can hold (422 `plan_amount_too_large`), and takes it out of the draft.
    The call gives 409 `plan_step_has_vote` while the step has a vote that is
    not cancelled, 409 `plan_not_enabled` while the plan switch of the budget is off
    and 409 `fiscal_year_closed` for a closed year. Requires budget.structure.
    """
    return await api().post(
        f"/budget-plan-versions/{version_id}/steps/next",
        json={"step": step} if step is not None else None,
    )


@group.tool
async def request_plan_step(version_id: str) -> dict:
    """Ask the Gremium of the next step for its decision.

    The call creates no vote. The version then waits for a meeting of that Gremium:
    `list_assignable_agenda_plans` shows it, `add_agenda_item` with `plan_version_id`
    puts it on the agenda, and `create_meeting_vote` on that item is the vote. An
    accepted vote passes the step, every other result sends the version back to the
    draft. 422 `plan_step_no_gremium` for a step without a Gremium, 409
    `plan_step_waits` when the step already waits. Requires budget.structure.
    """
    return await api().post(f"/budget-plan-versions/{version_id}/steps/next/request")


@group.tool
async def set_plan_state(version_id: str, state: Literal["in_force", "draft"]) -> dict:
    """Bring a version into force, or move a version in progress back to draft.

    In force needs every step passed and a version with a line (422 `plan_empty`), and
    it writes the allocations of the year. Back to draft drops the passed steps,
    deletes a draft vote of the version and cancels an open one. The call gives 409
    `plan_not_enabled` while the plan switch of the budget is off. Requires
    budget.structure.
    """
    return await api().post(f"/budget-plan-versions/{version_id}/state", json={"state": state})


def register(mcp: FastMCP) -> None:
    """Register the Haushaltsplan tool group."""
    group.register(mcp)
