"""Pure rules of the pretix integration: the sales of an event and its bookings.

The sales (§F/integrations/pretix/003084) hold only sums and numbers
(§F/integrations/pretix/003088). The bookings (003086) come from the orders: one income
per paid order, one expense per finished refund.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from app.modules.pretix.client import Order, Product, Quota

BookingKind = Literal["income", "expense"]


def _count(orders: Iterable[Order], product_id: int, statuses: frozenset[str]) -> int:
    return sum(order.products.count(product_id) for order in orders if order.status in statuses)


def sales_of(
    products: Iterable[Product], quotas: Iterable[Quota], orders: Iterable[Order]
) -> dict[str, object]:
    """Build the stored sales of an event from its products, quotas and orders.

    A position of an expired order counts as cancelled, because it holds no place.
    """
    rows = tuple(orders)
    return {
        "products": [
            {
                "name": product.name,
                "paid": _count(rows, product.id, frozenset({"p"})),
                "pending": _count(rows, product.id, frozenset({"n"})),
                "cancelled": _count(rows, product.id, frozenset({"c", "e"})),
            }
            for product in products
        ],
        "paidSum": str(sum((order.total for order in rows if order.status == "p"), Decimal(0))),
        "refundSum": str(
            sum((refund.amount for order in rows for refund in order.refunds), Decimal(0))
        ),
        "quotas": [{"name": quota.name, "available": quota.available} for quota in quotas],
    }


@dataclass(frozen=True, slots=True)
class Candidate:
    """One booking that an order asks for.

    Attributes:
        source: `order` for the income of a paid order, `refund` for a refund.
        key: The code of the order, for a refund with the id of the refund.
        kind: `income` or `expense`.
        amount: The sum, always above zero.
        on: The day of the payment or of the refund.
        code: The code of the order, for the text of the booking.
    """

    source: Literal["order", "refund"]
    key: str
    kind: BookingKind
    amount: Decimal
    on: date | None
    code: str


def _paid(order: Order) -> Candidate | None:
    amount = sum((payment.amount for payment in order.payments), Decimal(0))
    days = [payment.on for payment in order.payments if payment.on is not None]
    if amount <= 0:
        return None
    return Candidate(
        source="order",
        key=order.code,
        kind="income",
        amount=amount,
        on=order.payment_date or (max(days) if days else None),
        code=order.code,
    )


def candidates(orders: Iterable[Order]) -> tuple[Candidate, ...]:
    """Return the bookings of the orders: each paid order and each finished refund.

    An order counts as paid when pretix confirmed a payment of it, so an order that was
    paid and then cancelled keeps its income and gets its refund as a second booking.
    """
    rows = tuple(orders)
    paid = tuple(found for order in rows if (found := _paid(order)) is not None)
    refunds = tuple(
        Candidate(
            source="refund",
            key=f"{order.code}-{refund.local_id}",
            kind="expense",
            amount=refund.amount,
            on=refund.on,
            code=order.code,
        )
        for order in rows
        for refund in order.refunds
        if refund.amount > 0
    )
    return paid + refunds
