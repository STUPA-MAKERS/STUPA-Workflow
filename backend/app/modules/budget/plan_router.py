"""Haushaltsplan API router, principal-only and fail-closed.

A read follows the read rule of the cost center: the full budget view or the gremium
scope of the top-level node. Each write needs ``budget.structure``. A write in a
closed fiscal year gives 409 ``fiscal_year_closed``. The service methods do not
commit, so each write route commits after the method returns.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.deps import Principal, require_principal
from app.modules.budget.plan_schemas import (
    PlanCreate,
    PlanLineSet,
    PlanOut,
    PlanStateSet,
    PlanSwitchOut,
    PlanSwitchSet,
    SideOut,
    SideSet,
)
from app.modules.budget.tree_router import ServiceDep, _errors, _require_node_view

router = APIRouter(tags=["budget"])

_STRUCTURE = [Depends(require_principal("budget.structure"))]


@router.put(
    "/budgets/{budget_id}/side",
    response_model=SideOut,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 409, 422),
)
async def set_side(budget_id: UUID, payload: SideSet, service: ServiceDep) -> SideOut:
    """Set the side of a direct child of a top-level cost center and of its subtree."""
    out = await service.set_side(budget_id, payload.side)
    await service.session.commit()
    return out


@router.put(
    "/budgets/{budget_id}/plan-switch",
    response_model=PlanSwitchOut,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 422),
)
async def set_plan_switch(
    budget_id: UUID, payload: PlanSwitchSet, service: ServiceDep
) -> PlanSwitchOut:
    """Set the plan switch of a top-level cost center.

    When the switch goes on, each open fiscal year without a plan gets a Stammplan in
    force from its allocations.
    """
    out = await service.set_plan_switch(budget_id, payload.enabled)
    await service.session.commit()
    return out


@router.get(
    "/budgets/{budget_id}/fiscal-years/{fiscal_year_id}/plan",
    response_model=PlanOut,
    responses=_errors(401, 403, 404, 422),
)
async def get_plan(
    budget_id: UUID,
    fiscal_year_id: UUID,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> PlanOut:
    """Return the Haushaltsplan of a fiscal year with every version and its lines."""
    await _require_node_view(service, principal, budget_id)
    return await service.get_plan(budget_id, fiscal_year_id)


@router.post(
    "/budgets/{budget_id}/fiscal-years/{fiscal_year_id}/plan",
    response_model=PlanOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 409, 422),
)
async def create_plan(
    budget_id: UUID, fiscal_year_id: UUID, payload: PlanCreate, service: ServiceDep
) -> PlanOut:
    """Create the Haushaltsplan of a fiscal year with a Stammplan in draft."""
    out = await service.create_plan(budget_id, fiscal_year_id, payload)
    await service.session.commit()
    return out


@router.post(
    "/budgets/{budget_id}/fiscal-years/{fiscal_year_id}/plan/versions",
    response_model=PlanOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 409, 422),
)
async def create_nachtrag(budget_id: UUID, fiscal_year_id: UUID, service: ServiceDep) -> PlanOut:
    """Add a Nachtrag in draft with a copy of the lines of the version in force."""
    out = await service.create_nachtrag(budget_id, fiscal_year_id)
    await service.session.commit()
    return out


@router.put(
    "/budget-plan-versions/{version_id}/lines/{budget_id}",
    response_model=PlanOut,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 409, 422),
)
async def set_plan_line(
    version_id: UUID, budget_id: UUID, payload: PlanLineSet, service: ServiceDep
) -> PlanOut:
    """Set the line of one cost center in a draft version."""
    out = await service.set_line(version_id, budget_id, payload)
    await service.session.commit()
    return out


@router.delete(
    "/budget-plan-versions/{version_id}/lines/{budget_id}",
    response_model=PlanOut,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 409, 422),
)
async def delete_plan_line(version_id: UUID, budget_id: UUID, service: ServiceDep) -> PlanOut:
    """Remove the line of one cost center from a draft version."""
    out = await service.delete_line(version_id, budget_id)
    await service.session.commit()
    return out


@router.post(
    "/budget-plan-versions/{version_id}/state",
    response_model=PlanOut,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 409, 422),
)
async def set_plan_state(version_id: UUID, payload: PlanStateSet, service: ServiceDep) -> PlanOut:
    """Move a version one step forward, or a resolved version back to draft."""
    out = await service.set_plan_state(version_id, payload)
    await service.session.commit()
    return out
