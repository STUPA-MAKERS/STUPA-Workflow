"""Unit tests of the pure rules of the pretix integration.

§F/integrations/pretix/003084 the sales hold the counts per product, the sums and the free
places. §F/integrations/pretix/003086 one income per paid order, one expense per refund.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.pretix.client import Money, Order, Product, Quota
from app.modules.pretix.rules import candidates, sales_of


def _order(
    code: str,
    status: str,
    total: str,
    products: tuple[int, ...] = (1,),
    payments: tuple[Money, ...] = (),
    refunds: tuple[Money, ...] = (),
    payment_date: date | None = None,
) -> Order:
    return Order(
        code=code,
        status=status,  # type: ignore[arg-type]
        total=Decimal(total),
        payment_date=payment_date,
        products=products,
        payments=payments,
        refunds=refunds,
    )


_PAID = Money(local_id=1, amount=Decimal("10.00"), on=date(2026, 11, 20))
_REFUND = Money(local_id=2, amount=Decimal("4.00"), on=date(2026, 11, 22))

ORDERS = (
    _order("A", "p", "10.00", (1, 1), payments=(_PAID,), payment_date=date(2026, 11, 19)),
    _order("B", "n", "5.00", (2,)),
    _order("C", "c", "10.00", (1,), payments=(_PAID,), refunds=(_REFUND,)),
    _order("D", "e", "5.00", (2,)),
    _order("E", "p", "0.00", (2,), payments=(Money(local_id=1, amount=Decimal(0), on=None),)),
)


def test_sales_count_each_product_and_sum_the_money() -> None:
    sales = sales_of(
        (Product(id=1, name="Vorverkauf"), Product(id=2, name="Abendkasse")),
        (Quota(name="Einlass", available=7),),
        ORDERS,
    )
    assert sales == {
        "products": [
            {"name": "Vorverkauf", "paid": 2, "pending": 0, "cancelled": 1},
            {"name": "Abendkasse", "paid": 1, "pending": 1, "cancelled": 1},
        ],
        "paidSum": "10.00",
        "refundSum": "4.00",
        "quotas": [{"name": "Einlass", "available": 7}],
    }


def test_each_paid_order_and_each_refund_is_one_booking() -> None:
    found = candidates(ORDERS)
    assert [(c.source, c.key, c.kind, c.amount, c.on) for c in found] == [
        ("order", "A", "income", Decimal("10.00"), date(2026, 11, 19)),
        ("order", "C", "income", Decimal("10.00"), date(2026, 11, 20)),
        ("refund", "C-2", "expense", Decimal("4.00"), date(2026, 11, 22)),
    ]
    assert {c.code for c in found} == {"A", "C"}


def test_a_paid_order_without_a_day_has_no_day() -> None:
    (found,) = candidates(
        (_order("F", "p", "3.00", payments=(Money(local_id=1, amount=Decimal(3), on=None),)),)
    )
    assert found.on is None
