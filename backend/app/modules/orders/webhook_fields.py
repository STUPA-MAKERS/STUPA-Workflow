"""The webhook fields of a Bestellung and the emit of its events (F/finance/orders/002891).

The orders service calls these functions in the transaction of the create and of the
status change (F/integrations/webhooks/002410). The Gremium filter and the Antragsart
filter of a webhook read the Gremium and the type of the Antrag, because a Bestellung has
none of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.modules.applications.models import Application
from app.modules.applications.service.service_base import _title_of
from app.modules.applications.webhook_fields import link, money
from app.modules.orders.numbers import format_number
from app.modules.webhooks.events import WebhookEvent, emit_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.orders.models import PurchaseOrder


def order_fields(row: PurchaseOrder, application_title: str | None) -> Mapping[str, Any]:
    """Return the fields of both events of a Bestellung."""
    return {
        "number": format_number(row.number),
        "title": row.title,
        "kind": row.kind,
        "status": row.status,
        "supplier": row.supplier,
        "plannedAmount": money(row.planned_amount),
        "actualAmount": money(row.actual_amount),
        "applicationTitle": application_title,
        "url": link(f"/orders/{row.id}"),
    }


async def emit_order_event(
    session: AsyncSession, row: PurchaseOrder, *, previous: str | None = None
) -> int:
    """Emit `order.created`, or `order.status_changed` with the status before.

    Args:
        session: The session of the write.
        row: The Bestellung after the write.
        previous: The status before a status change; None for the create.

    Returns:
        The number of new deliveries.
    """
    application = await session.get(Application, row.application_id)

    async def fields() -> Mapping[str, Any]:
        base = order_fields(row, _title_of(application.data) if application else None)
        return base if previous is None else {**base, "fromStatus": previous}

    return await emit_event(
        session,
        WebhookEvent(
            name="order.created" if previous is None else "order.status_changed",
            ids={"orderId": row.id, "applicationId": row.application_id},
            fields=fields,
            gremium_id=application.gremium_id if application else None,
            type_id=application.type_id if application else None,
        ),
    )
