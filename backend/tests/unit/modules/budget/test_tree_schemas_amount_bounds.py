"""Amount cap on the booking and transfer schemas.

The DB columns are `numeric(12, 2)`, so the maximum is 9 999 999 999.99. Without the
`le` bound, Pydantic accepted a larger amount. The INSERT then failed with a numeric
overflow 500 instead of the 422 that the contract promises. These tests pin the cap on
`ExpenseCreate`, `ExpenseUpdate`, `TransferCreate` and `AllocationSet`, and the EUR-only
currency of `BudgetNodeCreate` (§F/finance/budget/000253).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.budget.tree_schemas import (
    _MAX_AMOUNT,
    AllocationSet,
    BudgetNodeCreate,
    ExpenseCreate,
    ExpenseUpdate,
    TransferCreate,
)

_OVER_CAP = _MAX_AMOUNT + Decimal("0.01")


def test_expense_create_rejects_over_cap_amount() -> None:
    with pytest.raises(ValidationError):
        ExpenseCreate(amount=_OVER_CAP, description="x", budgetId=uuid.uuid4())
    ok = ExpenseCreate(amount=_MAX_AMOUNT, description="x", budgetId=uuid.uuid4())
    assert ok.amount == _MAX_AMOUNT


def test_expense_update_rejects_over_cap_amount() -> None:
    with pytest.raises(ValidationError):
        ExpenseUpdate(amount=_OVER_CAP)
    ok = ExpenseUpdate(amount=_MAX_AMOUNT)
    assert ok.amount == _MAX_AMOUNT


def test_transfer_create_rejects_over_cap_amount() -> None:
    with pytest.raises(ValidationError):
        TransferCreate(
            fromBudgetId=uuid.uuid4(),
            toBudgetId=uuid.uuid4(),
            fiscalYearId=uuid.uuid4(),
            amount=_OVER_CAP,
            description="x",
        )


def test_allocation_set_rejects_over_cap_amount() -> None:
    """An allocation above ``numeric(12, 2)`` gives 422 (§F/finance/budget/000253)."""
    with pytest.raises(ValidationError):
        AllocationSet(allocated=_OVER_CAP)
    assert AllocationSet(allocated=_MAX_AMOUNT).allocated == _MAX_AMOUNT


def test_budget_node_create_accepts_only_eur() -> None:
    """A currency other than EUR gives 422, not a 500 (§F/finance/budget/000253)."""
    with pytest.raises(ValidationError):
        BudgetNodeCreate.model_validate({"key": "k", "name": "n", "currency": "USD"})
    assert BudgetNodeCreate(key="k", name="n").currency == "EUR"
