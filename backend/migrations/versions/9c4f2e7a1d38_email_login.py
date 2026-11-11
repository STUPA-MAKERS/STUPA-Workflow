"""email_login: the ``email_login_link`` table and the e-mail binding of a session.

The e-mail login opens an applicant session for an address instead of one
application. ``applicant_session.application_id`` becomes nullable, the new
``email`` column holds the address, and a CHECK keeps exactly one binding.

Idempotent. A fresh database already gets the table, the column and the CHECK from
the ``create_all`` baseline (0001), because the models sit in ``app.models``. A
migrated database gets them through ``IF NOT EXISTS`` and a drop before the add of
the CHECK.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "9c4f2e7a1d38"
down_revision: str | None = "e4a91c27b6d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS email_login_link (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        email citext NOT NULL,
        token_hash bytea NOT NULL,
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        CONSTRAINT uq_email_login_link_token_hash UNIQUE (token_hash)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_email_login_link_expires_at "
        "ON email_login_link (expires_at)"
    ),
    "ALTER TABLE applicant_session ALTER COLUMN application_id DROP NOT NULL",
    "ALTER TABLE applicant_session ADD COLUMN IF NOT EXISTS email citext",
    (
        "ALTER TABLE applicant_session "
        "DROP CONSTRAINT IF EXISTS ck_applicant_session_one_binding"
    ),
    (
        "ALTER TABLE applicant_session ADD CONSTRAINT ck_applicant_session_one_binding "
        "CHECK ((application_id IS NULL) <> (email IS NULL))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE applicant_session "
        "DROP CONSTRAINT IF EXISTS ck_applicant_session_one_binding"
    ),
    "DELETE FROM applicant_session WHERE application_id IS NULL",
    "ALTER TABLE applicant_session DROP COLUMN IF EXISTS email",
    "ALTER TABLE applicant_session ALTER COLUMN application_id SET NOT NULL",
    "DROP TABLE IF EXISTS email_login_link",
)


def upgrade() -> None:
    """Create the link table and let a session bind to an address."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the e-mail sessions, the column and the link table."""
    for statement in _DOWNGRADE:
        op.execute(statement)
