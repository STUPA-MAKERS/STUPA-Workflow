"""Buchungen: Zahlungsmethode ``paypal`` erlauben (#dropdown-paypal).

Erweitert die CHECK-Constraint aus 0023 um ``paypal``. Idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024_expense_paypal"
down_revision: str | None = "0023_expense_metadata_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE budget_expense DROP CONSTRAINT IF EXISTS "
        "budget_expense_payment_method_valid"
    ),
    (
        "ALTER TABLE budget_expense ADD CONSTRAINT budget_expense_payment_method_valid "
        "CHECK (payment_method IS NULL OR payment_method IN "
        "('ueberweisung', 'bar', 'lastschrift', 'karte', 'paypal'))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE budget_expense DROP CONSTRAINT IF EXISTS "
        "budget_expense_payment_method_valid"
    ),
    (
        "ALTER TABLE budget_expense ADD CONSTRAINT budget_expense_payment_method_valid "
        "CHECK (payment_method IS NULL OR payment_method IN "
        "('ueberweisung', 'bar', 'lastschrift', 'karte'))"
    ),
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
