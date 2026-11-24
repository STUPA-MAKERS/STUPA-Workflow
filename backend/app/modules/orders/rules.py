"""Pure rules of the Bestellungen: the link, the dates, the positions and the sum.

Every function here takes plain values and returns a plain value. The service reads the
database, calls these functions and writes the result.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Literal

OrderStatus = Literal["planned", "ordered", "delivered", "cancelled"]
OrderKind = Literal["order", "outlay"]

#: The schemes that the link of a Bestellung can have. A different scheme, for example
#: ``javascript:``, runs code in the page.
URL_SCHEMES: tuple[str, ...] = ("http://", "https://")
#: The longest link.
URL_MAX = 2000


def url_valid(url: str) -> bool:
    """Tell whether the link starts with ``http://`` or ``https://`` and is short enough."""
    return len(url) <= URL_MAX and url.lower().startswith(URL_SCHEMES)


def buyer_missing(kind: str, buyer_id: object, buyer_name: str | None) -> bool:
    """Tell whether an Auslage lacks its buyer.

    An Auslage is a purchase that a person paid, so it must name that person, as an
    account or as a name.
    """
    return kind == "outlay" and buyer_id is None and not (buyer_name or "").strip()


def status_dates(
    status: str, ordered_on: date | None, delivered_on: date | None, today: date
) -> tuple[date | None, date | None]:
    """Return the two dates after a change to ``status``.

    "Bestellt" sets the empty order date and "Geliefert" sets the empty delivery date to
    ``today``. A date that a person set stays, because it is more exact than the day of
    the click.
    """
    match status:
        case "ordered":
            return (ordered_on or today, delivered_on)
        case "delivered":
            return (ordered_on, delivered_on or today)
        case _:
            return (ordered_on, delivered_on)


def price(actual: Decimal | None, planned: Decimal | None) -> Decimal | None:
    """Return the price of a Bestellung: the real price, else the planned price."""
    return actual if actual is not None else planned


def orders_sum(rows: Iterable[tuple[str, Decimal | None, Decimal | None]]) -> Decimal:
    """Sum the prices of the Bestellungen that are not cancelled.

    Each row is ``(status, actual, planned)``. A cancelled Bestellung bought nothing.
    """
    return sum(
        (
            price(actual, planned) or Decimal(0)
            for status, actual, planned in rows
            if status != "cancelled"
        ),
        Decimal(0),
    )


def over_by(total: Decimal, approved: Decimal | None) -> Decimal | None:
    """Return by how much the sum is above the approved amount, else None."""
    return total - approved if approved is not None and total > approved else None


def price_from_invoice(actual: Decimal | None, gross: Decimal, others: int) -> Decimal | None:
    """Return the real price of a Bestellung that gets an invoice.

    The gross amount of the invoice fills an empty real price, and only when no other
    Bestellung names the invoice (``others`` is 0). On an invoice for several purchases
    each Bestellung has a part of the amount, so a person types it. A real price that is
    set stays.
    """
    return gross if actual is None and others == 0 else actual
