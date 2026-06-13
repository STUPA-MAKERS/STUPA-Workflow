"""Budget-Baum-API-Router (CR #76/#78, api.md »budget«).

Endpunkte (alle Principal-only, fail-closed, RBAC aus T-10):

* ``GET    /api/budgets``                                  — P(``budget.view``); Baum.
* ``POST   /api/budgets``                                  — P(``budget.structure``); Knoten.
* ``PATCH/DELETE /api/budgets/{id}``                       — P(``budget.structure``).
* ``GET/POST /api/budgets/{topId}/fiscal-years``           — P(``budget.structure``).
* ``PATCH  /api/budgets/{topId}/fiscal-years/{fyId}``      — P(``budget.structure``).
* ``PUT    /api/budgets/{id}/allocations/{fyId}``          — P(``budget.structure``).
* Buchungen/Umbuchungen (expenses/transfers)               — P(``budget.book``) (#6).
* ``POST   /api/applications/{id}/assign-budget``          — P(``application.manage``).
* ``POST   /api/applications/{id}/move-fiscal-year``       — P(``application.manage``).

Fehler als ``ProblemDetail`` (problem+json). Constraints (Kinder ≤ Eltern, HHJ-
Disjunktheit) → 422; Löschen mit Kindern/Zuteilungen → 409.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.deps import DbSession, Principal, require_any_permission, require_principal
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget.tree_schemas import (
    AccountCreate,
    AccountOption,
    AccountOut,
    AccountUpdate,
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
    ExpenseKind,
    ExpenseOut,
    ExpenseUpdate,
    FiscalYearCreate,
    FiscalYearOut,
    FiscalYearUpdate,
    InvoiceCreate,
    InvoiceOut,
    InvoiceUpdate,
    MoveFiscalYearRequest,
    TransferCreate,
    TransferOut,
)
from app.modules.budget.tree_service import BudgetTreeService
from app.shared.errors import ForbiddenError, ProblemDetail
from app.shared.paging import Page

router = APIRouter(tags=["budget"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_budget_tree_service(session: DbSession) -> BudgetTreeService:
    return BudgetTreeService(session)


ServiceDep = Annotated[BudgetTreeService, Depends(get_budget_tree_service)]




# Globale Voll-Sicht auf den Budget-Tab — jede dieser Permissions zeigt ALLES;
# ohne sie greift der Gremium-Scope (#budget-scope, view_gremium_id).
_FULL_VIEW_PERMS = ("budget.view", "budget.structure", "budget.book")


def _has_full_view(principal: Principal) -> bool:
    return any(principal.has(p) for p in _FULL_VIEW_PERMS)


async def _member_gremium_ids(service: BudgetTreeService, sub: str) -> set[UUID]:
    from app.modules.admin.gremium_roles import gremium_member_ids

    return await gremium_member_ids(service.session, sub)


async def _require_node_view(
    service: BudgetTreeService, principal: Principal, budget_id: UUID
) -> None:
    """Voll-Sicht ODER Knoten liegt in einem zugeordneten Teilbaum (#budget-scope)."""
    if _has_full_view(principal):
        return
    member = await _member_gremium_ids(service, principal.sub)
    if not await service.can_view_node(budget_id, member):
        raise ForbiddenError("no access to this cost centre")

# --------------------------------------------------------------------- nodes
@router.get(
    "/budgets",
    response_model=list[BudgetTreeNodeOut],
    responses=_errors(401, 403),
)
async def list_budget_tree(
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
    gremium_id: Annotated[UUID | None, Query(alias="gremium")] = None,
) -> list[BudgetTreeNodeOut]:
    """Kostenstellen-Baum (mit ``pathKey``, allocated/committed/available je HHJ).

    Voll-Sicht mit ``budget.view``/``structure``/``book``; sonst Gremium-Scope
    (#budget-scope): nur Teilbäume, deren ``viewGremiumId`` einem Mitglieds-Gremium
    des Principals entspricht — als Roots. Ohne beides: leere Liste."""
    if _has_full_view(principal):
        return await service.get_tree(gremium_id=gremium_id)
    member = await _member_gremium_ids(service, principal.sub)
    return await service.get_tree(
        gremium_id=gremium_id, visible_gremium_ids=member
    )


def _find_subtree(
    roots: list[BudgetTreeNodeOut], node_id: UUID
) -> BudgetTreeNodeOut | None:
    for node in roots:
        if node.id == node_id:
            return node
        found = _find_subtree(node.children, node_id)
        if found is not None:
            return found
    return None


@router.get(
    "/budget/export.xlsx",
    responses=_errors(401, 403),
)
async def export_budget_xlsx(
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("budget.export"))],
    gremium_id: Annotated[UUID | None, Query(alias="gremium")] = None,
    node_id: Annotated[UUID | None, Query(alias="node")] = None,
    fiscal_year_id: Annotated[UUID | None, Query(alias="fiscalYear")] = None,
) -> Response:
    """Budget-Baum als ``.xlsx`` (P(``budget.export``)), gefiltert wie das Dashboard.

    ``gremium`` / ``node`` (Teilbaum-Auswahl) / ``fiscalYear`` spiegeln die aktiven
    Dashboard-Filter; ``node`` exportiert nur diesen Knoten samt Unterbaum.
    """
    from app.shared.xlsx import XLSX_MEDIA_TYPE, build_budget_workbook

    roots = await service.get_tree(gremium_id=gremium_id)
    if node_id is not None:
        sub = _find_subtree(roots, node_id)
        roots = [sub] if sub is not None else []
    labels = await service.fiscal_year_label_map()
    data = build_budget_workbook(
        roots, fiscal_year_labels=labels, fiscal_year_id=fiscal_year_id
    )
    await audit_record(
        service.session,
        actor=principal.sub,
        action=AuditAction.EXPORT,
        target_type="export",
        target_id="budget.xlsx",
        data={
            "gremium_id": str(gremium_id) if gremium_id else None,
            "node_id": str(node_id) if node_id else None,
            "fiscal_year_id": str(fiscal_year_id) if fiscal_year_id else None,
        },
    )
    await service.session.commit()
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="budget.xlsx"'},
    )


@router.post(
    "/budgets",
    response_model=BudgetNodeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_principal("budget.structure"))],
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
    dependencies=[Depends(require_principal("budget.structure"))],
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
    dependencies=[Depends(require_principal("budget.structure"))],
    responses=_errors(401, 403, 404, 409),
)
async def delete_budget_node(budget_id: UUID, service: ServiceDep) -> None:
    """Kostenstelle löschen (nur ohne Kinder/Zuteilungen → 409 sonst)."""
    await service.delete_node(budget_id)


@router.get(
    "/budgets/{budget_id}/applications",
    response_model=list[BudgetApplicationOut],
    responses=_errors(401, 403, 404),
)
async def list_budget_applications(
    budget_id: UUID,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
    fiscal_year_id: Annotated[UUID | None, Query(alias="fiscalYear")] = None,
) -> list[BudgetApplicationOut]:
    """Anträge dieser Kostenstelle + Unterbaum (#17), optional HHJ-gefiltert.

    Voll-Sicht oder Gremium-Scope auf den Knoten (#budget-scope)."""
    await _require_node_view(service, principal, budget_id)
    return await service.list_applications(budget_id, fiscal_year_id)


# -------------------------------------------------------------------- expenses
@router.get(
    "/budgets/{budget_id}/expenses",
    response_model=list[ExpenseOut],
    responses=_errors(401, 403, 404),
)
async def list_budget_expenses(
    budget_id: UUID,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
    fiscal_year_id: Annotated[UUID | None, Query(alias="fiscalYear")] = None,
) -> list[ExpenseOut]:
    """Eigenständige Ausgaben dieser Kostenstelle + Unterbaum (#25), optional HHJ.

    Voll-Sicht oder Gremium-Scope auf den Knoten (#budget-scope)."""
    await _require_node_view(service, principal, budget_id)
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
    principal: Annotated[Principal, Depends(require_principal("budget.book"))],
) -> ExpenseOut:
    """Ausgabe ohne Antrag gegen Kostenstelle + HHJ buchen (#25)."""
    return await service.create_expense(budget_id, payload, actor=principal.sub)


@router.delete(
    "/budget-expenses/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("budget.book"))],
    responses=_errors(401, 403, 404),
)
async def delete_budget_expense(expense_id: UUID, service: ServiceDep) -> None:
    """Gebuchte Ausgabe/Einnahme löschen (#25)."""
    await service.delete_expense(expense_id)


# --------------------------------------------------- expenses (flat, #25 tab)
@router.post(
    "/expenses",
    response_model=ExpenseOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(400, 401, 403, 404, 422),
)
async def book_expense(
    payload: ExpenseCreate,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("budget.book"))],
) -> ExpenseOut:
    """Ausgabe/Einnahme buchen (#25): eigenständig (``budgetId``) oder an einen Antrag
    gebunden (``applicationId`` — erbt Kostenstelle + HHJ, ersetzt dessen Bindung)."""
    return await service.book_expense(payload, actor=principal.sub)


@router.get(
    "/expenses",
    response_model=Page[ExpenseOut],
    # Lesen für jede Budget-Rolle (#5-2): view/structure/book sehen die Buchungsliste.
    dependencies=[
        Depends(require_any_permission("budget.view", "budget.structure", "budget.book"))
    ],
    responses=_errors(401, 403, 404),
)
async def list_expenses(
    service: ServiceDep,
    budget_id: Annotated[UUID | None, Query(alias="budget")] = None,
    fiscal_year_id: Annotated[UUID | None, Query(alias="fiscalYear")] = None,
    kind: Annotated[ExpenseKind | None, Query()] = None,
    application_id: Annotated[UUID | None, Query(alias="applicationId")] = None,
    q: Annotated[str | None, Query()] = None,
    amount_min: Annotated[Decimal | None, Query(alias="amountMin", ge=0)] = None,
    amount_max: Annotated[Decimal | None, Query(alias="amountMax", ge=0)] = None,
    created_from: Annotated[str | None, Query(alias="createdFrom")] = None,
    created_to: Annotated[str | None, Query(alias="createdTo")] = None,
    sort: Annotated[
        Literal["createdAt", "amount", "invoiceDate", "paymentDate"] | None, Query()
    ] = None,
    order: Annotated[Literal["asc", "desc"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ExpenseOut]:
    """Buchungen gefiltert + sortiert + offset-paginiert (#25). ``budget`` schließt den
    Unterbaum ein; ``kind`` = ``expense``/``income``; ``q`` = Beschreibungssuche;
    ``amountMin``/``amountMax`` = Betragsbereich; ``sort``/``order`` = Spalten-Sortierung."""
    return await service.list_expenses_paged(
        budget_id=budget_id,
        fiscal_year_id=fiscal_year_id,
        kind=kind,
        application_id=application_id,
        q=q,
        amount_min=amount_min,
        amount_max=amount_max,
        created_from=created_from,
        created_to=created_to,
        sort="amount" if sort == "amount" else "createdAt",
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/expenses/export.xlsx",
    responses=_errors(401, 403),
)
async def export_expenses_xlsx(
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("budget.export"))],
    budget_id: Annotated[UUID | None, Query(alias="budget")] = None,
    fiscal_year_id: Annotated[UUID | None, Query(alias="fiscalYear")] = None,
    kind: Annotated[ExpenseKind | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    amount_min: Annotated[Decimal | None, Query(alias="amountMin", ge=0)] = None,
    amount_max: Annotated[Decimal | None, Query(alias="amountMax", ge=0)] = None,
    created_from: Annotated[str | None, Query(alias="createdFrom")] = None,
    created_to: Annotated[str | None, Query(alias="createdTo")] = None,
) -> Response:
    """Gefilterte Buchungen als ``.xlsx`` (P(``budget.export``)) — Inhalt wie die Liste."""
    from app.shared.xlsx import XLSX_MEDIA_TYPE, build_expenses_workbook

    page = await service.list_expenses_paged(
        budget_id=budget_id,
        fiscal_year_id=fiscal_year_id,
        kind=kind,
        q=q,
        amount_min=amount_min,
        amount_max=amount_max,
        created_from=created_from,
        created_to=created_to,
        limit=10_000,
        offset=0,
    )
    data = build_expenses_workbook(page.items)
    await audit_record(
        service.session,
        actor=principal.sub,
        action=AuditAction.EXPORT,
        target_type="export",
        target_id="buchungen.xlsx",
        data={"rows": len(page.items)},
    )
    await service.session.commit()
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="buchungen.xlsx"'},
    )


@router.patch(
    "/budget-expenses/{expense_id}",
    response_model=ExpenseOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_budget_expense(
    expense_id: UUID,
    payload: ExpenseUpdate,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("budget.book"))],
) -> ExpenseOut:
    """Betrag/Beschreibung einer Buchung ändern (#25)."""
    return await service.update_expense(expense_id, payload)


# ----------------------------------------------------------------- transfers
@router.post(
    "/budget-transfers",
    response_model=TransferOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_transfer(
    payload: TransferCreate,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("budget.book"))],
) -> TransferOut:
    """Übertrag Kostenstelle → Kostenstelle (Ausgabe + Einnahme, gleiches HHJ)."""
    return await service.create_transfer(payload, actor=principal.sub)


# ------------------------------------------------------------------- invoices
# Lesen: jede Budget-Rolle; Schreiben: budget.book (#invoices).
_INVOICE_READ = Depends(
    require_any_permission("budget.view", "budget.structure", "budget.book")
)


@router.get(
    "/invoices",
    response_model=list[InvoiceOut],
    dependencies=[_INVOICE_READ],
    responses=_errors(401, 403),
)
async def list_invoices(service: ServiceDep) -> list[InvoiceOut]:
    """Rechnungen (neueste Rechnungsdatum zuerst)."""
    return await service.list_invoices()


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceOut,
    dependencies=[_INVOICE_READ],
    responses=_errors(401, 403, 404),
)
async def get_invoice(invoice_id: UUID, service: ServiceDep) -> InvoiceOut:
    return await service.get_invoice(invoice_id)


@router.post(
    "/invoices",
    response_model=InvoiceOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(400, 401, 403, 422),
)
async def create_invoice(
    payload: InvoiceCreate,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("budget.book"))],
) -> InvoiceOut:
    return await service.create_invoice(payload, actor=principal.sub)


@router.patch(
    "/invoices/{invoice_id}",
    response_model=InvoiceOut,
    dependencies=[Depends(require_principal("budget.book"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_invoice(
    invoice_id: UUID, payload: InvoiceUpdate, service: ServiceDep
) -> InvoiceOut:
    return await service.update_invoice(invoice_id, payload)


@router.delete(
    "/invoices/{invoice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("budget.book"))],
    responses=_errors(401, 403, 404),
)
async def delete_invoice(invoice_id: UUID, service: ServiceDep) -> None:
    await service.delete_invoice(invoice_id)


# ------------------------------------------------------------------- accounts
@router.get(
    "/accounts/options",
    response_model=list[AccountOption],
    # Minimale Auswahl (id+Name, keine IBAN) für Buchungs-Dropdowns — Bucher dürfen das
    # ohne account.manage (#5-2/#2). Volle Stammdaten bleiben account.manage.
    dependencies=[
        Depends(require_any_permission("account.manage", "budget.book", "budget.view"))
    ],
    responses=_errors(401, 403),
)
async def list_account_options(service: ServiceDep) -> list[AccountOption]:
    """Aktive Konten als id+Name (ohne IBAN) — für Buchungs-Auswahl."""
    return await service.list_account_options()


@router.get(
    "/accounts",
    response_model=list[AccountOut],
    dependencies=[Depends(require_principal("account.manage"))],
    responses=_errors(401, 403),
)
async def list_accounts(service: ServiceDep) -> list[AccountOut]:
    """Konten (Name + IBAN) — P(``account.manage``)."""
    return await service.list_accounts()


@router.post(
    "/accounts",
    response_model=AccountOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_principal("account.manage"))],
    responses=_errors(400, 401, 403, 422),
)
async def create_account(payload: AccountCreate, service: ServiceDep) -> AccountOut:
    return await service.create_account(payload)


@router.patch(
    "/accounts/{account_id}",
    response_model=AccountOut,
    dependencies=[Depends(require_principal("account.manage"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_account(
    account_id: UUID, payload: AccountUpdate, service: ServiceDep
) -> AccountOut:
    return await service.update_account(account_id, payload)


@router.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("account.manage"))],
    responses=_errors(401, 403, 404),
)
async def delete_account(account_id: UUID, service: ServiceDep) -> None:
    await service.delete_account(account_id)


# ---------------------------------------------------------------- fiscal years
@router.get(
    "/budgets/{budget_id}/fiscal-years",
    response_model=list[FiscalYearOut],
    responses=_errors(401, 403, 404, 422),
)
async def list_fiscal_years(
    budget_id: UUID,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> list[FiscalYearOut]:
    """Haushaltsjahre auflisten — jeder Knoten erlaubt; Nicht-Top-Level löst auf
    seinen Top-Level-Vorfahren auf (#budget-scope: gescopte Roots sind oft
    Unter-Kostenstellen). Voll-Sicht oder Gremium-Scope auf den Knoten."""
    await _require_node_view(service, principal, budget_id)
    return await service.list_fiscal_years(budget_id)


@router.post(
    "/budgets/{budget_id}/fiscal-years",
    response_model=FiscalYearOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_principal("budget.structure"))],
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
    dependencies=[Depends(require_principal("budget.structure"))],
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
    dependencies=[Depends(require_principal("budget.structure"))],
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
