"""The read gate of the budget lists: invoices, bookings and the full tree view.

Each of ``budget.view``, ``budget.structure`` and ``budget.book`` reads every
invoice, every booking (``GET /api/invoices``, ``GET /api/expenses``) and every node
of the tree. Without one of them only the gremium scope applies (`viewed_by`), and
that scope covers the tree, not the invoice and booking lists.

The gremium scope opens the subtree of a node for the Gremium in its
``view_gremium_id``, and a top-level node with a plan for each Gremium that decides
its plan in a step (spec 000888).

The global search and the to-do links ask this gate too, so a hit or a link never
shows more than the lists show.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, and_, exists, or_

from app.modules.budget.plan_models import BudgetPlanStep
from app.modules.budget.tree_models import Budget

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID

    from app.modules.auth.principal import Principal

#: The permissions that read the invoice and booking lists (the full view).
BUDGET_READ_PERMISSIONS: tuple[str, ...] = ("budget.view", "budget.structure", "budget.book")


def has_budget_read(principal: Principal) -> bool:
    """Tell if ``principal`` reads the invoice and booking lists (scope-capped ``has``)."""
    return any(principal.has(p) for p in BUDGET_READ_PERMISSIONS)


def viewed_by(gremium_ids: Collection[UUID]) -> ColumnElement[bool]:
    """Return the filter for the nodes whose subtree one of the Gremien reads.

    A node matches with one of the Gremien in its ``view_gremium_id``. A top-level node
    with a plan matches too when one of the Gremien decides its plan in a step, because
    the members of such a Gremium read the whole Haushalt (spec 000888).
    """
    return or_(
        Budget.view_gremium_id.in_(gremium_ids),
        and_(
            Budget.parent_id.is_(None),
            Budget.plan_enabled.is_(True),
            exists().where(
                BudgetPlanStep.budget_id == Budget.id,
                BudgetPlanStep.gremium_id.in_(gremium_ids),
            ),
        ),
    )
