"""fints_bank_sync: FinTS-Bankabgleich (#fints).

Erweitert ``account`` um die (optionalen) FinTS-Zugangsdaten — die PIN liegt **nur
verschlüsselt** vor (Fernet, ``app.shared.crypto``) — und legt drei Tabellen an:

* ``bank_statement_line`` — gestagete Kontoumsätze (vor dem Buchen). ``idempotency_key``
  je Konto eindeutig → idempotenter Re-Import.
* ``bank_allocation``     — N:M-Zuordnung Umsatz ↔ Buchung (Teil-/Sammelzahlungen).
* ``counterparty_memory`` — Gegen-IBAN → zuletzt gewählte Kostenstelle (Matcher-Vorschlag).

Idempotent (``IF NOT EXISTS``); sauberer Down-Round-Trip. Auf einem frischen Schema
entstehen die Tabellen ohnehin über ``Base.metadata.create_all`` (0002).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035_fints_bank_sync"
down_revision: str | None = "0034_config_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    # — account: FinTS-Zugangsdaten (alle optional; PIN verschlüsselt) —
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_endpoint text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_blz text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_login text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_pin_encrypted text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_tan_mechanism text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_state text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_last_sync_at timestamptz",
    # — bank_statement_line: gestagete Umsätze —
    """
    CREATE TABLE IF NOT EXISTS bank_statement_line (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
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
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_bank_statement_line_idem UNIQUE (account_id, idempotency_key),
        CONSTRAINT bank_statement_line_currency_eur CHECK (currency = 'EUR'),
        CONSTRAINT bank_statement_line_state_valid
            CHECK (match_state IN ('unmatched', 'suggested', 'matched', 'ignored'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_bank_statement_line_account_id "
    "ON bank_statement_line (account_id)",
    "CREATE INDEX IF NOT EXISTS ix_bank_statement_line_match_state "
    "ON bank_statement_line (match_state)",
    "CREATE INDEX IF NOT EXISTS ix_bank_statement_line_booking_date "
    "ON bank_statement_line (booking_date)",
    # — bank_allocation: N:M Umsatz ↔ Buchung —
    """
    CREATE TABLE IF NOT EXISTS bank_allocation (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        statement_line_id uuid NOT NULL
            REFERENCES bank_statement_line (id) ON DELETE CASCADE,
        expense_id uuid NOT NULL REFERENCES budget_expense (id) ON DELETE CASCADE,
        allocated_amount numeric(12, 2) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_bank_allocation_pair UNIQUE (statement_line_id, expense_id),
        CONSTRAINT bank_allocation_amount_positive CHECK (allocated_amount > 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_bank_allocation_statement_line_id "
    "ON bank_allocation (statement_line_id)",
    "CREATE INDEX IF NOT EXISTS ix_bank_allocation_expense_id "
    "ON bank_allocation (expense_id)",
    # — counterparty_memory: Gegen-IBAN → Kostenstelle —
    """
    CREATE TABLE IF NOT EXISTS counterparty_memory (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        counterparty_iban text NOT NULL,
        budget_id uuid REFERENCES budget (id) ON DELETE SET NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_counterparty_memory_iban UNIQUE (counterparty_iban)
    )
    """,
    # — bank_sync_session: kurzlebiger, verschlüsselter TAN-Dialog-Zustand —
    """
    CREATE TABLE IF NOT EXISTS bank_sync_session (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id uuid NOT NULL REFERENCES account (id) ON DELETE CASCADE,
        payload_encrypted text NOT NULL,
        expires_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_bank_sync_session_account_id "
    "ON bank_sync_session (account_id)",
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP TABLE IF EXISTS bank_sync_session",
    "DROP TABLE IF EXISTS counterparty_memory",
    "DROP TABLE IF EXISTS bank_allocation",
    "DROP TABLE IF EXISTS bank_statement_line",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_last_sync_at",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_state",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_tan_mechanism",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_pin_encrypted",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_login",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_blz",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_endpoint",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
