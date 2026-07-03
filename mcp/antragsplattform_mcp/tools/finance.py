"""Finance tools: flat expense listing, invoices, FinTS bank reconcile, staged
statement lines, and sub-bookings.

FinTS acts under the booker's PERSONAL online-banking login; a `needs_tan` response
requires a HUMAN to complete PSD2/SCA — an agent cannot finish a TAN flow alone.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..client import ApiError
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params

group = ToolGroup()


def _file_part(file_path: str) -> dict[str, Any]:
    """Read a local file into an httpx multipart ``files=`` dict (backend field name ``file``)."""
    p = Path(file_path).expanduser()
    if not p.is_file():
        raise ApiError(400, f"file not found: {file_path!r}")
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return {"file": (p.name, p.read_bytes(), mime)}


@group.tool
async def list_expenses(
    budget: str | None = None,
    fiscal_year: str | None = None,
    application_id: str | None = None,
    kind: Literal["expense", "income"] | None = None,
    q: str | None = None,
    amount_min: str | None = None,
    amount_max: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    sort: Literal["createdAt", "amount", "invoiceDate", "paymentDate"] | None = None,
    order: Literal["asc", "desc"] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List bookings across all cost centres (flat, filtered, offset-paged). ``budget`` includes
    the subtree; dates are ISO; amounts are decimal strings. Requires budget.view."""
    return await api().get(
        "/expenses",
        params=params(
            budget=budget, fiscalYear=fiscal_year, applicationId=application_id,
            kind=kind, q=q, amountMin=amount_min, amountMax=amount_max,
            createdFrom=created_from, createdTo=created_to, sort=sort, order=order,
            limit=limit, offset=offset,
        ),
    )


@group.tool
async def list_account_options() -> dict:
    """List accounts as id+name for booking dropdowns (no IBAN). Shows ``fintsConfigured`` and
    whether the requesting booker already has personal FinTS credentials. Readable for bookers
    (budget.book/budget.view) without account-master rights."""
    return await api().get("/accounts/options")


# --- invoices
@group.tool
async def list_invoices(
    q: str | None = None,
    status: Literal["open", "paid"] | None = None,
    gross_min: str | None = None,
    gross_max: str | None = None,
    issue_from: str | None = None,
    issue_to: str | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List invoices (fuzzy ``q`` over number/supplier/note; filter status/gross-range/date;
    offset-paged, newest issue date first). Requires budget.view/.book."""
    return await api().get(
        "/invoices",
        params=params(
            q=q, status=status, grossMin=gross_min, grossMax=gross_max,
            issueFrom=issue_from, issueTo=issue_to, dueFrom=due_from, dueTo=due_to,
            limit=limit, offset=offset,
        ),
    )


@group.tool
async def get_invoice(invoice_id: str) -> dict:
    """Fetch one invoice (header data + whether an original file is attached)."""
    return await api().get(f"/invoices/{invoice_id}")


@group.tool
async def create_invoice(invoice: S.InvoiceCreate) -> dict:
    """Create an invoice (grossAmount required). ``fileToken`` from parse_invoice /
    upload_invoice_file links the stored original PDF. Requires budget.book."""
    return await api().post("/invoices", json=dump_create(invoice))


@group.tool
async def update_invoice(invoice_id: str, patch: S.InvoiceUpdate) -> dict:
    """Patch an invoice (amount/status/dates/supplier/note). Requires budget.book."""
    return await api().patch(f"/invoices/{invoice_id}", json=dump_patch(patch))


@group.tool
async def delete_invoice(invoice_id: str) -> dict:
    """Delete an invoice. Requires budget.book."""
    return await api().delete(f"/invoices/{invoice_id}")


@group.tool
async def parse_invoice(file_path: str) -> dict:
    """Parse a local ZUGFeRD/Factur-X PDF: extract header fields + store the original. Returns the
    parsed fields plus a ``fileToken`` to pass to create_invoice. Requires budget.book."""
    return await api().post("/invoices/parse", files=_file_part(file_path))


@group.tool
async def upload_invoice_file(file_path: str) -> dict:
    """Upload a local invoice document (non-ZUGFeRD also fine); returns a ``fileToken`` for
    create_invoice. Requires budget.book."""
    return await api().post("/invoices/file", files=_file_part(file_path))


# --- FinTS bank reconcile
@group.tool
async def get_fints_credential(account_id: str) -> dict:
    """Connection status for the requesting booker on an account: FinTS-capable? personal login
    stored? lock cooldown? Requires budget.book."""
    return await api().get(f"/accounts/{account_id}/fints/credential")


@group.tool
async def set_fints_credential(account_id: str, credential: S.FintsCredentialIn) -> dict:
    """Store/replace the booker's personal FinTS login+PIN for an account (PIN write-only, stored
    encrypted). The account must already have a FinTS connection (endpoint+BLZ, set via
    update_account). Requires budget.book."""
    return await api().put(
        f"/accounts/{account_id}/fints/credential", json=dump_create(credential)
    )


@group.tool
async def delete_fints_credential(account_id: str) -> dict:
    """Remove the booker's personal FinTS credential for an account. Requires budget.book."""
    return await api().delete(f"/accounts/{account_id}/fints/credential")


@group.tool
async def fints_sync(account_id: str) -> dict:
    """Start a FinTS transaction sync. Returns status='done' (imported/duplicates staged) OR
    status='needs_tan' (sessionToken + challenge → a human approves/enters the TAN, then call
    fints_submit_tan). 409 means the access is locked — do not retry. Requires budget.book +
    a stored credential."""
    return await api().post(f"/accounts/{account_id}/fints/sync")


@group.tool
async def fints_submit_tan(account_id: str, session_token: str, tan: str = "") -> dict:
    """Resume a pending FinTS sync with the TAN (empty ``tan`` = decoupled pushTAN poll: 'approved
    in the app yet?'). Returns done or needs_tan again. Requires budget.book."""
    return await api().post(
        f"/accounts/{account_id}/fints/sessions/{session_token}/tan", json={"tan": tan}
    )


@group.tool
async def import_statement_file(account_id: str, file_path: str) -> dict:
    """Import a local CAMT.053/MT940 statement file for an account → stages transactions
    (idempotent). Returns imported/duplicates. No bank/TAN needed. Requires budget.book."""
    return await api().post(
        f"/accounts/{account_id}/statement/import", files=_file_part(file_path)
    )


# --- staged statement lines → bookings
@group.tool
async def list_statement_lines(
    account: str | None = None,
    state: Literal["unmatched", "suggested", "matched", "ignored"] | None = None,
    linked: bool | None = None,
    kind: Literal["expense", "income"] | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: Literal["date", "amount"] | None = None,
    order: Literal["asc", "desc"] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List staged bank transactions, filtered + offset-paginated. Returns a page
    ``{items, total, limit, offset}``; each item carries a signed amount, decoded counterparty
    and a suggested cost centre. Filters: ``account``, ``state``, ``linked`` (true = already
    booked, false = open), ``kind`` (expense/income), ``q`` (counterparty/IBAN/purpose),
    ``date_from``/``date_to`` (YYYY-MM-DD over value/booking date); ``sort`` = date|amount.
    Requires budget.view/.book."""
    return await api().get(
        "/statement-lines",
        params=params(
            account=account, state=state, linked=linked, kind=kind, q=q,
            dateFrom=date_from, dateTo=date_to, sort=sort, order=order,
            limit=limit, offset=offset,
        ),
    )


@group.tool
async def confirm_statement_line(line_id: str, confirm: S.ConfirmLineRequest) -> dict:
    """Book a staged transaction into a booking: new booking on ``budgetId`` OR attach to an
    existing ``matchExpenseId`` (kind derives from the sign). Requires budget.book."""
    return await api().post(
        f"/statement-lines/{line_id}/confirm", json=dump_create(confirm)
    )


@group.tool
async def ignore_statement_line(line_id: str, reason: str | None = None) -> dict:
    """Mark a staged transaction as irrelevant (kept for idempotent re-import). ``reason`` is an
    optional free-text note recorded in the audit log. Audit-sensitive — requires the dedicated
    budget.reconcile_ignore permission."""
    return await api().post(
        f"/statement-lines/{line_id}/ignore", json={"reason": reason} if reason else None
    )


@group.tool
async def reactivate_statement_line(line_id: str) -> dict:
    """Undo an ignore (#konten): return an ignored transaction to the open reconcile queue
    (``unmatched``). Requires budget.reconcile_ignore."""
    return await api().post(f"/statement-lines/{line_id}/reactivate")


@group.tool
async def unlink_statement_line(line_id: str) -> dict:
    """Undo a transaction↔booking link (#konten): removes the allocation and reopens the
    transaction (``unmatched``). The booking itself is kept. Requires budget.book."""
    return await api().post(f"/statement-lines/{line_id}/unlink")


# --- sub-bookings
@group.tool
async def list_sub_bookings(expense_id: str) -> dict:
    """List the sub-bookings of a booking (#subbookings). A booking can be broken down into
    sub-bookings (same schema); they inherit cost-centre/account/fiscal-year/kind from the
    parent and the parent amount equals their sum. Requires budget.view/.book."""
    return await api().get(f"/budget-expenses/{expense_id}/sub-bookings")


@group.tool
async def import_sub_bookings(expense_id: str, file_path: str) -> dict:
    """Add sub-bookings to a booking from a local CAMT.053/MT940 file (#subbookings). Each
    same-direction line becomes a child inheriting the parent's cost-centre/account/fiscal-year/
    kind; the parent amount is recomputed to their sum. Idempotent (re-upload skips duplicates);
    EUR-only; transfer/sub-booking parents are rejected. Requires budget.book."""
    return await api().post(
        f"/budget-expenses/{expense_id}/sub-bookings/import", files=_file_part(file_path)
    )


def register(mcp: FastMCP) -> None:
    """Register the expenses/invoices/FinTS tool group."""
    group.register(mcp)
