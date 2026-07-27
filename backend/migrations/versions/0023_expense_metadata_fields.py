"""Bookings: extra metadata columns (#1-1/#1-2/#3/#4).

Add the invoice date, the payment date and the recipient or payer
(`correspondent`) to `budget_expense`. Add a free `note`, the receipt number
(`reference_number`), the `payment_method` and a category tag (`category`).
Every new column is nullable, so existing bookings stay valid. All statements
are idempotent (`IF NOT EXISTS`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023_expense_metadata_fields"
down_revision: str | None = "0022_budget_view_gremium"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS invoice_date date",
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS payment_date date",
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS correspondent text",
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS note text",
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS reference_number text",
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS payment_method text",
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS category text",
    (
        "ALTER TABLE budget_expense DROP CONSTRAINT IF EXISTS "
        "budget_expense_payment_method_valid"
    ),
    (
        "ALTER TABLE budget_expense ADD CONSTRAINT budget_expense_payment_method_valid "
        "CHECK (payment_method IS NULL OR payment_method IN "
        "('ueberweisung', 'bar', 'lastschrift', 'karte'))"
    ),
    # The booking list sorts by invoice date by default.
    (
        "CREATE INDEX IF NOT EXISTS ix_budget_expense_invoice_date "
        "ON budget_expense (invoice_date)"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_budget_expense_invoice_date",
    (
        "ALTER TABLE budget_expense DROP CONSTRAINT IF EXISTS "
        "budget_expense_payment_method_valid"
    ),
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS category",
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS payment_method",
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS reference_number",
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS note",
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS correspondent",
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS payment_date",
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS invoice_date",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
