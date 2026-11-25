"""Pure rules of the Bestellungen: the link, the dates, the positions and the sum.

Every function here takes plain values and returns a plain value. The service reads the
database, calls these functions and writes the result.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Literal

#: The key of a status of the list of the Bestellungen (F/administration/admin/003035).
OrderStatus = str
OrderKind = Literal["order", "outlay"]
#: The segments of the page "Bestellungen" that hold a Bestellung (F/finance/orders/002884).
Segment = Literal["open", "delivered", "done"]

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
    sets_date: str | None, ordered_on: date | None, delivered_on: date | None, today: date
) -> tuple[date | None, date | None]:
    """Return the two dates after a change to a status with the setting ``sets_date``.

    A status sets the date that it names (``orderedOn`` or ``deliveredOn``) to ``today``
    when the date is empty (F/administration/admin/003037). A date that a person set
    stays, because it is more exact than the day of the click.
    """
    match sets_date:
        case "orderedOn":
            return (ordered_on or today, delivered_on)
        case "deliveredOn":
            return (ordered_on, delivered_on or today)
        case _:
            return (ordered_on, delivered_on)


def price(actual: Decimal | None, planned: Decimal | None) -> Decimal | None:
    """Return the price of a Bestellung: the real price, else the planned price."""
    return actual if actual is not None else planned


def orders_sum(rows: Iterable[tuple[str, Decimal | None, Decimal | None]]) -> Decimal:
    """Sum the prices of the Bestellungen that are not in the phase ``void``.

    Each row is ``(phase, actual, planned)``. A Bestellung in the phase ``void`` bought
    nothing (F/administration/admin/003036).
    """
    return sum(
        (
            price(actual, planned) or Decimal(0)
            for phase, actual, planned in rows
            if phase != "void"
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


def segment_of(phase: str, cost: Decimal | None, booked: Decimal) -> Segment:
    """Return the segment of a Bestellung on the page "Bestellungen" (F/finance/orders/002884).

    ``phase`` is the phase of its status (F/administration/admin/003036), ``cost`` the
    price of the Bestellung (`price`) and ``booked`` the sum of its bookings. A
    Bestellung in the phase ``done`` waits in "Geliefert" until its price is booked in
    full. Without a price it usually waits for its invoice, so it stays there until a
    person books it. `OrderListing` holds the same rule as SQL.
    """
    match phase:
        case "open":
            return "open"
        case "void":
            return "done"
        case _:
            waits = booked < cost if cost is not None else booked == 0
            return "delivered" if waits else "done"
