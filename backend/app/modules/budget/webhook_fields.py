"""The webhook fields of a booking and an invoice, and the emit of their events.

The budget services call these functions in the transaction of the booking or the invoice
(§F/integrations/webhooks/002410, 002417). A transfer is one `booking.created` with the
kind `transfer` and the source cost centre. The Gremium of a booking is the Gremium of its
cost centre. An invoice has no cost centre until a booking pays it, so its `costCentre`
is None at the create.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.modules.applications.webhook_fields import link, money
from app.modules.budget.tree_models import Budget, FiscalYear
from app.modules.webhooks.events import WebhookEvent, emit_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.budget.tree_models import BudgetExpense, Invoice


async def emit_booking_created(
    session: AsyncSession, expense: BudgetExpense, node: Budget, *, kind: str
) -> int:
    """Emit `booking.created` for a booking on the cost centre `node`.

    Returns:
        The number of new deliveries.
    """

    async def fields() -> Mapping[str, Any]:
        year = await session.get(FiscalYear, expense.fiscal_year_id)
        return {
            "kind": kind,
            "amount": money(expense.amount),
            "costCentre": {"id": str(node.id), "name": node.name},
            "fiscalYear": {
                "id": str(expense.fiscal_year_id),
                "name": str(getattr(year, "year", "")),
            },
            "description": expense.description,
            "applicationId": str(expense.application_id) if expense.application_id else None,
            "url": link(f"/expenses?id={expense.id}"),
        }

    return await emit_event(
        session,
        WebhookEvent(
            name="booking.created",
            ids={"bookingId": expense.id},
            fields=fields,
            gremium_id=node.gremium_id,
        ),
    )


async def emit_invoice_created(session: AsyncSession, invoice: Invoice) -> int:
    """Emit `invoice.created`.

    Returns:
        The number of new deliveries.
    """

    async def fields() -> Mapping[str, Any]:
        return {
            "number": invoice.number,
            "supplier": invoice.supplier,
            "grossAmount": money(invoice.gross_amount),
            "currency": invoice.currency or "EUR",
            "issueDate": invoice.issue_date.isoformat() if invoice.issue_date else None,
            "dueDate": invoice.due_date.isoformat() if invoice.due_date else None,
            "costCentre": None,
            "url": link(f"/invoices?id={invoice.id}"),
        }

    return await emit_event(
        session,
        WebhookEvent(name="invoice.created", ids={"invoiceId": invoice.id}, fields=fields),
    )
