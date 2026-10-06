"""Integration (real Postgres): A6, the bookings that reference an invoice.

`InvoiceOut.linkedBookings` lists the bookings with the invoice. The full budget view
sees all of them. A gremium scope sees only the bookings on cost centres in the subtree
of a node whose `view_gremium_id` is a member Gremium, as the budget tree does.
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


async def _gremium(session: AsyncSession, name: str) -> Gremium:
    g = Gremium(name=name, slug=f"g-{uuid.uuid4().hex[:8]}")
    session.add(g)
    await session.commit()
    return g


async def test_linked_bookings_follow_the_budget_visibility(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    culture = await _gremium(session, "Kulturreferat")
    sport = await _gremium(session, "Sportreferat")
    suffix = uuid.uuid4().hex[:6]

    top_a = await svc.create_node(BudgetNodeCreate(key=f"A{suffix}", name="Kultur"))
    await svc.update_node(top_a.id, BudgetNodeUpdate(viewGremiumId=culture.id))
    child_a = await svc.create_node(
        BudgetNodeCreate(key="1", name="Theater", parentId=top_a.id)
    )
    top_b = await svc.create_node(BudgetNodeCreate(key=f"B{suffix}", name="Sport"))
    await svc.update_node(top_b.id, BudgetNodeUpdate(viewGremiumId=sport.id))
    fy_a = await svc.create_fiscal_year(top_a.id, FiscalYearCreate(year=2026))
    fy_b = await svc.create_fiscal_year(top_b.id, FiscalYearCreate(year=2026))

    invoice = await svc.create_invoice(
        InvoiceCreate(number=f"R-{suffix}", grossAmount=Decimal("100.00")), actor="t"
    )
    assert invoice.linked_bookings == []

    on_a = await svc.book_expense(
        ExpenseCreate(
            amount=Decimal("60.00"), description="Bühne", budgetId=child_a.id,
            fiscalYearId=fy_a.id, invoiceId=invoice.id,
        ),
        actor="t",
    )
    on_b = await svc.book_expense(
        ExpenseCreate(
            amount=Decimal("40.00"), description="Bälle", budgetId=top_b.id,
            fiscalYearId=fy_b.id, invoiceId=invoice.id,
        ),
        actor="t",
    )
    # A booking without the invoice never shows up.
    await svc.book_expense(
        ExpenseCreate(
            amount=Decimal("5.00"), description="Porto", budgetId=top_b.id,
            fiscalYearId=fy_b.id,
        ),
        actor="t",
    )

    full = await svc.get_invoice(invoice.id)
    assert [b.id for b in full.linked_bookings] == [on_a.id, on_b.id]
    theatre = full.linked_bookings[0]
    assert theatre.path_key == f"A{suffix}-1"
    assert theatre.budget_name == "Theater"
    assert theatre.fiscal_year_id == fy_a.id
    assert theatre.amount == Decimal("60.00")

    culture_view = await svc.get_invoice(invoice.id, visible_gremium_ids={culture.id})
    assert [b.id for b in culture_view.linked_bookings] == [on_a.id]
    sport_view = await svc.get_invoice(invoice.id, visible_gremium_ids={sport.id})
    assert [b.id for b in sport_view.linked_bookings] == [on_b.id]
    no_view = await svc.get_invoice(invoice.id, visible_gremium_ids={uuid.uuid4()})
    assert no_view.linked_bookings == []
    assert (await svc.get_invoice(invoice.id, visible_gremium_ids=set())).linked_bookings == []

    page = await svc.list_invoices_paged(
        invoice_id=invoice.id, visible_gremium_ids={culture.id}
    )
    assert [b.id for b in page.items[0].linked_bookings] == [on_a.id]

    updated = await svc.update_invoice(invoice.id, InvoiceUpdate(note="geprüft"))
    assert {b.id for b in updated.linked_bookings} == {on_a.id, on_b.id}

