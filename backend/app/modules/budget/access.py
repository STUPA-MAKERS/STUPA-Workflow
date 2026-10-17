"""The read gate of the budget lists: invoices, bookings and the full tree view.

Each of ``budget.view``, ``budget.structure`` and ``budget.book`` reads every
invoice, every booking (``GET /api/invoices``, ``GET /api/expenses``) and every node
of the tree. Without one of them only the gremium scope of ``view_gremium_id``
applies, and that scope covers the tree, not the invoice and booking lists.

The global search and the to-do links ask this gate too, so a hit or a link never
shows more than the lists show.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.auth.principal import Principal

#: The permissions that read the invoice and booking lists (the full view).
BUDGET_READ_PERMISSIONS: tuple[str, ...] = ("budget.view", "budget.structure", "budget.book")


def has_budget_read(principal: Principal) -> bool:
    """Tell if ``principal`` reads the invoice and booking lists (scope-capped ``has``)."""
    return any(principal.has(p) for p in BUDGET_READ_PERMISSIONS)
