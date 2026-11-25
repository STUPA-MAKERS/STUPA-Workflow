"""The read of a Bestellung by a permission (F/finance/orders/002863).

A person with a read permission of the Haushalt reads every Bestellung, because the
bookings and the invoices that the person reads name their Bestellungen. Every other
person reads a Bestellung through its Antrag. Without an Antrag no Gremium owns the
purchase, so the person who orders reads it too.
"""

from __future__ import annotations

from app.modules.auth.principal import Principal
from app.modules.budget.access import BUDGET_READ_PERMISSIONS

#: The permissions of which one reads every Bestellung. They read the bookings and the
#: invoices too.
ALL_READ_PERMISSIONS: tuple[str, ...] = BUDGET_READ_PERMISSIONS
#: The permissions of which one reads a Bestellung without an Antrag. They are the
#: permissions of the page "Bestellungen" (F/finance/orders/002883).
FREE_READ_PERMISSIONS: tuple[str, ...] = ("order.manage", *ALL_READ_PERMISSIONS)


def reads_all(principal: Principal | None) -> bool:
    """Tell whether the caller reads every Bestellung, whatever its Antrag."""
    return principal is not None and any(principal.has(perm) for perm in ALL_READ_PERMISSIONS)


def reads_free(principal: Principal | None) -> bool:
    """Tell whether the caller reads the Bestellungen that have no Antrag."""
    return principal is not None and any(principal.has(perm) for perm in FREE_READ_PERMISSIONS)
