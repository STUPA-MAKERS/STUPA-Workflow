"""Integration (real Postgres): the order of the invoice list (spec 003021).

The list sorts newest first by the invoice date, and an invoice without one by the day of
its entry, because the frontend puts it under that month. So each month is one run of rows,
and the pages of the infinite scroll neither overlap nor skip a row.
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_schemas import InvoiceCreate

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def test_undated_invoice_sorts_by_its_entry_day(session: AsyncSession) -> None:
    """An invoice without an invoice date sorts by the day of its entry, not at the end.

    The invoices share a gross amount that no other test uses, so the amount filter
    isolates them. The entry day of each invoice is today, which lies after every
    invoice date of the test.
    """
    svc = BudgetTreeService(session)
    gross = Decimal(random.randint(10_000_000, 90_000_000)) + Decimal("0.37")

    async def invoice(number: str, issued: date | None) -> str:
        out = await svc.create_invoice(
            InvoiceCreate(number=number, issueDate=issued, grossAmount=gross), actor="t"
        )
        return str(out.id)

    feb = await invoice("FEB", date(2020, 2, 9))
    undated_a = await invoice("NONE-A", None)
    mar = await invoice("MAR", date(2020, 3, 16))
    undated_b = await invoice("NONE-B", None)
    jun = await invoice("JUN", date(2020, 6, 1))

    page = await svc.list_invoices_paged(gross_min=gross, gross_max=gross, limit=50)
    ids = [str(i.id) for i in page.items]
    assert ids[:2] == [undated_b, undated_a]
    assert ids[2:] == [jun, mar, feb]

    paged: list[str] = []
    for offset in range(0, 5, 2):
        part = await svc.list_invoices_paged(
            gross_min=gross, gross_max=gross, limit=2, offset=offset
        )
        paged.extend(str(i.id) for i in part.items)
    assert paged == ids
