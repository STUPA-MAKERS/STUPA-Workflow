"""The webhook fields of a ticket and the emits of the ticket events.

The ticket services call these functions in the transaction of their change
(§F/integrations/webhooks/002410, 002417). Each event carries the Gremium of the Bereich
of the ticket for the Gremium filter of a webhook (§F/integrations/webhooks/002749); a
Bereich without a Gremium passes that filter. An emit asks first for a subscriber, so an
event that nobody reads costs no read of the Bereich.

`reporterEmail` of `ticket.created` is the given address or the e-mail of the reporting
account.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.modules.applications.webhook_fields import link, ref
from app.modules.tickets.models import Ticket, TicketArea
from app.modules.tickets.numbers import format_number
from app.modules.webhooks.events import WebhookEvent, emit_event, has_subscriber

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.webhooks.catalog import WebhookEventName


async def _emit(
    session: AsyncSession,
    name: WebhookEventName,
    ticket: Ticket,
    extra: Mapping[str, Any],
) -> int:
    """Emit one ticket event with the fields that each ticket event has.

    Returns:
        The number of new deliveries.
    """
    if not await has_subscriber(session, name):
        return 0
    area = await session.get(TicketArea, ticket.area_id)

    async def fields() -> Mapping[str, Any]:
        return {
            "number": format_number(ticket.number),
            "title": ticket.title,
            "area": None if area is None else ref(area.id, area.name),
            "url": link(f"/tickets/{ticket.id}"),
            **extra,
        }

    return await emit_event(
        session,
        WebhookEvent(
            name=name,
            ids={"ticketId": ticket.id},
            fields=fields,
            gremium_id=None if area is None else area.gremium_id,
        ),
    )


async def emit_ticket_created(
    session: AsyncSession, ticket: Ticket, *, reporter_email: str | None
) -> int:
    """Emit `ticket.created` for a new ticket of each source.

    Returns:
        The number of new deliveries.
    """
    return await _emit(
        session,
        "ticket.created",
        ticket,
        {
            "kind": ticket.kind,
            "source": ticket.source,
            "body": ticket.body,
            "reporterEmail": reporter_email,
        },
    )


async def emit_ticket_message(session: AsyncSession, ticket: Ticket, *, body: str) -> int:
    """Emit `ticket.message` for a message of the sender (§F/integrations/webhooks/002750).

    The caller does not call it for a message of the team and not for the first message
    of a new ticket, because that one is in `ticket.created`.

    Returns:
        The number of new deliveries.
    """
    return await _emit(session, "ticket.message", ticket, {"body": body})


async def emit_ticket_status(session: AsyncSession, ticket: Ticket, *, old: str, new: str) -> int:
    """Emit `ticket.status` for a status change, also for one without a person.

    A change to the same status is no event (§F/integrations/webhooks/002751).

    Returns:
        The number of new deliveries.
    """
    if old == new:
        return 0
    return await _emit(session, "ticket.status", ticket, {"fromStatus": old, "toStatus": new})
