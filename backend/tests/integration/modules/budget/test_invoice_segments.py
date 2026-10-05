"""Integration (real Postgres): FE10c, the segments of the invoice list.

The invoice list has four segments: all, "Eingang" (open, no booking), "Verbucht"
(open, with a booking) and "Bezahlt" (paid). ``booked`` filters on a linked booking,
and ``counts`` gives the size of each segment under the other filters. A booking on a
cost centre outside the scope of a gremium-scoped reader does not count.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import Gremium
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_schemas import (
    BudgetNodeCreate,
    BudgetNodeUpdate,
    ExpenseCreate,
    FiscalYearCreate,
    InvoiceCreate,
    InvoiceUpdate,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def test_segments_and_counts(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    suffix = uuid.uuid4().hex[:6]
    gremium = Gremium(name="Kulturreferat", slug=f"g-{suffix}")
    session.add(gremium)
    await session.commit()

    # Two top cost centres: the gremium sees the first one only.
    seen = await svc.create_node(BudgetNodeCreate(key=f"S{suffix}", name="Kultur"))
    await svc.update_node(seen.id, BudgetNodeUpdate(viewGremiumId=gremium.id))
    hidden = await svc.create_node(BudgetNodeCreate(key=f"H{suffix}", name="Sport"))
    fy_seen = await svc.create_fiscal_year(seen.id, FiscalYearCreate(year=2026))
    fy_hidden = await svc.create_fiscal_year(hidden.id, FiscalYearCreate(year=2026))

    # A day that no other test uses, so the date filter isolates these invoices.
    day = date(random.randint(2200, 2900), 1, 1)

    async def invoice(number: str, gross: str) -> uuid.UUID:
        out = await svc.create_invoice(
            InvoiceCreate(
                number=f"{number}-{suffix}", issueDate=day, grossAmount=Decimal(gross)
            ),
            actor="t",
        )
        return out.id

    inbox = await invoice("IN", "10.00")
    booked_seen = await invoice("BS", "20.00")
    booked_hidden = await invoice("BH", "30.00")
    paid = await invoice("PD", "40.00")
    await svc.update_invoice(paid, InvoiceUpdate(status="paid"))

    for invoice_id, budget_id, fy_id in (
        (booked_seen, seen.id, fy_seen.id),
        (booked_hidden, hidden.id, fy_hidden.id),
    ):
        await svc.book_expense(
            ExpenseCreate(
                amount=Decimal("5.00"), description="Anzahlung", budgetId=budget_id,
                fiscalYearId=fy_id, invoiceId=invoice_id,
            ),
            actor="t",
        )

    async def ids(status: str | None = None, booked: bool | None = None) -> set[uuid.UUID]:
        page = await svc.list_invoices_paged(
            issue_from=day.isoformat(), issue_to=day.isoformat(), status=status, booked=booked
        )
        return {i.id for i in page.items}

    full = await svc.list_invoices_paged(issue_from=day.isoformat(), issue_to=day.isoformat())
    assert full.total == 4
    assert full.counts.model_dump() == {"all": 4, "inbox": 1, "booked": 2, "paid": 1}

    assert await ids(status="open", booked=False) == {inbox}
    assert await ids(status="open", booked=True) == {booked_seen, booked_hidden}
    assert await ids(booked=False) == {inbox, paid}
    assert await ids(status="paid") == {paid}

    # The counts ignore the segment filter itself, so every segment keeps its number.
    narrowed = await svc.list_invoices_paged(
        issue_from=day.isoformat(), issue_to=day.isoformat(), status="open", booked=True
    )
    assert narrowed.total == 2
    assert narrowed.counts == full.counts

    # Another filter narrows the counts too.
    big = await svc.list_invoices_paged(
        issue_from=day.isoformat(), issue_to=day.isoformat(), gross_min=Decimal("25.00")
    )
    assert big.counts.model_dump() == {"all": 2, "inbox": 0, "booked": 1, "paid": 1}

    # A gremium-scoped reader: the booking on the hidden cost centre does not count.
    scoped = await svc.list_invoices_paged(
        issue_from=day.isoformat(), issue_to=day.isoformat(),
        visible_gremium_ids={gremium.id},
    )
    assert scoped.counts.model_dump() == {"all": 4, "inbox": 2, "booked": 1, "paid": 1}
    scoped_inbox = await svc.list_invoices_paged(
        issue_from=day.isoformat(), issue_to=day.isoformat(), status="open", booked=False,
        visible_gremium_ids={gremium.id},
    )
    assert {i.id for i in scoped_inbox.items} == {inbox, booked_hidden}

    # A reader without any visible cost centre sees no booking at all.
    blind = await svc.list_invoices_paged(
        issue_from=day.isoformat(), issue_to=day.isoformat(), visible_gremium_ids=set()
    )
    assert blind.counts.model_dump() == {"all": 4, "inbox": 3, "booked": 0, "paid": 1}
