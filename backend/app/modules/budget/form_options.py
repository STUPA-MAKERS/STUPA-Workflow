"""The cost centers as the options of a form field.

`forms` asks for these options through `FormsService(session, budget_field_options)`,
because `forms` imports no higher module (§S/backend/python/000651).
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.budget.tree_models import Budget
from app.modules.budget.tree_rules import _SEP
from app.shared.config_schemas import FieldOption


async def budget_field_options(session: AsyncSession) -> list[FieldOption]:
    """Return the active cost centers as `select` options for `budget_select`.

    The label is `name (path key)`. The stored answer value is the budget UUID. Each
    option also carries the parent, the key and the own color, because the form shows
    the cost centers as a tree with the colors of the budget page. A cost center that
    is not active has no option, and no cost center below it has one.
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
            .where(Budget.active.is_(True), below_active_only())
            .order_by(Budget.path_key)
        )
    ).all()
    return [
        FieldOption(
            value=str(bid),
            label={"de": f"{name} ({path})", "en": f"{name} ({path})"},
            parentId=str(parent) if parent is not None else None,
            key=key,
            color=color,
        )
        for bid, name, path, parent, key, color in rows
    ]


def below_active_only() -> ColumnElement[bool]:
    """Return the filter for a cost center that has no ancestor that is not active.

    A path segment is alphanumeric, so the path key of an ancestor with the separator
    is a prefix without a LIKE wildcard.
    """
    above = aliased(Budget)
    return ~exists().where(
        above.active.is_(False), Budget.path_key.like(above.path_key + _SEP + "%")
    )
