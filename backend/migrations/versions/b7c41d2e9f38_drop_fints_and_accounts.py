"""drop_fints_and_accounts: remove the Konten tab and every FinTS feature.

The bank-reconciliation feature (FinTS fetch, CAMT.053/MT940 import, staged
statement lines, line↔booking allocations) and the accounts (Konten) it was
built on are removed from the product. This revision drops their tables and
columns.

Dropped:

* ``bank_allocation``          — statement line ↔ booking link.
* ``bank_statement_line``      — staged bank transactions.
* ``bank_sync_session``        — pending FinTS TAN sessions.
* ``account_fints_credential`` — per-principal FinTS login/PIN.
* ``counterparty_memory``      — matcher hint per counterparty IBAN.
* ``account``                  — bank account master data.
* ``budget_expense.account_id`` — the booking's account reference.
* the ``account.manage`` and ``budget.reconcile_ignore`` role permissions.

Order matters: the child tables go first, then the ``budget_expense`` column,
then ``account`` itself. ``CASCADE`` is deliberately NOT used — every dependent
object is named here, so an unexpected dependency fails loudly instead of being
dropped silently.

**This deletes data and is not reversible.** Statement lines, allocations and
account master data are gone after the upgrade. ``downgrade`` re-creates the
empty structures so the schema round-trips, but it cannot bring the rows back.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b7c41d2e9f38"
down_revision: str | None = "0048_deadline_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "DROP TABLE IF EXISTS bank_allocation",
    "DROP TABLE IF EXISTS bank_statement_line",
    "DROP TABLE IF EXISTS bank_sync_session",
    "DROP TABLE IF EXISTS account_fints_credential",
    "DROP TABLE IF EXISTS counterparty_memory",
    "DROP INDEX IF EXISTS ix_budget_expense_account_id",
    "ALTER TABLE budget_expense DROP COLUMN IF EXISTS account_id",
    "DROP TABLE IF EXISTS account",
    "DELETE FROM role_permission WHERE permission IN "
    "('account.manage', 'budget.reconcile_ignore')",
)

# Structure only — the rows are gone for good.
_DOWNGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS account (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        name text NOT NULL,
        iban text NOT NULL DEFAULT '',
        active boolean NOT NULL DEFAULT true,
        fints_endpoint text,
        fints_blz text,
        fints_last_balance numeric(14, 2),
        fints_balance_at timestamptz
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_account_name ON account (name)",
    "ALTER TABLE budget_expense ADD COLUMN IF NOT EXISTS account_id uuid "
    "REFERENCES account (id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_budget_expense_account_id "
    "ON budget_expense (account_id)",
    """
    CREATE TABLE IF NOT EXISTS account_fints_credential (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id uuid NOT NULL REFERENCES account (id) ON DELETE CASCADE,
        principal_id uuid NOT NULL REFERENCES principal (id) ON DELETE CASCADE,
        fints_login text NOT NULL,
        fints_pin_encrypted text NOT NULL,
        fints_tan_mechanism text,
        fints_state text,
        fints_last_sync_at timestamptz,
        fints_locked_until timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_account_fints_credential_owner UNIQUE (account_id, principal_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_account_fints_credential_account_id "
    "ON account_fints_credential (account_id)",
    "CREATE INDEX IF NOT EXISTS ix_account_fints_credential_principal_id "
    "ON account_fints_credential (principal_id)",
    """
    CREATE TABLE IF NOT EXISTS bank_statement_line (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        account_id uuid NOT NULL REFERENCES account (id) ON DELETE CASCADE,
        idempotency_key text NOT NULL,
        raw_payload jsonb NOT NULL DEFAULT '{}',
        booking_date date,
        value_date date,
        amount numeric(12, 2) NOT NULL,
        currency char(3) NOT NULL DEFAULT 'EUR',
        purpose text,
        counterparty_name text,
        counterparty_iban text,
        end_to_end_id text,
        reference text,
        match_state text NOT NULL DEFAULT 'unmatched',
        suggested_budget_id uuid REFERENCES budget (id) ON DELETE SET NULL,
        suggested_expense_id uuid REFERENCES budget_expense (id) ON DELETE SET NULL,
        CONSTRAINT uq_bank_statement_line_idem UNIQUE (account_id, idempotency_key),
        CONSTRAINT bank_statement_line_currency_eur CHECK (currency = 'EUR'),
        CONSTRAINT bank_statement_line_state_valid CHECK (
            match_state IN ('unmatched', 'suggested', 'matched', 'ignored')
        )
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_bank_statement_line_account_id "
    "ON bank_statement_line (account_id)",
    "CREATE INDEX IF NOT EXISTS ix_bank_statement_line_match_state "
    "ON bank_statement_line (match_state)",
    "CREATE INDEX IF NOT EXISTS ix_bank_statement_line_booking_date "
    "ON bank_statement_line (booking_date)",
    """
    CREATE TABLE IF NOT EXISTS bank_allocation (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        statement_line_id uuid NOT NULL
            REFERENCES bank_statement_line (id) ON DELETE CASCADE,
        expense_id uuid NOT NULL REFERENCES budget_expense (id) ON DELETE CASCADE,
        allocated_amount numeric(12, 2) NOT NULL,
        CONSTRAINT uq_bank_allocation_pair UNIQUE (statement_line_id, expense_id),
        CONSTRAINT bank_allocation_amount_positive CHECK (allocated_amount > 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_bank_allocation_statement_line_id "
    "ON bank_allocation (statement_line_id)",
    "CREATE INDEX IF NOT EXISTS ix_bank_allocation_expense_id "
    "ON bank_allocation (expense_id)",
    """
    CREATE TABLE IF NOT EXISTS bank_sync_session (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        account_id uuid NOT NULL REFERENCES account (id) ON DELETE CASCADE,
        principal_id uuid NOT NULL REFERENCES principal (id) ON DELETE CASCADE,
        payload_encrypted text NOT NULL,
        expires_at timestamptz NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_bank_sync_session_account_id "
    "ON bank_sync_session (account_id)",
    """
    CREATE TABLE IF NOT EXISTS counterparty_memory (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        counterparty_iban text NOT NULL,
        budget_id uuid REFERENCES budget (id) ON DELETE SET NULL,
        CONSTRAINT uq_counterparty_memory_iban UNIQUE (counterparty_iban)
    )
    """,
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
