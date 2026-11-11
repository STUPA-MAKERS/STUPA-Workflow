"""The cost centers as the options of a form field.

`forms` asks for these options through `FormsService(session, budget_field_options)`,
because `forms` imports no higher module (§S/backend/python/000651).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.budget.tree_models import Budget
from app.shared.config_schemas import FieldOption


async def budget_field_options(session: AsyncSession) -> list[FieldOption]:
    """Return the active cost centers as `select` options for `budget_select`.

    The label is `name (path key)`. The stored answer value is the budget UUID. Each
    option also carries the parent, the key and the own color, because the form shows
    the cost centers as a tree with the colors of the budget page. A parent that is not
    active has no option, so its active children are top-level options.
    """
    rows = (
        await session.execute(
            select(
                Budget.id,
                Budget.name,
                Budget.path_key,
                Budget.parent_id,
                Budget.key,
                Budget.color,
            )
            .where(Budget.active.is_(True))
            .order_by(Budget.path_key)
        )
    ).all()
    active = {bid for bid, *_ in rows}
    return [
        FieldOption(
            value=str(bid),
            label={"de": f"{name} ({path})", "en": f"{name} ({path})"},
            parentId=str(parent) if parent in active else None,
            key=key,
            color=color,
        )
        for bid, name, path, parent, key, color in rows
    ]
