"""subbookings: Unterbuchungen je Buchung (#subbookings).

``budget_expense.parent_expense_id`` (Self-FK, ON DELETE CASCADE) macht eine Buchung zur
Unterbuchung einer Eltern-Buchung. Kinder erben Konto/Kostenstelle/HHJ/Art (kopierte Spalten);
der Eltern-Betrag ist die Summe der Kinder. Der Budget-Rollup zählt nur Eltern
(``parent_expense_id IS NULL``). Additiv + idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0043_subbookings"
down_revision: str | None = "0042_account_balance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS parent_expense_id uuid "
        "REFERENCES budget_expense (id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_budget_expense_parent_expense_id "
        "ON budget_expense (parent_expense_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_budget_expense_parent_expense_id")
    op.execute("ALTER TABLE budget_expense DROP COLUMN IF EXISTS parent_expense_id")
