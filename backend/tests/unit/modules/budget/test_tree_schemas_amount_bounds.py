"""Amount cap on the booking and transfer schemas (AUD-035).

The DB columns are `numeric(12, 2)`, so the maximum is 9 999 999 999.99. Without the
`le` bound, Pydantic accepted a larger amount. The INSERT then failed with a numeric
overflow 500 instead of the 422 that the contract promises. These tests pin the cap on
`ExpenseCreate`, `ExpenseUpdate` and `TransferCreate`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.budget.tree_schemas import (
    _MAX_AMOUNT,
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
