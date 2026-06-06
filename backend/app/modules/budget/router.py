"""Budget-API-Router (T-17, api.md »budget«).

Endpunkte:

* ``POST/GET   /api/budget-pots``              — P(``budget.manage``); Töpfe + Extra-Felder.
* ``GET/PATCH  /api/budget-pots/{id}``         — P(``budget.manage``); Topf + Auslastung.
* ``POST       /api/applications/{id}/assign`` — P(``application.manage``); Topf-Zuordnung.
* ``GET        /api/budget/stats``             — P(``budget.view``); Rollup-Statistik.

Alle Endpunkte sind Principal-only (fail-closed, RBAC aus T-10). Fehler werden als
``ProblemDetail`` deklariert (problem+json-Hook). Der MV-Refresh wird vom Worker
(Cron/CONCURRENTLY) bzw. der Flow-Engine angestoßen — nicht je HTTP-Write.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.deps import DbSession, Principal, require_principal
from app.modules.budget.schemas import (
    AssignOut,
    AssignRequest,
    BudgetPotCreate,
    BudgetPotDetailOut,
    BudgetPotOut,
    BudgetPotUpdate,
    BudgetStatsOut,
)
from app.modules.budget.service import BudgetService
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["budget"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_budget_service(session: DbSession) -> BudgetService:
    return BudgetService(session)


ServiceDep = Annotated[BudgetService, Depends(get_budget_service)]


@router.post(
    "/budget-pots",
    response_model=BudgetPotOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_pot(payload: BudgetPotCreate, service: ServiceDep) -> BudgetPotOut:
    """Budget-Topf (+ Extra-Felder) anlegen."""
    return await service.create_pot(payload)


@router.get(
    "/budget-pots",
    response_model=list[BudgetPotOut],
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(401, 403),
)
async def list_pots(
    service: ServiceDep,
    gremium_id: Annotated[UUID | None, Query(alias="gremium")] = None,
    period: Annotated[str | None, Query()] = None,
    active: Annotated[bool | None, Query()] = None,
) -> list[BudgetPotOut]:
    """Töpfe auflisten (Filter: gremium/period/active)."""
    return await service.list_pots(gremium_id=gremium_id, period=period, active=active)


@router.get(
    "/budget-pots/{pot_id}",
    response_model=BudgetPotDetailOut,
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(401, 403, 404),
)
async def get_pot(pot_id: UUID, service: ServiceDep) -> BudgetPotDetailOut:
    """Einzelnen Topf + Auslastung lesen."""
    return await service.get_pot(pot_id)


@router.patch(
    "/budget-pots/{pot_id}",
    response_model=BudgetPotOut,
    dependencies=[Depends(require_principal("budget.manage"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_pot(
    pot_id: UUID, payload: BudgetPotUpdate, service: ServiceDep
) -> BudgetPotOut:
    """Topf teil-aktualisieren (``fields`` ersetzt die Extra-Felder)."""
    return await service.update_pot(pot_id, payload)


@router.post(
    "/applications/{application_id}/assign",
    response_model=AssignOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def assign_application(
    application_id: UUID,
    payload: AssignRequest,
    service: ServiceDep,
    # Einmalige RBAC-Prüfung (der Principal wird zugleich als ``actor`` gebraucht).
    principal: Annotated[Principal, Depends(require_principal("application.manage"))],
) -> AssignOut:
    """Antrag einem Gremium/Topf zuordnen (manuell; ``budgetPotId=null`` löst)."""
    return await service.assign(application_id, payload, actor=principal.sub)


@router.get(
    "/budget/stats",
    response_model=BudgetStatsOut,
    dependencies=[Depends(require_principal("budget.view"))],
    responses=_errors(401, 403),
)
async def budget_stats(
    service: ServiceDep,
    gremium_id: Annotated[UUID | None, Query(alias="gremium")] = None,
    period: Annotated[str | None, Query(alias="period")] = None,
    budget_pot_id: Annotated[UUID | None, Query(alias="pot")] = None,
) -> BudgetStatsOut:
    """Rollup-Statistik (Auslastung + Statusverteilung; Filter pot/gremium/period)."""
    return await service.stats_service().stats(
        gremium_id=gremium_id, period=period, budget_pot_id=budget_pot_id
    )
