"""The cost centers as the options of a form field.

`forms` asks for these options through `FormsService(session, budget_field_options)`,
because `forms` imports no higher module (§S/backend/python/000651).
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.budget import plan_rules
from app.modules.budget.tree.service_base import BudgetTreeServiceBase
from app.modules.budget.tree_models import Budget
from app.modules.budget.tree_rules import _SEP
from app.shared.config_schemas import FieldOption


async def budget_field_options(session: AsyncSession) -> list[FieldOption]:
    """Return the active cost centers as `select` options for `budget_select`.

    The label is `name (path key)`. The stored answer value is the budget UUID. Each
    option also carries the parent, the key and the own color, because the form shows
    the cost centers as a tree with the colors of the budget page. A cost center that
    is not active has no option, and no cost center below it has one. A cost center
    that is income in the current year of its budget has no option either, because an
    Antrag takes only a cost center on the expense side (001030).
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
                Budget.tree_path,
            )
            .where(Budget.active.is_(True), below_active_only())
            .order_by(Budget.tree_path)
        )
    ).all()
    income = await _income_now(session)
    return [
        FieldOption(
            value=str(bid),
            label={"de": f"{name} ({path})", "en": f"{name} ({path})"},
            parentId=str(parent) if parent is not None else None,
            key=key,
            color=color,
        )
        for bid, name, path, parent, key, color, tree_path in rows
        if not plan_rules.is_below_path(tree_path, income)
    ]


async def _income_now(session: AsyncSession) -> tuple[str, ...]:
    """Return the tree paths of the income Titel in the current year of each budget.

    The current year is the year that the flow action takes (000879). A budget without
    a current year, or without a plan in force for it, has no income Titel.
    """
    service = BudgetTreeServiceBase(session)
    tops = (await session.scalars(select(Budget).where(Budget.parent_id.is_(None)))).all()
    years = [year for top in tops if (year := await service.current_year(top)) is not None]
    if not years:
        return ()
    return tuple(path for _fy, path in await service.income_titel_paths(years))


def below_active_only() -> ColumnElement[bool]:
    """Return the filter for a cost center that has no ancestor that is not active.

    A path segment is alphanumeric, so the path key of an ancestor with the separator
    is a prefix without a LIKE wildcard.
    """
    above = aliased(Budget)
    return ~exists().where(
        above.active.is_(False), Budget.tree_path.like(above.tree_path + _SEP + "%")
    )
