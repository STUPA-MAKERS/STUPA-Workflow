"""The webhook fields of a ticket and the emit of `ticket.created`.

The report service calls `emit_ticket_created` in the transaction of the report
(§F/integrations/webhooks/002410, 002417). `reporterEmail` is the given address or the
e-mail of the reporting account.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.modules.applications.webhook_fields import link
from app.modules.tickets.models import Ticket
from app.modules.tickets.numbers import format_number
from app.modules.webhooks.events import WebhookEvent, emit_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def emit_ticket_created(
    session: AsyncSession, ticket: Ticket, *, reporter_email: str | None
) -> int:
    """Emit `ticket.created`.

    Returns:
        The number of new deliveries.
    """

    async def fields() -> Mapping[str, Any]:
        return {
            "number": format_number(ticket.number),
            "kind": ticket.kind,
            "title": ticket.title,
            "url": link(f"/tickets/{ticket.id}"),
            "body": ticket.body,
            "reporterEmail": reporter_email,
        }

    return await emit_event(
        session,
        WebhookEvent(name="ticket.created", ids={"ticketId": ticket.id}, fields=fields),
    )
