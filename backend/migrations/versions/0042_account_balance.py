"""account_balance: store the last bank balance per account (#fints-konten).

A FinTS sync (HKSAL balance) or a file import (``:62F:`` or CLBD closing balance) writes
the balance and its cut-off date to the account. The value only serves the display and the
reconciliation in the accounts tab. It is NOT part of the budget calculation. The migration
only adds columns and is idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0042_account_balance"
down_revision: str | None = "0041_fints_cp_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_last_balance numeric(14, 2)")
    op.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_balance_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE account DROP COLUMN IF EXISTS fints_balance_at")
    op.execute("ALTER TABLE account DROP COLUMN IF EXISTS fints_last_balance")
