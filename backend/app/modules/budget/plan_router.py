"""Haushaltsplan API router, principal-only and fail-closed.

A read follows the read rule of the cost center: the full budget view or the gremium
scope of the top-level node. Each write needs ``budget.structure``. A write in a
closed fiscal year gives 409 ``fiscal_year_closed``. The service methods do not
commit, so each write route commits after the method returns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.deps import Principal, SettingsDep, require_principal
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget import plan_export
from app.modules.budget.plan_export import PlanExport
from app.modules.budget.plan_schemas import (
    PlanCreate,
    PlanLineRename,
    PlanLineSet,
    PlanNodeCreate,
    PlanOut,
    PlanStateByHand,
    PlanStateSet,
    PlanStepPass,
    PlanStepsOut,
    PlanStepsSet,
    PlanSwitchOut,
    PlanSwitchSet,
)
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_router import ServiceDep, _errors, _require_node_view
from app.modules.pdf.typst_client import TypstError, build_typst_client
from app.modules.site_config.export_logo import (
    active_export_logo,
    export_render_assets,
    export_render_config,
)
from app.shared.errors import BadRequestError, ServiceUnavailableError
from app.shared.filenames import content_disposition
from app.shared.xlsx import XLSX_MEDIA_TYPE, build_table_workbook

router = APIRouter(tags=["budget"])

_STRUCTURE = [Depends(require_principal("budget.structure"))]
_SET_STATE = [Depends(require_principal("budget.plan.set_state"))]


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

    When the switch goes on, each open fiscal year without a plan gets a draft from its
    allocations.
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


@router.get(
    "/budget-plan-versions/{version_id}/plan",
    response_model=PlanOut,
    responses=_errors(401, 403, 404, 422),
)
async def get_plan_of_version(
    version_id: UUID,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> PlanOut:
    """Return the Haushaltsplan that holds a version, under the read rule of its budget."""
    out = await service.plan_of_version(version_id)
    await _require_node_view(service, principal, out.budget_id)
    return out


async def _export_of(
    service: BudgetTreeService, principal: Principal, version_id: UUID, extension: str
) -> PlanExport:
    """Read a version for a file under the read rule of its budget, and record the export."""
    plan = await service.plan_of_version(version_id)
    await _require_node_view(service, principal, plan.budget_id)
    export = await service.plan_export(version_id, datetime.now(UTC).date())
    await audit_record(
        service.session,
        actor=principal.sub,
        action=AuditAction.EXPORT,
        target_type="export",
        target_id=f"haushaltsplan.{extension}",
        data={"plan_version_id": str(version_id), "state": export.head.state},
    )
    await service.session.commit()
    return export


@router.get(
    "/budget-plan-versions/{version_id}/export.xlsx",
    responses=_errors(401, 403, 404),
)
async def export_plan_xlsx(
    version_id: UUID,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> Response:
    """Return a version of a Haushaltsplan as `.xlsx`, for each reader of the plan.

    Rule: §F/finance/budget/000875.
    """
    export = await _export_of(service, principal, version_id, "xlsx")
    rows = plan_export.sheet_rows(export)
    data = build_table_workbook(
        title=export.head.title,
        head=plan_export.head_lines(export.head),
        headers=plan_export.sheet_headers(export),
        rows=[row.cells for row in rows],
        bold_rows=frozenset(i for i, row in enumerate(rows) if row.kind != "line"),
        indents={i: row.depth for i, row in enumerate(rows)},
        money_columns=plan_export.money_columns(export),
    )
    name = plan_export.export_filename(export.head, "xlsx")
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": content_disposition("attachment", name)},
    )


@router.get(
    "/budget-plan-versions/{version_id}/export.pdf",
    responses=_errors(400, 401, 403, 404, 503),
)
async def export_plan_pdf(
    version_id: UUID,
    service: ServiceDep,
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> Response:
    """Return a version of a Haushaltsplan as a PDF, for each reader of the plan.

    The PDF carries the export logo of the branding.

    Rules: §F/finance/budget/000875, §F/administration/admin/000891.

    Raises:
        BadRequestError: `render_failed` (400) when the render service refuses the plan.
        ServiceUnavailableError: The render service does not answer (503).
    """
    export = await _export_of(service, principal, version_id, "pdf")
    logo = await active_export_logo(service.session)
    try:
        pdf = await build_typst_client(settings).render_pdf(
            plan_export.pdf_source(export),
            variant="plan",
            config={**export_render_config(logo, footer=False), **plan_export.pdf_config(export)},
            assets=export_render_assets(logo),
        )
    except TypstError as exc:
        if not exc.retryable:
            raise BadRequestError(
                f"The plan could not be rendered: {exc}", code="render_failed"
            ) from exc
        raise ServiceUnavailableError("PDF rendering temporarily unavailable.") from exc
    name = plan_export.export_filename(export.head, "pdf")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition("attachment", name)},
    )


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
    """Create the Haushaltsplan of a fiscal year with its first version in draft."""
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


@router.put(
    "/budget-plan-versions/{version_id}/lines/{budget_id}/name",
    response_model=PlanOut,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 409, 422),
)
async def rename_plan_line(
    version_id: UUID, budget_id: UUID, payload: PlanLineRename, service: ServiceDep
) -> PlanOut:
    """Give the cost center of a draft line a new name, a new key or both."""
    out = await service.rename_line(version_id, budget_id, payload)
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
    """Bring a version into force, or move a version in progress back to draft."""
    out = await service.set_plan_state(version_id, payload)
    await service.session.commit()
    return out


@router.put(
    "/budget-plan-versions/{version_id}/state",
    response_model=PlanOut,
    dependencies=_SET_STATE,
    responses=_errors(401, 403, 404, 409, 422),
)
async def set_plan_state_by_hand(
    version_id: UUID, payload: PlanStateByHand, service: ServiceDep
) -> PlanOut:
    """Set the state of the newest version of a plan by hand, with a reason."""
    out = await service.set_state_by_hand(version_id, payload)
    await service.session.commit()
    return out


@router.get(
    "/budgets/{budget_id}/plan-steps",
    response_model=PlanStepsOut,
    responses=_errors(401, 403, 404, 422),
)
async def get_plan_steps(
    budget_id: UUID,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> PlanStepsOut:
    """Return the steps that a plan version of this budget passes."""
    await _require_node_view(service, principal, budget_id)
    return await service.get_plan_steps(budget_id)


@router.put(
    "/budgets/{budget_id}/plan-steps",
    response_model=PlanStepsOut,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 422),
)
async def set_plan_steps(
    budget_id: UUID, payload: PlanStepsSet, service: ServiceDep
) -> PlanStepsOut:
    """Replace the ordered steps of a top-level cost center."""
    out = await service.set_plan_steps(budget_id, payload)
    await service.session.commit()
    return out


@router.post(
    "/budget-plan-versions/{version_id}/steps/next",
    response_model=PlanOut,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 409, 422),
)
async def pass_next_plan_step(
    version_id: UUID, service: ServiceDep, payload: PlanStepPass | None = None
) -> PlanOut:
    """Record the next step of a version as passed.

    A body with `step` names the step that the caller means, by its place in the
    list from 0. The call answers 409 when that step is no longer the next one.
    """
    out = await service.pass_next_step(
        version_id, expected=payload.step if payload is not None else None
    )
    await service.session.commit()
    return out


@router.post(
    "/budget-plan-versions/{version_id}/steps/next/request",
    response_model=PlanOut,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 409, 422),
)
async def request_plan_step(version_id: UUID, service: ServiceDep) -> PlanOut:
    """Ask the Gremium of the next step for its decision.

    The request creates no vote. The step waits for a meeting of the Gremium, which
    takes the plan as an agenda item and votes on it. An accepted vote passes the step.
    """
    out = await service.request_step(version_id)
    await service.session.commit()
    return out


@router.delete(
    "/budget-plan-versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 409),
)
async def delete_plan_version(version_id: UUID, service: ServiceDep) -> None:
    """Delete a draft version, and the plan with it when it has no other version."""
    await service.delete_version(version_id)
    await service.session.commit()


@router.post(
    "/budget-plan-versions/{version_id}/cost-centres",
    response_model=PlanOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_STRUCTURE,
    responses=_errors(401, 403, 404, 409, 422),
)
async def create_plan_cost_centre(
    version_id: UUID, payload: PlanNodeCreate, service: ServiceDep
) -> PlanOut:
    """Create a cost center and its line in a draft version."""
    out = await service.create_plan_node(version_id, payload)
    await service.session.commit()
    return out
