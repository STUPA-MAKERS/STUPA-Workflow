"""Budget-Baum-API-Router (CR #76/#78, api.md »budget«).

Endpunkte (alle Principal-only, fail-closed, RBAC aus T-10):

* ``GET    /api/budgets``                                  — P(``budget.view``); Baum.
* ``POST   /api/budgets``                                  — P(``budget.manage``); Knoten.
* ``PATCH/DELETE /api/budgets/{id}``                       — P(``budget.manage``).
* ``GET/POST /api/budgets/{topId}/fiscal-years``           — P(``budget.manage``).
* ``PATCH  /api/budgets/{topId}/fiscal-years/{fyId}``      — P(``budget.manage``).
* ``PUT    /api/budgets/{id}/allocations/{fyId}``          — P(``budget.manage``).
* ``POST   /api/applications/{id}/assign-budget``          — P(``application.manage``).
* ``POST   /api/applications/{id}/move-fiscal-year``       — P(``application.manage``).

Fehler als ``ProblemDetail`` (problem+json). Constraints (Kinder ≤ Eltern, HHJ-
Disjunktheit) → 422; Löschen mit Kindern/Zuteilungen → 409.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.deps import DbSession, Principal, require_principal
from app.modules.budget.tree_schemas import (
    AllocationOut,
    AllocationSet,
    AssignBudgetOut,
    AssignBudgetRequest,
    BudgetApplicationOut,
    BudgetNodeCreate,
    BudgetNodeOut,
    BudgetNodeUpdate,
    BudgetTreeNodeOut,
    ExpenseCreate,
    ExpenseOut,
    FiscalYearCreate,
    FiscalYearOut,
    FiscalYearUpdate,
    MoveFiscalYearRequest,
)
from app.modules.budget.tree_service import BudgetTreeService
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["budget"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_budget_tree_service(session: DbSession) -> BudgetTreeService:
    return BudgetTreeService(session)


ServiceDep = Annotated[BudgetTreeService, Depends(get_budget_tree_service)]


# --------------------------------------------------------------------- nodes
@router.get(
    "/budgets",
    response_model=list[BudgetTreeNodeOut],
    dependencies=[Depends(require_principal("budget.view"))],
    responses=_errors(401, 403),
)
async def list_budget_tree(
    service: ServiceDep,
    gremium_id: Annotated[UUID | None, Query(alias="gremium")] = None,
) -> list[BudgetTreeNodeOut]:
    """Kostenstellen-Baum (mit ``pathKey``, allocated/committed/available je HHJ)."""
    return await service.get_tree(gremium_id=gremium_id)


@router.post(
    "/budgets",
    response_model=BudgetNodeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def create_budget_node(
    payload: BudgetNodeCreate, service: ServiceDep
) -> BudgetNodeOut:
    """Kostenstelle anlegen (Top-Level mit ``gremiumId``; Kinder mit ``parentId``)."""
    return await service.create_node(payload)


@router.patch(
    "/budgets/{budget_id}",
    response_model=BudgetNodeOut,
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_budget_node(
    budget_id: UUID, payload: BudgetNodeUpdate, service: ServiceDep
) -> BudgetNodeOut:
    """Kostenstelle ändern (Name/Aktiv-Status)."""
    return await service.update_node(budget_id, payload)


@router.delete(
    "/budgets/{budget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(401, 403, 404, 409),
)
async def delete_budget_node(budget_id: UUID, service: ServiceDep) -> None:
    """Kostenstelle löschen (nur ohne Kinder/Zuteilungen → 409 sonst)."""
    await service.delete_node(budget_id)


@router.get(
    "/budgets/{budget_id}/applications",
    response_model=list[BudgetApplicationOut],
    dependencies=[Depends(require_principal("budget.view"))],
    responses=_errors(401, 403, 404),
)
async def list_budget_applications(
    budget_id: UUID,
    service: ServiceDep,
    fiscal_year_id: Annotated[UUID | None, Query(alias="fiscalYear")] = None,
) -> list[BudgetApplicationOut]:
    """Anträge dieser Kostenstelle + Unterbaum (#17), optional HHJ-gefiltert."""
    return await service.list_applications(budget_id, fiscal_year_id)


# -------------------------------------------------------------------- expenses
@router.get(
    "/budgets/{budget_id}/expenses",
    response_model=list[ExpenseOut],
    dependencies=[Depends(require_principal("budget.view"))],
    responses=_errors(401, 403, 404),
)
async def list_budget_expenses(
    budget_id: UUID,
    service: ServiceDep,
    fiscal_year_id: Annotated[UUID | None, Query(alias="fiscalYear")] = None,
) -> list[ExpenseOut]:
    """Eigenständige Ausgaben dieser Kostenstelle + Unterbaum (#25), optional HHJ."""
    return await service.list_expenses(budget_id, fiscal_year_id)


@router.post(
    "/budgets/{budget_id}/expenses",
    response_model=ExpenseOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_budget_expense(
    budget_id: UUID,
    payload: ExpenseCreate,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("budget.manage"))],
) -> ExpenseOut:
    """Ausgabe ohne Antrag gegen Kostenstelle + HHJ buchen (#25)."""
    return await service.create_expense(budget_id, payload, actor=principal.sub)


@router.delete(
    "/budget-expenses/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(401, 403, 404),
)
async def delete_budget_expense(expense_id: UUID, service: ServiceDep) -> None:
    """Gebuchte Ausgabe löschen (#25)."""
    await service.delete_expense(expense_id)


# ---------------------------------------------------------------- fiscal years
@router.get(
    "/budgets/{budget_id}/fiscal-years",
    response_model=list[FiscalYearOut],
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(401, 403, 404, 422),
)
async def list_fiscal_years(
    budget_id: UUID, service: ServiceDep
) -> list[FiscalYearOut]:
    """Haushaltsjahre eines Top-Level-Budgets auflisten."""
    return await service.list_fiscal_years(budget_id)


@router.post(
    "/budgets/{budget_id}/fiscal-years",
    response_model=FiscalYearOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_fiscal_year(
    budget_id: UUID, payload: FiscalYearCreate, service: ServiceDep
) -> FiscalYearOut:
    """Haushaltsjahr anlegen (Start/Ende frei; disjunkt pro Top-Budget → 422)."""
    return await service.create_fiscal_year(budget_id, payload)


@router.patch(
    "/budgets/{budget_id}/fiscal-years/{fiscal_year_id}",
    response_model=FiscalYearOut,
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_fiscal_year(
    budget_id: UUID,
    fiscal_year_id: UUID,
    payload: FiscalYearUpdate,
    service: ServiceDep,
) -> FiscalYearOut:
    """Haushaltsjahr ändern (Disjunktheit erneut geprüft)."""
    return await service.update_fiscal_year(budget_id, fiscal_year_id, payload)


# ----------------------------------------------------------------- allocation
@router.put(
    "/budgets/{budget_id}/allocations/{fiscal_year_id}",
    response_model=AllocationOut,
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def set_allocation(
    budget_id: UUID,
    fiscal_year_id: UUID,
    payload: AllocationSet,
    service: ServiceDep,
) -> AllocationOut:
    """Top-Down-Zuteilung setzen (422 wenn Σ Kinder > Parent)."""
    return await service.set_allocation(budget_id, fiscal_year_id, payload)


# ------------------------------------------------------------------- assign
@router.post(
    "/applications/{application_id}/assign-budget",
    response_model=AssignBudgetOut,
    dependencies=[Depends(require_principal("application.manage"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def assign_budget(
    application_id: UUID, payload: AssignBudgetRequest, service: ServiceDep
) -> AssignBudgetOut:
    """Antrag einer Kostenstelle zuordnen; setzt zugleich HHJ (``budgetId=null`` löst)."""
    return await service.assign_budget(application_id, payload)


@router.post(
    "/applications/{application_id}/move-fiscal-year",
    response_model=AssignBudgetOut,
    dependencies=[Depends(require_principal("application.manage"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def move_fiscal_year(
    application_id: UUID, payload: MoveFiscalYearRequest, service: ServiceDep
) -> AssignBudgetOut:
    """Antrag in anderes HHJ verschieben (Konsistenz mit Top-Budget geprüft)."""
    return await service.move_fiscal_year(application_id, payload)
