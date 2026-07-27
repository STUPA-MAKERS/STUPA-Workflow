"""Accounts (bank accounts), the transfer link on bookings, and the account.manage right.

Idempotent. A fresh database gets the table and the columns from `create_all`
(baseline), so this migration is a no-op there. A migrated database gets them here.

* `account`: a bank account with a name and a free-text IBAN. It is not bound to a
  cost center.
* `budget_expense.account_id` (FK SET NULL) and `transfer_id`. `transfer_id` links the
  two bookings of one transfer.
* `account.manage` goes to the roles `manager` and `finance`. The `admin` role holds
  every permission anyway.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_accounts_and_transfers"
down_revision: str | None = "0004_budget_fully_bound"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS account (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        name text NOT NULL,
        iban text NOT NULL DEFAULT '',
        active boolean NOT NULL DEFAULT true
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_account_name ON account (name)",
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS account_id uuid "
    "REFERENCES account(id) ON DELETE SET NULL",
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS transfer_id uuid",
    "CREATE INDEX IF NOT EXISTS ix_budget_expense_account_id ON budget_expense (account_id)",
    "CREATE INDEX IF NOT EXISTS ix_budget_expense_transfer_id ON budget_expense (transfer_id)",
    """
    INSERT INTO role_permission (role_id, permission)
    SELECT r.id, 'account.manage' FROM role r WHERE r.key IN ('manager', 'finance')
    ON CONFLICT DO NOTHING
    """,
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'account.manage'",
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS transfer_id",
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS account_id",
    "DROP TABLE IF EXISTS account",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
