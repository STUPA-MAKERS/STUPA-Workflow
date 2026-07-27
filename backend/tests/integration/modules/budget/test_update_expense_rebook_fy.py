"""Integration: a rebook across top-budget borders must check the fiscal year (#AUD-036).

The tests run against a real Postgres through testcontainers.

`update_expense` let `budgetId` move to any node but kept `fiscalYearId` fixed. It did
not check that the fiscal year belongs to the new top budget. A cross-top-level rebook
then left an orphan fiscal-year reference: a phantom row with allocated 0 and a negative
available amount. The fix mirrors `book_expense` and `move_fiscal_year`. A top-level
mismatch gives 422.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import Gremium
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import BudgetExpense
from app.modules.budget.tree_schemas import (
    BudgetNodeCreate,
    ExpenseCreate,
    ExpenseUpdate,
    FiscalYearCreate,
)
from app.shared.errors import ValidationProblem

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _gremium(session: AsyncSession) -> Gremium:
    g = Gremium(name="FS Informatik", slug=f"fs-{uuid.uuid4().hex[:8]}")
    session.add(g)
    await session.commit()
    return g


def _suffix() -> str:
    return uuid.uuid4().hex[:6]


async def test_update_expense_rejects_cross_top_level_rebook(session: AsyncSession) -> None:
    """A rebook to a cost center under a different top budget gives 422 (#AUD-036)."""
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    # Two independent top budgets, each with its own fiscal year.
    top_a = await svc.create_node(
        BudgetNodeCreate(key=f"TA{_suffix()}", name="Top A", gremiumId=g.id)
    )
    child_a = await svc.create_node(BudgetNodeCreate(key="01", name="K-A", parentId=top_a.id))
    fy_a = await svc.create_fiscal_year(top_a.id, FiscalYearCreate(year=2026))

    top_b = await svc.create_node(
        BudgetNodeCreate(key=f"TB{_suffix()}", name="Top B", gremiumId=g.id)
    )
    child_b = await svc.create_node(BudgetNodeCreate(key="01", name="K-B", parentId=top_b.id))
    await svc.create_fiscal_year(top_b.id, FiscalYearCreate(year=2026))

    booking = await svc.book_expense(
        ExpenseCreate(
            budgetId=child_a.id,
            fiscalYearId=fy_a.id,
            amount=Decimal("50"),
            description="Buchung A",
        ),
        actor="tester",
    )

    # Rebook to a cost center under top B. The fiscal year of top A stays fixed, so 422.
    with pytest.raises(ValidationProblem):
        await svc.update_expense(booking.id, ExpenseUpdate(budgetId=child_b.id))

    # The booking stays unchanged. No partial commit writes the orphan fiscal-year row.
    await session.rollback()
    row = await session.get(BudgetExpense, booking.id)
    assert row is not None
    assert row.budget_id == child_a.id
    assert row.fiscal_year_id == fy_a.id


async def test_update_expense_same_top_level_rebook_ok(session: AsyncSession) -> None:
    """A rebook inside the same top budget stays allowed because the fiscal year fits."""
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"TS{_suffix()}", name="Top", gremiumId=g.id))
    c1 = await svc.create_node(BudgetNodeCreate(key="01", name="K1", parentId=top.id))
    c2 = await svc.create_node(BudgetNodeCreate(key="02", name="K2", parentId=top.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))

    booking = await svc.book_expense(
        ExpenseCreate(
            budgetId=c1.id,
            fiscalYearId=fy.id,
            amount=Decimal("50"),
            description="Buchung",
        ),
        actor="tester",
    )

    out = await svc.update_expense(booking.id, ExpenseUpdate(budgetId=c2.id))
    assert out.budget_id == c2.id
    assert out.fiscal_year_id == fy.id
