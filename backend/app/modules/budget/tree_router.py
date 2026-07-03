"""Budget-tree API router (all principal-only, fail-closed RBAC).

Permission scope: tree reads need ``budget.view`` (or gremium scope); structure
mutations (nodes, fiscal years, allocations) need ``budget.structure``;
bookings/transfers move money and need ``budget.book``; assign/move-fiscal-year
need ``application.manage``. Constraint violations (children <= parent,
fiscal-year disjointness) yield 422; deleting with children/allocations 409.
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
    StatementLineOut,
    SubBookingCreate,
    TransferCreate,
    TransferOut,
)
from app.shared.antiabuse import body_cap, rate_limit_fints
from app.shared.errors import ForbiddenError, ProblemDetail, ValidationProblem
from app.shared.paging import Page

router = APIRouter(tags=["budget"])

# Early (Content-Length) body cap for receipt uploads before FastAPI buffers —
# defense in depth next to the nginx cap and the in-app size check.
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
    # Storage is used only by the invoice import; ``actor`` = principal ``sub``
    # for the audit trail of money mutations (all budget endpoints are authed).
    storage = getattr(request.app.state, "object_storage", None)
    return BudgetTreeService(session, storage=storage, settings=settings, actor=principal.sub)


ServiceDep = Annotated[BudgetTreeService, Depends(get_budget_tree_service)]


async def get_bank_service(
    session: DbSession,
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> BankService:
    """Build the bank service — ``actor`` for the audit trail; ``principal_id``
    scopes personal credentials and TAN sessions."""
    from sqlalchemy import select

    from app.modules.auth.models import Principal as PrincipalRow

    principal_id = await session.scalar(
        select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub)
    )
    return BankService(
        session, settings=settings, actor=principal.sub, principal_id=principal_id
    )


BankServiceDep = Annotated[BankService, Depends(get_bank_service)]


# Global full view of the budget tab — each of these permissions shows ALL;
# without one, the gremium scope (view_gremium_id) applies.
_FULL_VIEW_PERMS = ("budget.view", "budget.structure", "budget.book")


def _has_full_view(principal: Principal) -> bool:
    return any(principal.has(p) for p in _FULL_VIEW_PERMS)


async def _member_gremium_ids(service: BudgetTreeService, sub: str) -> set[UUID]:
    from app.modules.admin.gremium_roles import gremium_member_ids

    return await gremium_member_ids(service.session, sub)


async def _require_node_view(
    service: BudgetTreeService, principal: Principal, budget_id: UUID
) -> None:
    """Full view OR the node lies in a subtree assigned to a member gremium."""
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
    """Cost-centre tree (with ``pathKey``, allocated/committed/available per fiscal year).

    Full view with ``budget.view``/``structure``/``book``; otherwise gremium
    scope: only subtrees whose ``viewGremiumId`` matches a member gremium, as
    roots. Neither: empty list."""
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

    ``gremium`` / ``node`` (subtree selection) / ``fiscalYear`` mirror the
    active dashboard filters; ``node`` exports only that node plus subtree.
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
    """Create a cost centre (top level with ``gremiumId``; children with ``parentId``)."""
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
    """Update a cost centre (name/active flag)."""
    return await service.update_node(budget_id, payload)


@router.delete(
    "/budgets/{budget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("budget.structure"))],
    responses=_errors(401, 403, 404, 409),
)
async def delete_budget_node(budget_id: UUID, service: ServiceDep) -> None:
    """Delete a cost centre (only without children/allocations — 409 otherwise)."""
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
    """List applications of this cost centre + subtree, optionally fiscal-year-filtered.

    Full view or gremium scope on the node."""
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
    """List standalone expenses of this cost centre + subtree, optionally per fiscal year.

    Full view or gremium scope on the node."""
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
    """Book an expense without an application against cost centre + fiscal year."""
    return await service.create_expense(budget_id, payload, actor=principal.sub)


@router.delete(
    "/budget-expenses/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("budget.book"))],
    responses=_errors(401, 403, 404),
)
async def delete_budget_expense(expense_id: UUID, service: ServiceDep) -> None:
    """Delete a booked expense/income."""
    await service.delete_expense(expense_id)


# ---------------------------------------------------------------- sub-bookings
@router.get(
    "/budget-expenses/{expense_id}/sub-bookings",
    response_model=list[ExpenseOut],
    dependencies=[
        Depends(require_any_permission("budget.view", "budget.structure", "budget.book"))
    ],
    responses=_errors(401, 403, 404),
)
async def list_sub_bookings(expense_id: UUID, service: ServiceDep) -> list[ExpenseOut]:
    """List sub-bookings of a booking — expanding in the bookings tab."""
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
    """Create a sub-booking manually — inherits account/cost centre/fiscal year/kind."""
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
    """Create sub-bookings from a CAMT.053/MT940 file. Children inherit
    account/cost centre/fiscal year/kind from the parent; parent amount = sum of children."""
    data = await file.read()
    return await service.import_sub_bookings(
        expense_id, data, filename=file.filename, actor=principal.sub
    )


# -------------------------------------------------------- expenses (flat tab)
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
    """Book an expense/income: standalone (``budgetId``) or bound to an application
    (``applicationId`` — inherits cost centre + fiscal year, replaces its binding)."""
    return await service.book_expense(payload, actor=principal.sub)


@router.get(
    "/expenses",
    response_model=Page[ExpenseOut],
    # Reads for every budget role: view/structure/book see the bookings list.
    dependencies=[
        Depends(require_any_permission("budget.view", "budget.structure", "budget.book"))
    ],
    responses=_errors(401, 403, 404),
)
async def list_expenses(
    service: ServiceDep,
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
    """List bookings filtered + sorted + offset-paged. ``budget`` includes the
    subtree; ``kind`` = ``expense``/``income``; ``q`` searches descriptions;
    ``amountMin``/``amountMax`` = amount range; ``sort``/``order`` = column sort."""
    return await service.list_expenses_paged(
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
        # ``sort`` is already Literal-validated — pass through unchanged; the
        # service's ``sort_map`` knows all four columns.
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
) -> Response:
    """Export filtered bookings as ``.xlsx`` — same content as the list."""
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
    """Update a booking's amount/description."""
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
    """Transfer cost centre to cost centre (expense + income, same fiscal year)."""
    return await service.create_transfer(payload, actor=principal.sub)


# ------------------------------------------------------------------- invoices
# Reads: every budget role; writes: budget.book.
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
    """List invoices fuzzy-searched + filtered + offset-paged (newest issue date
    first). ``q`` searches number/supplier/note; ``status`` = ``open``/``paid``;
    ``grossMin``/``grossMax`` = gross range; ``issueFrom``/``issueTo`` and
    ``dueFrom``/``dueTo`` = date ranges."""
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
    """Parse a ZUGFeRD/Factur-X PDF: fields + file handle for the dialog.

    No valid Factur-X yields 422 ``invoice_not_zugferd`` (UI offers manual
    entry); non-EUR currency yields 422 ``invoice_currency_unsupported``.
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
    # Write permission: stores the original PDF (also for non-ZUGFeRD receipts).
    dependencies=[Depends(_enforce_invoice_body)],
    responses=_errors(401, 403, 413, 415, 503),
)
async def upload_invoice_file(
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("budget.book"))],
    file: Annotated[UploadFile, File()],
) -> InvoiceFileResult:
    """Store a receipt PDF without ZUGFeRD parsing: file handle for the entry
    dialog so manually entered invoices also carry a receipt."""
    data = await file.read()
    return await service.store_invoice_file(data, filename=file.filename)


@router.get(
    "/invoices/{invoice_id}/file",
    dependencies=[_INVOICE_READ],
    responses=_errors(401, 403, 404, 503),
    response_class=Response,
)
async def get_invoice_file(invoice_id: UUID, service: ServiceDep) -> Response:
    """Stream the original receipt server-side (MinIO is internal — no presigned URL).

    Hardening: the client-supplied ``file_mime`` is NOT trusted on the serve
    path. Uploads already enforce ``application/pdf``, so the media type is
    forced to ``application/pdf`` and served with ``Content-Disposition:
    attachment`` — an HTML polyglot stored as PDF cannot render in the app
    origin."""
    data, _mime, name = await service.invoice_file_bytes(invoice_id)
    safe = "".join(c for c in name if c.isprintable() and c not in '"\\\r\n')
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


# ------------------------------------------------------------------- accounts
@router.get(
    "/accounts/options",
    response_model=list[AccountOption],
    # Minimal choice (id+name, no IBAN) for booking dropdowns — bookers may read
    # this without account.manage. Full account data stays account.manage.
    dependencies=[Depends(require_any_permission("account.manage", "budget.book", "budget.view"))],
    responses=_errors(401, 403),
)
async def list_account_options(service: ServiceDep) -> list[AccountOption]:
    """List active accounts as id+name (no IBAN) — for booking selection."""
    return await service.list_account_options()


@router.get(
    "/accounts",
    response_model=list[AccountOut],
    dependencies=[Depends(require_principal("account.manage"))],
    responses=_errors(401, 403),
)
async def list_accounts(service: ServiceDep) -> list[AccountOut]:
    """List accounts (name + IBAN) — requires ``account.manage``."""
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


# --------------------------------------------------------------- bank reconcile
# Fetch/import/book move money -> ``budget.book``; reading the staging list is
# open to every budget role. The bank connection (endpoint/BLZ) on the account
# is set by the admin (account.manage); personal credentials are set by each
# booker (budget.book) per account.
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
    """Create/replace personal FinTS credentials (login + PIN) — first connect
    in the booking tab. PIN is write-only, encrypted."""
    return await service.set_credential(account_id, payload)


@router.delete(
    "/accounts/{account_id}/fints/credential",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_principal("budget.book"))],
    responses=_errors(401, 403, 404),
)
async def delete_fints_credential(account_id: UUID, service: BankServiceDep) -> None:
    """Delete own FinTS credentials for the account."""
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
    """Start a FinTS sync: stage transactions OR request a TAN (``needs_tan``)."""
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
    """Resume a pending TAN session — empty ``tan`` = decoupled poll."""
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
    """List staged bank transactions, filtered + offset-paged. Filters:
    ``account``, ``state``, ``kind``, ``q`` (counterparty/IBAN/purpose), date
    range (``dateFrom``/``dateTo``); ``sort`` = date/amount. ``includeIgnored``
    = false hides set-aside lines when no explicit ``state`` is given (Alle view)."""
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
    """Book a transaction: new booking against ``budgetId`` OR onto ``matchExpenseId``."""
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
    """Mark a transaction as irrelevant — it is kept (idempotent import).

    Gated by the dedicated ``budget.reconcile_ignore`` permission (audit-sensitive);
    an optional ``reason`` is recorded in the audit log."""
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
    """Unlink transaction from booking: remove the allocation, reopen the
    transaction. The booking remains."""
    return await service.unlink_line(line_id)


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
    """List fiscal years — any node allowed; non-top-level resolves to its
    top-level ancestor (scoped roots are often sub cost centres). Full view or
    gremium scope on the node."""
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
    """Create a fiscal year (disjoint per top budget — 422 otherwise)."""
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
    """Update a fiscal year (disjointness re-checked)."""
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
    """Set the top-down allocation (422 if the children's sum exceeds the parent)."""
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
    """Assign an application to a cost centre; sets the fiscal year (``budgetId=null`` clears)."""
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
    """Move an application to another fiscal year (consistency with the top budget checked)."""
    return await service.move_fiscal_year(application_id, payload)
