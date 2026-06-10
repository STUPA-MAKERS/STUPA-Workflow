"""Konten (Bankkonten) + Übertrag-Verknüpfung an Buchungen + account.manage-Recht.

Idempotent: frische DBs erhalten Tabelle/Spalten aus ``create_all`` (Baseline) → dann
No-op; migrierte DBs tragen nach.

* ``account`` — Konto (Name + IBAN-Freitext), nicht an Kostenstellen gebunden.
* ``budget_expense.account_id`` (FK SET NULL) + ``transfer_id`` (verknüpft die beiden
  Buchungen eines Übertrags).
* ``account.manage`` an die Rollen ``manager`` + ``finance`` (admin hat ohnehin alles).
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
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS account_id uuid REFERENCES account(id) ON DELETE SET NULL",
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS transfer_id uuid",
    "CREATE INDEX IF NOT EXISTS ix_budget_expense_account_id ON budget_expense (account_id)",
    "CREATE INDEX IF NOT EXISTS ix_budget_expense_transfer_id ON budget_expense (transfer_id)",
    # account.manage an manager + finance (admin bypasst Rechte ohnehin).
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
