"""The read of a Bestellung without an Antrag (F/finance/orders/002863).

A Bestellung of an Antrag is read by the persons who read the Antrag. Without an Antrag
no Gremium owns the purchase, so the persons who open the page "Bestellungen" read it.
"""

from __future__ import annotations

from app.modules.auth.principal import Principal

#: The permissions of which one reads a Bestellung without an Antrag. They are the
#: permissions of the page "Bestellungen" (F/finance/orders/002883).
FREE_READ_PERMISSIONS: tuple[str, ...] = ("order.manage", "budget.view")


def reads_free(principal: Principal | None) -> bool:
    """Tell whether the caller reads the Bestellungen that have no Antrag."""
    return principal is not None and any(principal.has(perm) for perm in FREE_READ_PERMISSIONS)
