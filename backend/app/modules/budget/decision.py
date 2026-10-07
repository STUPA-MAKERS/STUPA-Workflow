"""The deciding Gremium of a cost center (flow variant B).

`budget.decision_gremium_id` names the Gremium that decides on spending from a cost
center and its subtree. A node without an own value inherits the value of the nearest
ancestor. `tree_rules.resolve_decision_gremium` holds the pure rule. This module loads
the ancestor chain of one node and applies the rule.

The flow engine reads the effective value when an application enters a vote state with
`gremiumSource: "budget"`, and for the guard `budgetHasDecisionGremium`.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.budget import tree_rules
from app.modules.budget.tree_models import Budget
from app.modules.budget.tree_rules import _SEP


async def decision_gremium_of(
    session: AsyncSession, budget_id: UUID
) -> tuple[UUID | None, UUID | None]:
    """Return the effective deciding Gremium of a node and the node that holds it.

    One query loads the node and its ancestors through the `path_key` prefixes, as
    `can_view_node` does.

    Returns:
        `(gremium_id, source_node_id)`, or `(None, None)` when the node does not exist
        or no node on its path holds a value.
    """
    path_key = await session.scalar(select(Budget.path_key).where(Budget.id == budget_id))
    if path_key is None:
        return None, None
    segments = path_key.split(_SEP)
    prefixes = [_SEP.join(segments[: i + 1]) for i in range(len(segments))]
    rows = (
        await session.execute(
            select(Budget.id, Budget.parent_id, Budget.decision_gremium_id).where(
                Budget.path_key.in_(prefixes)
            )
        )
    ).all()
    parent_of: dict[UUID, UUID | None] = {r[0]: r[1] for r in rows}
    own_of: dict[UUID, UUID | None] = {r[0]: r[2] for r in rows}
    return tree_rules.resolve_decision_gremium(budget_id, parent_of, own_of)


async def effective_decision_gremium(
    session: AsyncSession, budget_id: UUID | None
) -> UUID | None:
    """Return the effective deciding Gremium of a cost center, or `None`.

    `None` comes back for a missing cost center (`budget_id=None` or an unknown id) and
    for a cost center without an own or inherited value.
    """
    if budget_id is None:
        return None
    gremium, _source = await decision_gremium_of(session, budget_id)
    return gremium
