"""Finance tools for expenses, invoices, FinTS reconcile, statement lines, sub-bookings.

FinTS acts under the PERSONAL online-banking login of the booker. A `needs_tan` response
needs a HUMAN to complete PSD2/SCA. An agent cannot finish a TAN flow alone.
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
    """Read a local file into an httpx `files=` dict under the backend field name `file`."""
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
    """List the bookings of all cost centers as a flat, filtered, offset-paged list.

    Requires budget.view.

    Args:
        budget: A cost center id. The list also covers its subtree.
        amount_min: A decimal string.
        amount_max: A decimal string.
        created_from: An ISO date.
        created_to: An ISO date.
    """
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
    """List the accounts as id and name for the booking dropdowns, without the IBAN.

    Each entry shows `fintsConfigured`. It also tells whether the booker who asks
    already holds a personal FinTS credential. A booker with budget.book or
    budget.view can read this without the account master permission.
    """
    return await api().get("/accounts/options")


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
    """List the invoices, offset-paged, with the newest issue date first.

    Filter by status, by gross range and by date. Requires budget.view or budget.book.

    Args:
        q: A fuzzy search over the invoice number, the supplier and the note.
    """
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
    """Get one invoice with its header data and a flag for an attached original file."""
    return await api().get(f"/invoices/{invoice_id}")


@group.tool
async def create_invoice(invoice: S.InvoiceCreate) -> dict:
    """Create an invoice.

    The field `grossAmount` is required. A `fileToken` from `parse_invoice` or
    `upload_invoice_file` links the stored original PDF. Requires budget.book.
    """
    return await api().post("/invoices", json=dump_create(invoice))


@group.tool
async def update_invoice(invoice_id: str, patch: S.InvoiceUpdate) -> dict:
    """Patch the amount, status, dates, supplier or note of an invoice.

    Requires budget.book.
    """
    return await api().patch(f"/invoices/{invoice_id}", json=dump_patch(patch))


@group.tool
async def delete_invoice(invoice_id: str) -> dict:
    """Delete an invoice. Requires budget.book."""
    return await api().delete(f"/invoices/{invoice_id}")


@group.tool
async def parse_invoice(file_path: str) -> dict:
    """Parse a local ZUGFeRD or Factur-X PDF and store the original.

    The call reads the header fields out of the file. Requires budget.book.

    Returns:
        The parsed fields and a `fileToken` to pass to `create_invoice`.
    """
    return await api().post("/invoices/parse", files=_file_part(file_path))


@group.tool
async def upload_invoice_file(file_path: str) -> dict:
    """Upload a local invoice document.

    The document does not have to be a ZUGFeRD file. Requires budget.book.

    Returns:
        A `fileToken` to pass to `create_invoice`.
    """
    return await api().post("/invoices/file", files=_file_part(file_path))


@group.tool
async def get_fints_credential(account_id: str) -> dict:
    """Get the FinTS connection status of the booker who asks, for one account.

    The answer tells whether the account speaks FinTS, whether a personal login is
    stored, and whether a lock cooldown runs. Requires budget.book.
    """
    return await api().get(f"/accounts/{account_id}/fints/credential")


@group.tool
async def set_fints_credential(account_id: str, credential: S.FintsCredentialIn) -> dict:
    """Store or replace the personal FinTS login and PIN of the booker for an account.

    The PIN is write-only and the server stores it encrypted. The account must already
    hold a FinTS connection with an endpoint and a BLZ, set through `update_account`.
    Requires budget.book.
    """
    return await api().put(
        f"/accounts/{account_id}/fints/credential", json=dump_create(credential)
    )


@group.tool
async def delete_fints_credential(account_id: str) -> dict:
    """Remove the personal FinTS credential of the booker for an account.

    Requires budget.book.
    """
    return await api().delete(f"/accounts/{account_id}/fints/credential")


@group.tool
async def fints_sync(account_id: str) -> dict:
    """Start a FinTS transaction sync.

    A status of `done` means the sync staged the imported and the duplicate
    transactions. A status of `needs_tan` returns a `sessionToken` and a challenge. A
    human then approves or enters the TAN. Call `fints_submit_tan` after that. A 409
    means the access is locked. Do not retry after a 409. Requires budget.book and a
    stored credential.
    """
    return await api().post(f"/accounts/{account_id}/fints/sync")


@group.tool
async def fints_submit_tan(account_id: str, session_token: str, tan: str = "") -> dict:
    """Resume a pending FinTS sync with the TAN.

    An empty `tan` polls a decoupled pushTAN and asks whether the human approved the
    sync in the app. The call returns `done` or `needs_tan` again.
    Requires budget.book.
    """
    return await api().post(
        f"/accounts/{account_id}/fints/sessions/{session_token}/tan", json={"tan": tan}
    )


@group.tool
async def import_statement_file(account_id: str, file_path: str) -> dict:
    """Import a local CAMT.053 or MT940 statement file for an account.

    The import stages the transactions and is idempotent. It reports the imported and
    the duplicate lines. It needs no bank connection and no TAN. Requires budget.book.
    """
    return await api().post(
        f"/accounts/{account_id}/statement/import", files=_file_part(file_path)
    )


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
    """List the staged bank transactions, filtered and offset-paged.

    Each item carries a signed amount, a decoded counterparty and a suggested cost
    center. Requires budget.view or budget.book.

    Args:
        linked: True lists the transactions that are already booked. False lists the
            open ones.
        q: A search over the counterparty, the IBAN and the purpose.
        date_from: A YYYY-MM-DD date. It matches the value date and the booking date.
        date_to: A YYYY-MM-DD date. It matches the value date and the booking date.

    Returns:
        A page of the shape `{items, total, limit, offset}`.
    """
    return await api().get(
        "/statement-lines",
        params=params(
            account=account, state=state, linked=linked, kind=kind, q=q,
            dateFrom=date_from, dateTo=date_to, sort=sort, order=order,
            limit=limit, offset=offset,
        ),
    )


@group.tool
async def get_statement_line(line_id: str) -> dict:
    """Get one staged transaction with its `rawPayload` and its `idempotencyKey`.

    The `rawPayload` holds the parser fields of the source format and the batch
    metadata. Use this diagnostic view to tell whether a line comes from MT940 or from
    CAMT. It also shows whether a batch booking carried sub-transactions.
    Requires budget.view or budget.book.
    """
    return await api().get(f"/statement-lines/{line_id}")


@group.tool
async def confirm_statement_line(line_id: str, confirm: S.ConfirmLineRequest) -> dict:
    """Turn a staged transaction into a booking.

    Give a `budgetId` to create a new booking. Give a `matchExpenseId` to attach the
    transaction to an existing booking. The sign of the amount gives the kind.
    Requires budget.book.
    """
    return await api().post(
        f"/statement-lines/{line_id}/confirm", json=dump_create(confirm)
    )


@group.tool
async def ignore_statement_line(line_id: str, reason: str | None = None) -> dict:
    """Mark a staged transaction as irrelevant.

    The server keeps the transaction so that a second import stays idempotent. This
    action is audit-sensitive. It needs the dedicated budget.reconcile_ignore
    permission.

    Args:
        reason: A free-text note. The audit log records it.
    """
    return await api().post(
        f"/statement-lines/{line_id}/ignore", json={"reason": reason} if reason else None
    )


@group.tool
async def reactivate_statement_line(line_id: str) -> dict:
    """Undo an ignore (#konten).

    The transaction goes back to the open reconcile queue in the state `unmatched`.
    Requires budget.reconcile_ignore.
    """
    return await api().post(f"/statement-lines/{line_id}/reactivate")


@group.tool
async def unlink_statement_line(line_id: str) -> dict:
    """Undo the link between a transaction and a booking (#konten).

    The call removes the allocation and reopens the transaction in the state
    `unmatched`. The booking itself stays. Requires budget.book.
    """
    return await api().post(f"/statement-lines/{line_id}/unlink")


@group.tool
async def list_sub_bookings(expense_id: str) -> dict:
    """List the sub-bookings of a booking (#subbookings).

    A booking can break down into sub-bookings with the same schema. A sub-booking
    inherits the cost center, the account, the fiscal year and the kind of the parent.
    The amount of the parent equals the sum of the sub-bookings.
    Requires budget.view or budget.book.
    """
    return await api().get(f"/budget-expenses/{expense_id}/sub-bookings")


@group.tool
async def import_sub_bookings(expense_id: str, file_path: str) -> dict:
    """Add sub-bookings to a booking from a local CAMT.053 or MT940 file (#subbookings).

    Each line with the same direction becomes a child. A child inherits the cost
    center, the account, the fiscal year and the kind of the parent. The server then
    recomputes the parent amount to the sum of the children.

    The import is idempotent and a second upload skips the duplicates. It accepts EUR
    only. The server rejects a transfer or a sub-booking as the parent.
    Requires budget.book.
    """
    return await api().post(
        f"/budget-expenses/{expense_id}/sub-bookings/import", files=_file_part(file_path)
    )


def register(mcp: FastMCP) -> None:
    """Register the expenses, invoices and FinTS tool group."""
    group.register(mcp)
