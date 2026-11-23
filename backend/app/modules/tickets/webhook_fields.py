"""The webhook fields of a ticket and the emit of `ticket.created`.

The report service calls `emit_ticket_created` in the transaction of the report
(§F/integrations/webhooks/002410, 002417). The number comes from the database sequence,
so the function reads it back instead of the attribute that the flush leaves unloaded.
`reporterEmail` is the given address or the e-mail of the reporting account.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.modules.applications.webhook_fields import link
from app.modules.tickets.models import Ticket
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
        number = await session.scalar(select(Ticket.number).where(Ticket.id == ticket.id))
        return {
            "number": None if number is None else f"T-{number:04d}",
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
