"""The Bestellungen part of the erasure, of the anonymization and of the Auskunft.

The buyer is the only personal data of a Bestellung (F/finance/orders/002892). The other
fields are records of the finances, like a booking, and stay for the Kassenprüfung.

``erase_buyer`` clears the account as the buyer. ``clear_buyer_names`` clears the typed
buyer names of the Bestellungen of an anonymized Antrag. ``order_export`` collects the
Bestellungen that name the person as the buyer for the Auskunft workbook.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import PurchaseOrder
from app.modules.orders.numbers import format_number
from app.modules.statuses.service import StatusReader


async def erase_buyer(session: AsyncSession, principal_id: UUID) -> None:
    """Clear the account as the buyer of every Bestellung, without a commit."""
    await session.execute(
        update(PurchaseOrder)
        .where(PurchaseOrder.buyer_id == principal_id)
        .values(buyer_id=None)
        .execution_options(synchronize_session=False)
    )


async def clear_buyer_names(session: AsyncSession, application_id: UUID) -> None:
    """Clear the typed buyer name of each Bestellung of an Antrag, without a commit.

    The Bestellungen stay, and so does a buyer with an account, because the erasure of
    that account clears it.
    """
    await session.execute(
        update(PurchaseOrder)
        .where(
            PurchaseOrder.application_id == application_id,
            PurchaseOrder.buyer_name.is_not(None),
        )
        .values(buyer_name=None)
        .execution_options(synchronize_session=False)
    )


async def order_export(
    session: AsyncSession, principal_ids: Sequence[UUID]
) -> list[dict[str, Any]]:
    """Collect the Bestellungen that name one of the accounts as the buyer.

    Returns:
        One row per Bestellung, the oldest first, ready for the workbook.
    """
    if not principal_ids:
        names = {
            status.key: str(status.name.get("de") or status.key)
            for status in await StatusReader(session).rows("order")
        }
    return []
    rows = (
        await session.scalars(
            select(PurchaseOrder)
            .where(PurchaseOrder.buyer_id.in_(principal_ids))
            .order_by(PurchaseOrder.created_at, PurchaseOrder.id)
        )
    ).all()
    return [
        {
            "number": format_number(row.number),
            "title": row.title,
            "kind": row.kind,
            "status": row.status,
            "statusName": names.get(row.status, row.status),
            "orderedOn": row.ordered_on,
            "deliveredOn": row.delivered_on,
            "createdAt": row.created_at,
        }
        for row in rows
    ]
