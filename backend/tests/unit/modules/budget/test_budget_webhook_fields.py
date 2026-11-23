"""The webhook fields of a booking and an invoice (§F/integrations/webhooks/002410)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.modules.budget.tree_models import Budget, BudgetExpense, FiscalYear, Invoice
from app.modules.budget.webhook_fields import emit_booking_created, emit_invoice_created
from app.modules.webhooks.catalog import EVENTS
from app.modules.webhooks.models import Webhook
from tests._support.webhooks_fakes import FakeSession
from tests.unit.conftest import ActiveWebhooks


def _hook(event: str) -> Webhook:
    hook = Webhook(
        name="h",
        url="https://h.test/h",
        active=True,
        subscriptions=[{"event": event, "fields": sorted(EVENTS[event].field_keys)}],
        gremium_ids=[],
        type_ids=[],
        state_keys=[],
    )
    hook.id = uuid.uuid4()
    return hook


def _node() -> Budget:
    node = Budget(name="Kultur", key="K", path_key="K", gremium_id=uuid.uuid4())
    node.id = uuid.uuid4()
    return node


async def test_booking_with_application(active_webhooks: ActiveWebhooks) -> None:
    active_webhooks.hooks = [_hook("booking.created")]
    year = FiscalYear(year=2026)
    expense = BudgetExpense(
        amount=Decimal("12.5"),
        description="Technik",
        fiscal_year_id=uuid.uuid4(),
        application_id=uuid.uuid4(),
    )
    expense.id = uuid.uuid4()
    node = _node()
    year.id = expense.fiscal_year_id
    session = FakeSession()
    session.store[year.id] = year
    assert await emit_booking_created(session, expense, node, kind="expense") == 1  # type: ignore[arg-type]
    data = session.added[0].payload["data"]
    assert data["amount"] == "12.50"
    assert data["costCentre"] == {"id": str(node.id), "name": "Kultur"}
    assert data["fiscalYear"]["name"] == "2026"
    assert data["applicationId"] == str(expense.application_id)
    assert data["kind"] == "expense"


async def test_transfer_without_application(active_webhooks: ActiveWebhooks) -> None:
    active_webhooks.hooks = [_hook("booking.created")]
    expense = BudgetExpense(amount=Decimal(1), description="d", fiscal_year_id=uuid.uuid4())
    expense.id = uuid.uuid4()
    session = FakeSession()
    await emit_booking_created(session, expense, _node(), kind="transfer")  # type: ignore[arg-type]
    data = session.added[0].payload["data"]
    assert data["applicationId"] is None
    assert data["kind"] == "transfer"
    assert data["fiscalYear"]["name"] == ""


async def test_invoice_with_dates(active_webhooks: ActiveWebhooks) -> None:
    active_webhooks.hooks = [_hook("invoice.created")]
    inv = Invoice(
        number="RE-1",
        supplier="S",
        gross_amount=Decimal("119"),
        currency="EUR",
        issue_date=dt.date(2026, 11, 20),
        due_date=dt.date(2026, 12, 4),
    )
    inv.id = uuid.uuid4()
    session = FakeSession()
    assert await emit_invoice_created(session, inv) == 1  # type: ignore[arg-type]
    data = session.added[0].payload["data"]
    assert data["grossAmount"] == "119.00"
    assert data["issueDate"] == "2026-11-20"
    assert data["dueDate"] == "2026-12-04"
    assert data["costCentre"] is None


async def test_invoice_without_dates(active_webhooks: ActiveWebhooks) -> None:
    active_webhooks.hooks = [_hook("invoice.created")]
    inv = Invoice(gross_amount=Decimal(1), currency=None)
    inv.id = uuid.uuid4()
    session = FakeSession()
    await emit_invoice_created(session, inv)  # type: ignore[arg-type]
    data = session.added[0].payload["data"]
    assert data["issueDate"] is None
    assert data["dueDate"] is None
    assert data["currency"] == "EUR"
