"""Geldbetrags-Obergrenze auf den Buchungs-/Übertrags-Schemata (AUD-035).

Die DB-Spalten sind ``numeric(12, 2)`` (max 9 999 999 999.99). Ohne ``le``-Schranke
passierte ein zu großer Betrag die Pydantic-Validierung und führte erst beim INSERT
zu einem numeric-overflow-500 statt des vertraglich zugesicherten 422. Diese Tests
fixieren die Schranke auf ``ExpenseCreate``/``ExpenseUpdate``/``TransferCreate``.
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
    # Genau am Limit bleibt gültig.
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
