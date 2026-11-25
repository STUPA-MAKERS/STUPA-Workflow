"""Bestellungen: an expense booking can name a Bestellung.

The upgrade adds ``budget_expense.order_id`` (``ON DELETE SET NULL``) with its index. A
booking keeps its row when its Bestellung goes with the Antrag, and it loses only the
reference (F/finance/orders/002878).

Every key is named like the baseline names it, so both paths match. Both steps are
idempotent, because a fresh database gets the column from the ``create_all`` baseline (0001).

Revision ID: 9d2f6a4b81c7
Revises: c41b9e62d7a3
Create Date: 2026-11-24 23:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "9d2f6a4b81c7"
down_revision: str | None = "c41b9e62d7a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS order_id uuid "
        "CONSTRAINT fk_budget_expense_order_id_purchase_order "
        "REFERENCES purchase_order (id) ON DELETE SET NULL"
    ),
    "CREATE INDEX IF NOT EXISTS ix_budget_expense_order_id ON budget_expense (order_id)",
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_budget_expense_order_id",
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS order_id",
)


def upgrade() -> None:
    """Add the reference of a booking to its Bestellung."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the reference of a booking to its Bestellung."""
    for statement in _DOWNGRADE:
        op.execute(statement)
