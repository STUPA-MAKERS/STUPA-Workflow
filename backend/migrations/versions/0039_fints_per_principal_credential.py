"""fints_principal_creds: split the FinTS credentials per principal (#fints-percred).

Several bookers share the same bank account, but each one has a **separate** online
banking login. Login, PIN, TAN method and client state therefore move from the account
into the new ``account_fints_credential`` table (account by principal, PIN encrypted).
The account keeps only the **bank connection** that is the same for everyone
(``fints_endpoint`` and ``fints_blz``). The migration also binds the TAN session to the
principal that starts it.

Nobody used the feature in production yet, because there was no live bank test. The old
account columns therefore need no data transfer. The migration drops them. It is
idempotent (``IF (NOT) EXISTS``) and has a clean down round trip.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0039_fints_principal_creds"
down_revision: str | None = "0038_gremium_membership_overlap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The TAN session gets the principal that starts it. The existing sessions are deleted
#: first, because they are short lived and worthless after the deploy, and old rows
#: have no useful default for the NOT NULL column.
_UPGRADE: tuple[str, ...] = (
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
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_account_fints_credential_owner UNIQUE (account_id, principal_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_account_fints_credential_account_id "
    "ON account_fints_credential (account_id)",
    "CREATE INDEX IF NOT EXISTS ix_account_fints_credential_principal_id "
    "ON account_fints_credential (principal_id)",
    "DELETE FROM bank_sync_session",
    "ALTER TABLE bank_sync_session ADD COLUMN IF NOT EXISTS principal_id uuid "
    "NOT NULL REFERENCES principal (id) ON DELETE CASCADE",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_last_sync_at",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_state",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_tan_mechanism",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_pin_encrypted",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_login",
)

#: The account columns come back empty, because the upgrade removed the data for good.
_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_login text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_pin_encrypted text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_tan_mechanism text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_state text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_last_sync_at timestamptz",
    "DELETE FROM bank_sync_session",
    "ALTER TABLE bank_sync_session DROP COLUMN IF EXISTS principal_id",
    "DROP TABLE IF EXISTS account_fints_credential",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
