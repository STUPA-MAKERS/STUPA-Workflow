"""Finance tools for expenses, invoices and sub-bookings."""

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
async def list_sub_bookings(expense_id: str) -> dict:
    """List the sub-bookings of a booking (#subbookings).

    A booking can break down into sub-bookings with the same schema. A sub-booking
    inherits the cost center, the fiscal year and the kind of the parent. The
    amount of the parent equals the sum of the sub-bookings.
    Requires budget.view or budget.book.
    """
    return await api().get(f"/budget-expenses/{expense_id}/sub-bookings")


def register(mcp: FastMCP) -> None:
    """Register the expenses, invoices and sub-bookings tool group."""
    group.register(mcp)
