"""Rechnungen (#invoices): ``invoice`` Tabelle + ``budget_expense.invoice_id``.

Eigenständige Rechnungen (optional aus ZUGFeRD/Factur-X importiert); Buchungen
referenzieren optional eine Rechnung (1 Rechnung : N Buchungen). Idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025_invoices"
down_revision: str | None = "0024_expense_paypal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "CREATE TABLE IF NOT EXISTS invoice ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " number text,"
        " issue_date date,"
        " due_date date,"
        " supplier text,"
        " net_amount numeric(12,2),"
        " tax_amount numeric(12,2),"
        " gross_amount numeric(12,2) NOT NULL,"
        " currency char(3) NOT NULL DEFAULT 'EUR',"
        " note text,"
        " status text NOT NULL DEFAULT 'open',"
        " file_object_key text,"
        " file_name text,"
        " file_mime text,"
        " actor text,"
        " CONSTRAINT invoice_currency_eur CHECK (currency = 'EUR'),"
        " CONSTRAINT invoice_status_valid CHECK (status IN ('open', 'paid')),"
        " CONSTRAINT invoice_gross_nonneg CHECK (gross_amount >= 0)"
        ")"
    ),
    "CREATE INDEX IF NOT EXISTS ix_invoice_number ON invoice (number)",
    "CREATE INDEX IF NOT EXISTS ix_invoice_issue_date ON invoice (issue_date)",
    (
        "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS invoice_id uuid "
        "REFERENCES invoice (id) ON DELETE SET NULL"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_budget_expense_invoice_id "
        "ON budget_expense (invoice_id)"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_budget_expense_invoice_id",
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS invoice_id",
    "DROP TABLE IF EXISTS invoice",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
