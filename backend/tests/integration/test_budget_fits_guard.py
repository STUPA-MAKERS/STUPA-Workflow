"""Integration: ``flow.context._budget_fits`` rechnet Einnahmen richtig vorzeichen-
behaftet (Regression). Einnahmen (``kind='income'``) ERHÖHEN den verfügbaren Rest —
nicht senken — gleiche Richtung wie ``tree_rules.node_available``.

Vor dem Fix summierte das Guard-Query ALLE ``budget_expense``-Zeilen als Ausgaben
(ohne ``kind``-Filter), sodass eine Einnahme die Verfügbarkeit fälschlich minderte und
auf ``budgetFits`` gewachte Auto-Übergänge daneben lagen.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.budget.tree_models import (
    Budget,
    BudgetAllocation,
    BudgetExpense,
    FiscalYear,
)
from app.modules.flow.context import _budget_fits

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Kostenstelle + Haushaltsjahr + Allocation 1000 anlegen; gibt (budget_id, fy_id)."""
    budget = Budget(key="VS", path_key="VS", name="Verfügungsstelle")
    session.add(budget)
    await session.flush()
    fy = FiscalYear(
        budget_id=budget.id,
        year=2026,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    session.add(fy)
    await session.flush()
    session.add(
        BudgetAllocation(
            budget_id=budget.id, fiscal_year_id=fy.id, allocated=Decimal("1000.00")
        )
    )
    await session.flush()
    return budget.id, fy.id


def _app(budget_id: uuid.UUID, fy_id: uuid.UUID, amount: str) -> SimpleNamespace:
    # `_budget_fits` liest nur diese drei Attribute der Application.
    return SimpleNamespace(
        budget_id=budget_id, fiscal_year_id=fy_id, amount=Decimal(amount)
    )


async def test_income_raises_availability(session: AsyncSession) -> None:
    budget_id, fy_id = await _seed(session)
    # Allocation 1000 + Einnahme 500 ⇒ verfügbar 1500. Antrag 1200 PASST.
    session.add(
        BudgetExpense(
            budget_id=budget_id, fiscal_year_id=fy_id, kind="income", amount=Decimal("500.00"), description="Spende"
        )
    )
    await session.flush()
    assert await _budget_fits(session, _app(budget_id, fy_id, "1200.00")) is True  # type: ignore[arg-type]


async def test_expense_lowers_availability(session: AsyncSession) -> None:
    budget_id, fy_id = await _seed(session)
    # Allocation 1000 − Ausgabe 400 ⇒ verfügbar 600. Antrag 800 passt NICHT.
    session.add(
        BudgetExpense(
            budget_id=budget_id, fiscal_year_id=fy_id, kind="expense", amount=Decimal("400.00"), description="Miete"
        )
    )
    await session.flush()
    assert await _budget_fits(session, _app(budget_id, fy_id, "800.00")) is False  # type: ignore[arg-type]


async def test_mixed_income_and_expense_net(session: AsyncSession) -> None:
    budget_id, fy_id = await _seed(session)
    # 1000 − 700 (Ausgabe) + 300 (Einnahme) = 600 verfügbar.
    session.add_all(
        [
            BudgetExpense(
                budget_id=budget_id, fiscal_year_id=fy_id, kind="expense", amount=Decimal("700.00"), description="Miete"
            ),
            BudgetExpense(
                budget_id=budget_id, fiscal_year_id=fy_id, kind="income", amount=Decimal("300.00"), description="Spende"
            ),
        ]
    )
    await session.flush()
    assert await _budget_fits(session, _app(budget_id, fy_id, "600.00")) is True  # type: ignore[arg-type]
    assert await _budget_fits(session, _app(budget_id, fy_id, "600.01")) is False  # type: ignore[arg-type]
