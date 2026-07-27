"""Budget-tree API router with principal-only and fail-closed RBAC.

Permission scope:

1. A tree read needs ``budget.view`` or the gremium scope.
2. A structure change (node, fiscal year, allocation) needs
   ``budget.structure``.
3. A booking or a transfer moves money and needs ``budget.book``.
4. Assign-budget and move-fiscal-year need ``application.manage``.

A constraint violation gives 422. The checked constraints are children <=
parent and fiscal-year disjointness. A delete of a node that still has children
or allocations gives 409.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status

from app.deps import (
    DbSession,
    Principal,
    SettingsDep,
    require_any_permission,
    require_principal,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget.bank.service import BankService
from app.modules.budget.invoice_import import (
    NotZugferdError,
    UnsupportedInvoiceCurrencyError,
)
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_schemas import (
    AccountCreate,
    AccountOption,
    AccountOut,
    AccountUpdate,
    AllocationOut,
    AllocationSet,
    AssignBudgetOut,
    AssignBudgetRequest,
    BankImportResult,
    BankSyncResult,
    BankTanRequest,
    BudgetApplicationOut,
    BudgetNodeCreate,
    BudgetNodeOut,
    BudgetNodeUpdate,
    BudgetTreeNodeOut,
    ConfirmLineRequest,
    ExpenseCreate,
    ExpenseKind,
    ExpenseOut,
    ExpenseUpdate,
    FintsCredentialIn,
    FintsCredentialStatus,
    FiscalYearCreate,
    FiscalYearOut,
    FiscalYearUpdate,
    IgnoreLineRequest,
    InvoiceCreate,
    InvoiceFileResult,
    InvoiceOut,
    InvoiceParseResult,
    InvoiceStatus,
    InvoiceUpdate,
    MoveFiscalYearRequest,
    StatementLineDetail,
    StatementLineOut,
    SubBookingCreate,
    TransferCreate,
    TransferOut,
)
from app.shared.antiabuse import body_cap, rate_limit_fints
from app.shared.errors import ForbiddenError, ProblemDetail, ValidationProblem
from app.shared.paging import Page

router = APIRouter(tags=["budget"])

# Body cap on Content-Length for a receipt upload, applied before FastAPI
# buffers the body. It adds defense in depth next to the nginx cap and the
# in-app size check.
_enforce_invoice_body = body_cap("attachment_max_bytes")

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_budget_tree_service(
    session: DbSession,
    request: Request,
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> BudgetTreeService:
    # Only the invoice import uses the storage. ``actor`` is the principal
    # ``sub`` for the audit trail of the money mutations. All budget endpoints
    # require authentication.
    storage = getattr(request.app.state, "object_storage", None)
    return BudgetTreeService(session, storage=storage, settings=settings, actor=principal.sub)


ServiceDep = Annotated[BudgetTreeService, Depends(get_budget_tree_service)]


async def get_bank_service(
    session: DbSession,
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> BankService:
    """Build the bank service.

    ``actor`` feeds the audit trail. ``principal_id`` scopes the personal
    credentials and the TAN sessions.
    """
    from sqlalchemy import select

    from app.modules.auth.models import Principal as PrincipalRow

    principal_id = await session.scalar(
        select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub)
    )
    return BankService(
        session, settings=settings, actor=principal.sub, principal_id=principal_id
    )


BankServiceDep = Annotated[BankService, Depends(get_bank_service)]


# Global full view of the budget tab. Each of these permissions shows ALL nodes.
# Without one of them the gremium scope (view_gremium_id) applies.
_FULL_VIEW_PERMS = ("budget.view", "budget.structure", "budget.book")


def _has_full_view(principal: Principal) -> bool:
    return any(principal.has(p) for p in _FULL_VIEW_PERMS)


async def _member_gremium_ids(service: BudgetTreeService, sub: str) -> set[UUID]:
    from app.modules.admin.gremium_roles import gremium_member_ids

    return await gremium_member_ids(service.session, sub)


async def _require_node_view(
    service: BudgetTreeService, principal: Principal, budget_id: UUID
) -> None:
    """Require the full view, or a node in a subtree of a member Gremium.

    Raises:
        ForbiddenError: The principal has neither the full view nor the gremium
            scope on this node.
    """
    if _has_full_view(principal):
        return
    member = await _member_gremium_ids(service, principal.sub)
    if not await service.can_view_node(budget_id, member):
        raise ForbiddenError("no access to this cost centre")


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
    """Cost-center tree with allocated, committed and available per fiscal year.

    Each node also carries its ``pathKey``. ``budget.view``,
    ``budget.structure`` or ``budget.book`` give the full view. Without one of
    them the gremium scope applies. The response then holds only the subtrees
    whose ``viewGremiumId`` matches a member Gremium, and it returns them as
    roots. A principal with neither gets an empty list.
    """
    if _has_full_view(principal):
        return await service.get_tree(gremium_id=gremium_id)
    member = await _member_gremium_ids(service, principal.sub)
    return await service.get_tree(gremium_id=gremium_id, visible_gremium_ids=member)


def _find_subtree(roots: list[BudgetTreeNodeOut], node_id: UUID) -> BudgetTreeNodeOut | None:
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
    """Export the budget tree as ``.xlsx``, filtered like the dashboard.

    ``gremium``, ``node`` and ``fiscalYear`` mirror the active dashboard
    filters. ``node`` selects a subtree and exports that node and its subtree
    only.
    """
    from app.shared.xlsx import XLSX_MEDIA_TYPE, build_budget_workbook

    roots = await service.get_tree(gremium_id=gremium_id)
    if node_id is not None:
        sub = _find_subtree(roots, node_id)
        roots = [sub] if sub is not None else []
    labels = await service.fiscal_year_label_map()
    data = build_budget_workbook(roots, fiscal_year_labels=labels, fiscal_year_id=fiscal_year_id)
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
async def create_budget_node(payload: BudgetNodeCreate, service: ServiceDep) -> BudgetNodeOut:
    """Create a cost center: a top level with ``gremiumId``, a child with ``parentId``."""
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
    """Update a cost center: the name or the active flag."""
    return await service.update_node(budget_id, payload)


@router.delete(
    "/budgets/{budget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("budget.structure"))],
    responses=_errors(401, 403, 404, 409),
)
async def delete_budget_node(budget_id: UUID, service: ServiceDep) -> None:
    """Delete a cost center. A node with children or allocations gives 409."""
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
    """List the applications of this cost center and of its subtree.

    The ``fiscalYear`` filter is optional. The caller needs the full view or the
    gremium scope on the node.
    """
    await _require_node_view(service, principal, budget_id)
    return await service.list_applications(budget_id, fiscal_year_id)


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
    """List the standalone expenses of this cost center and of its subtree.

    The ``fiscalYear`` filter is optional. The caller needs the full view or the
    gremium scope on the node.
    """
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
    """Book an expense without an application against a cost center and fiscal year."""
    return await service.create_expense(budget_id, payload, actor=principal.sub)


@router.delete(
    "/budget-expenses/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("budget.book"))],
    responses=_errors(401, 403, 404),
)
async def delete_budget_expense(expense_id: UUID, service: ServiceDep) -> None:
    """Delete a booked expense or income."""
    await service.delete_expense(expense_id)


@router.get(
    "/budget-expenses/{expense_id}/sub-bookings",
    response_model=list[ExpenseOut],
    dependencies=[
        Depends(require_any_permission("budget.view", "budget.structure", "budget.book"))
    ],
    responses=_errors(401, 403, 404),
)
async def list_sub_bookings(expense_id: UUID, service: ServiceDep) -> list[ExpenseOut]:
    """List the sub-bookings of a booking, for the expand row in the bookings tab."""
    return await service.list_sub_expenses(expense_id)


@router.post(
    "/budget-expenses/{expense_id}/sub-bookings",
    response_model=ExpenseOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 404, 422),
)
async def create_sub_booking(
    expense_id: UUID,
    payload: SubBookingCreate,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("budget.book"))],
) -> ExpenseOut:
    """Create a sub-booking by hand.

    The sub-booking inherits account, cost center, fiscal year and kind from
    the parent booking.
    """
    return await service.create_sub_booking(expense_id, payload, actor=principal.sub)


@router.post(
    "/budget-expenses/{expense_id}/sub-bookings/import",
    response_model=list[ExpenseOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_principal("budget.book")),
        Depends(_enforce_invoice_body),
    ],
    responses=_errors(401, 403, 404, 413, 422),
)
async def import_sub_bookings(
    expense_id: UUID,
    service: ServiceDep,
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(require_principal("budget.book"))],
) -> list[ExpenseOut]:
    """Create sub-bookings from a CAMT.053/MT940 file.

    Each child inherits account, cost center, fiscal year and kind from the
    parent. The parent amount is the sum of its children.
    """
    data = await file.read()
    return await service.import_sub_bookings(
        expense_id, data, filename=file.filename, actor=principal.sub
    )


# Flat bookings tab: the next expense routes are not scoped to one node.
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
    """Book an expense or an income.

    A standalone booking uses ``budgetId``. A booking with ``applicationId``
    binds to an application. It inherits cost center and fiscal year from that
    application and replaces its binding.
    """
    return await service.book_expense(payload, actor=principal.sub)


@router.get(
    "/expenses",
    response_model=Page[ExpenseOut],
    # Every budget role reads this: view, structure and book see the bookings.
    dependencies=[
        Depends(require_any_permission("budget.view", "budget.structure", "budget.book"))
    ],
    responses=_errors(401, 403, 404),
)
async def list_expenses(
    service: ServiceDep,
    expense_id: Annotated[UUID | None, Query(alias="id")] = None,
    budget_id: Annotated[UUID | None, Query(alias="budget")] = None,
    fiscal_year_id: Annotated[UUID | None, Query(alias="fiscalYear")] = None,
    account_id: Annotated[UUID | None, Query(alias="account")] = None,
    kind: Annotated[ExpenseKind | None, Query()] = None,
    application_id: Annotated[UUID | None, Query(alias="applicationId")] = None,
    unallocated: Annotated[bool, Query()] = False,
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
    """List bookings, filtered and sorted, with offset paging.

    ``id`` selects the exact booking for the deep link from the accounts tab.
    ``budget`` includes the subtree. ``kind`` is ``expense`` or ``income``.
    ``q`` searches the descriptions. ``amountMin`` and ``amountMax`` bound the
    amount. ``sort`` and ``order`` set the column sort.
    """
    return await service.list_expenses_paged(
        expense_id=expense_id,
        budget_id=budget_id,
        fiscal_year_id=fiscal_year_id,
        account_id=account_id,
        kind=kind,
        application_id=application_id,
        unallocated=unallocated,
        q=q,
        amount_min=amount_min,
        amount_max=amount_max,
        created_from=created_from,
        created_to=created_to,
        # ``sort`` is already Literal-validated, so it passes through
        # unchanged. The ``sort_map`` of the service knows all four columns.
        sort=sort,
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
    ids: Annotated[list[UUID] | None, Query()] = None,
) -> Response:
    """Export the filtered bookings as ``.xlsx``, with the same content as the list.

    The optional ``ids`` (#expenses-ux) restricts the export to the selected
    bookings. The route narrows the filtered page to those IDs, so the
    selection stays a subset of the current filter.
    """
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
    items = page.items
    if ids:
        wanted = set(ids)
        items = [e for e in items if e.id in wanted]
    data = build_expenses_workbook(items)
    await audit_record(
        service.session,
        actor=principal.sub,
        action=AuditAction.EXPORT,
        target_type="export",
        target_id="buchungen.xlsx",
        data={"rows": len(items)},
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
    """Update the amount or the description of a booking."""
    return await service.update_expense(expense_id, payload)


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
    """Transfer from one cost center to another.

    The transfer books an expense and an income in the same fiscal year.
    """
    return await service.create_transfer(payload, actor=principal.sub)


# Every budget role may read an invoice. A write needs budget.book.
_INVOICE_READ = Depends(require_any_permission("budget.view", "budget.structure", "budget.book"))


@router.get(
    "/invoices",
    response_model=Page[InvoiceOut],
    dependencies=[_INVOICE_READ],
    responses=_errors(401, 403),
)
async def list_invoices(
    service: ServiceDep,
    q: Annotated[str | None, Query()] = None,
    status: Annotated[InvoiceStatus | None, Query()] = None,
    gross_min: Annotated[Decimal | None, Query(alias="grossMin", ge=0)] = None,
    gross_max: Annotated[Decimal | None, Query(alias="grossMax", ge=0)] = None,
    issue_from: Annotated[str | None, Query(alias="issueFrom")] = None,
    issue_to: Annotated[str | None, Query(alias="issueTo")] = None,
    due_from: Annotated[str | None, Query(alias="dueFrom")] = None,
    due_to: Annotated[str | None, Query(alias="dueTo")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[InvoiceOut]:
    """List invoices with fuzzy search, filters and offset paging.

    The newest issue date comes first. ``q`` searches number, supplier and note.
    ``status`` is ``open`` or ``paid``. ``grossMin`` and ``grossMax`` bound the
    gross amount. ``issueFrom``/``issueTo`` and ``dueFrom``/``dueTo`` bound the
    dates.
    """
    return await service.list_invoices_paged(
        q=q,
        status=status,
        gross_min=gross_min,
        gross_max=gross_max,
        issue_from=issue_from,
        issue_to=issue_to,
        due_from=due_from,
        due_to=due_to,
        limit=limit,
        offset=offset,
    )


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


@router.post(
    "/invoices/parse",
    response_model=InvoiceParseResult,
    # Write permission: the import stores the original PDF and reads its data.
    dependencies=[Depends(_enforce_invoice_body)],
    responses=_errors(401, 403, 413, 415, 422, 503),
)
async def parse_invoice(
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("budget.book"))],
    file: Annotated[UploadFile, File()],
) -> InvoiceParseResult:
    """Parse a ZUGFeRD/Factur-X PDF into fields plus a file handle for the dialog.

    A PDF without valid Factur-X data yields 422 ``invoice_not_zugferd``. The
    UI then offers manual entry. A currency other than EUR yields 422
    ``invoice_currency_unsupported``.
    """
    data = await file.read()
    try:
        return await service.parse_invoice_file(data, filename=file.filename)
    except UnsupportedInvoiceCurrencyError as exc:
        raise ValidationProblem(
            f"Only EUR invoices are supported (got {exc.currency}).",
            code="invoice_currency_unsupported",
        ) from exc
    except NotZugferdError as exc:
        raise ValidationProblem(
            "No embedded ZUGFeRD/Factur-X data found.",
            code="invoice_not_zugferd",
        ) from exc


@router.post(
    "/invoices/file",
    response_model=InvoiceFileResult,
    # Write permission: the route stores the original PDF, also for a receipt
    # without ZUGFeRD data.
    dependencies=[Depends(_enforce_invoice_body)],
    responses=_errors(401, 403, 413, 415, 503),
)
async def upload_invoice_file(
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("budget.book"))],
    file: Annotated[UploadFile, File()],
) -> InvoiceFileResult:
    """Store a receipt PDF without ZUGFeRD parsing.

    The route returns a file handle for the entry dialog, so that a manually
    entered invoice also carries a receipt.
    """
    data = await file.read()
    return await service.store_invoice_file(data, filename=file.filename)


@router.get(
    "/invoices/{invoice_id}/file",
    dependencies=[_INVOICE_READ],
    responses=_errors(401, 403, 404, 503),
    response_class=Response,
)
async def get_invoice_file(invoice_id: UUID, service: ServiceDep) -> Response:
    """Stream the original receipt from the server.

    MinIO is internal, so the route serves no presigned URL. Hardening: the
    route does NOT trust the client-supplied ``file_mime`` on the serve path.
    The upload already enforces ``application/pdf``. Therefore the route forces
    the media type to ``application/pdf`` and adds ``Content-Disposition:
    attachment``. An HTML polyglot stored as a PDF then cannot render in the
    app origin.
    """
    data, _mime, name = await service.invoice_file_bytes(invoice_id)
    safe = "".join(c for c in name if c.isprintable() and c not in '"\\\r\n')
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@router.get(
    "/accounts/options",
    response_model=list[AccountOption],
    # Minimal choice with id and name and no IBAN, for the booking dropdowns. A
    # booker may read this without account.manage. The full account data stays
    # behind account.manage.
    dependencies=[Depends(require_any_permission("account.manage", "budget.book", "budget.view"))],
    responses=_errors(401, 403),
)
async def list_account_options(service: ServiceDep) -> list[AccountOption]:
    """List the active accounts as id and name without IBAN, for the booking form."""
    return await service.list_account_options()


@router.get(
    "/accounts",
    response_model=list[AccountOut],
    dependencies=[Depends(require_principal("account.manage"))],
    responses=_errors(401, 403),
)
async def list_accounts(service: ServiceDep) -> list[AccountOut]:
    """List the accounts with name and IBAN, gated by ``account.manage``."""
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


# Bank reconcile. Fetch, import and book move money and need ``budget.book``.
# Reading the staging list is open to every budget role. The admin sets the bank
# connection on the account, the endpoint and the BLZ, with account.manage. Each
# booker sets the personal credentials per account with budget.book.
@router.get(
    "/accounts/{account_id}/fints/credential",
    response_model=FintsCredentialStatus,
    dependencies=[Depends(require_principal("budget.book"))],
    responses=_errors(401, 403, 404),
)
async def fints_credential_status(
    account_id: UUID, service: BankServiceDep
) -> FintsCredentialStatus:
    """Check whether the booker already has own FinTS credentials for the account."""
    return await service.credential_status(account_id)


@router.put(
    "/accounts/{account_id}/fints/credential",
    response_model=FintsCredentialStatus,
    dependencies=[
        Depends(require_principal("budget.book")),
        Depends(rate_limit_fints),
    ],
    responses=_errors(401, 403, 404, 422, 429, 503),
)
async def set_fints_credential(
    account_id: UUID, payload: FintsCredentialIn, service: BankServiceDep
) -> FintsCredentialStatus:
    """Create or replace the personal FinTS credentials with login and PIN.

    The booker runs this on the first connect in the booking tab. The PIN is
    write-only and stored encrypted.
    """
    return await service.set_credential(account_id, payload)


@router.delete(
    "/accounts/{account_id}/fints/credential",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("budget.book"))],
    responses=_errors(401, 403, 404),
)
async def delete_fints_credential(account_id: UUID, service: BankServiceDep) -> None:
    """Delete the FinTS credentials of the calling booker for the account."""
    await service.delete_credential(account_id)


@router.post(
    "/accounts/{account_id}/fints/sync",
    response_model=BankSyncResult,
    dependencies=[
        Depends(require_principal("budget.book")),
        Depends(rate_limit_fints),
    ],
    responses=_errors(401, 403, 404, 409, 422, 429, 503),
)
async def fints_sync(account_id: UUID, service: BankServiceDep) -> BankSyncResult:
    """Start a FinTS sync. It stages the transactions or requests a TAN (``needs_tan``)."""
    return await service.sync_account(account_id)


@router.post(
    "/accounts/{account_id}/fints/sessions/{session_token}/tan",
    response_model=BankSyncResult,
    dependencies=[
        Depends(require_principal("budget.book")),
        Depends(rate_limit_fints),
    ],
    responses=_errors(401, 403, 404, 409, 422, 429, 503),
)
async def fints_submit_tan(
    account_id: UUID,
    session_token: UUID,
    payload: BankTanRequest,
    service: BankServiceDep,
) -> BankSyncResult:
    """Resume a pending TAN session. An empty ``tan`` makes a decoupled poll."""
    return await service.submit_tan(account_id, session_token, payload.tan)


@router.post(
    "/accounts/{account_id}/statement/import",
    response_model=BankImportResult,
    dependencies=[
        Depends(require_principal("budget.book")),
        Depends(rate_limit_fints),
        Depends(_enforce_invoice_body),
    ],
    responses=_errors(401, 403, 413, 422, 429, 503),
)
async def import_statement_file(
    account_id: UUID,
    service: BankServiceDep,
    file: Annotated[UploadFile, File()],
) -> BankImportResult:
    """Upload a CAMT.053/MT940 file and stage its transactions."""
    data = await file.read()
    return await service.import_file(account_id, data, filename=file.filename)


@router.get(
    "/statement-lines",
    response_model=Page[StatementLineOut],
    dependencies=[
        Depends(require_any_permission("budget.view", "budget.structure", "budget.book"))
    ],
    responses=_errors(401, 403),
)
async def list_statement_lines(
    service: BankServiceDep,
    account_id: Annotated[UUID | None, Query(alias="account")] = None,
    state: Annotated[
        Literal["unmatched", "suggested", "matched", "ignored"] | None, Query()
    ] = None,
    linked: Annotated[bool | None, Query()] = None,
    include_ignored: Annotated[bool, Query(alias="includeIgnored")] = True,
    kind: Annotated[ExpenseKind | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    date_from: Annotated[str | None, Query(alias="dateFrom")] = None,
    date_to: Annotated[str | None, Query(alias="dateTo")] = None,
    sort: Annotated[Literal["date", "amount"] | None, Query()] = None,
    order: Annotated[Literal["asc", "desc"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[StatementLineOut]:
    """List the staged bank transactions, filtered and offset-paged.

    The filters are ``account``, ``state``, ``kind``, ``q`` (counterparty, IBAN
    or purpose) and the date range ``dateFrom``/``dateTo``. ``sort`` takes date
    or amount. ``includeIgnored`` = false hides the set-aside lines when the
    request gives no explicit ``state``, which is the All view.
    """
    return await service.list_lines_paged(
        account_id=account_id,
        state=state,
        linked=linked,
        include_ignored=include_ignored,
        kind=kind,
        q=q,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/statement-lines/{line_id}",
    response_model=StatementLineDetail,
    dependencies=[
        Depends(require_any_permission("budget.view", "budget.structure", "budget.book"))
    ],
    responses=_errors(401, 403, 404),
)
async def get_statement_line(line_id: UUID, service: BankServiceDep) -> StatementLineDetail:
    """Return one staged transaction for the diagnostic detail view.

    The response holds the raw parser payload and the idempotency key. It shows
    the source format and the batch metadata.
    """
    return await service.get_line(line_id)


@router.post(
    "/statement-lines/{line_id}/confirm",
    response_model=ExpenseOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_principal("budget.book"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def confirm_statement_line(
    line_id: UUID, payload: ConfirmLineRequest, service: BankServiceDep
) -> ExpenseOut:
    """Book a transaction: a new booking on ``budgetId`` or onto ``matchExpenseId``."""
    return await service.confirm_line(line_id, payload)


@router.post(
    "/statement-lines/{line_id}/ignore",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("budget.reconcile_ignore"))],
    responses=_errors(401, 403, 404, 422),
)
async def ignore_statement_line(
    line_id: UUID, service: BankServiceDep, payload: IgnoreLineRequest | None = None
) -> None:
    """Mark a transaction as irrelevant. The line stays for the idempotent import.

    The dedicated ``budget.reconcile_ignore`` permission gates this route,
    because the action is audit-sensitive. The audit log records the optional
    ``reason``.
    """
    await service.ignore_line(line_id, reason=payload.reason if payload else None)


@router.post(
    "/statement-lines/{line_id}/reactivate",
    response_model=StatementLineOut,
    dependencies=[Depends(require_principal("budget.reconcile_ignore"))],
    responses=_errors(401, 403, 404, 422),
)
async def reactivate_statement_line(line_id: UUID, service: BankServiceDep) -> StatementLineOut:
    """Undo an ignore: return an ignored transaction to the open reconcile queue."""
    return await service.reactivate_line(line_id)


@router.post(
    "/statement-lines/{line_id}/unlink",
    response_model=StatementLineOut,
    dependencies=[Depends(require_principal("budget.book"))],
    responses=_errors(401, 403, 404),
)
async def unlink_statement_line(line_id: UUID, service: BankServiceDep) -> StatementLineOut:
    """Unlink a transaction from a booking.

    The route removes the allocation and reopens the transaction. The booking
    remains.
    """
    return await service.unlink_line(line_id)


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
    """List the fiscal years of the top-level budget above this node.

    Any node is allowed. A node below the top level resolves to its top-level
    ancestor, because a scoped root is often a sub cost center. The caller
    needs the full view or the gremium scope on the node.
    """
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
    """Create a fiscal year.

    The fiscal years of one top budget must stay disjoint. An overlap gives 422.
    """
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
    """Update a fiscal year. The route checks the disjointness again."""
    return await service.update_fiscal_year(budget_id, fiscal_year_id, payload)


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
    """Set the top-down allocation. A children sum above the parent gives 422."""
    return await service.set_allocation(budget_id, fiscal_year_id, payload)


@router.post(
    "/applications/{application_id}/assign-budget",
    response_model=AssignBudgetOut,
    dependencies=[Depends(require_principal("application.manage"))],
    responses=_errors(400, 401, 403, 404, 422),
)
async def assign_budget(
    application_id: UUID, payload: AssignBudgetRequest, service: ServiceDep
) -> AssignBudgetOut:
    """Assign an application to a cost center and set the fiscal year.

    ``budgetId=null`` clears the assignment.
    """
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
    """Move an application to another fiscal year.

    The route checks that the fiscal year stays consistent with the top budget.
    """
    return await service.move_fiscal_year(application_id, payload)
