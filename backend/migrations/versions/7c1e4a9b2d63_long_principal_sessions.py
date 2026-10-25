"""Long principal sessions: lifetimes per client and the periodic IdP check.

The upgrade:

1. creates the single-row table `login_settings` and inserts the row
   `(id=1, web_session_days=90, pwa_session_days=180)`. The values replace the
   environment setting `SESSION_TTL_HOURS` (12 hours).
2. adds `auth_session.client` (`web` or `pwa`, default `web`) and
   `auth_session.revalidated_at` (default `now()`). The existing sessions become
   browser sessions that were checked at the migration. They carry no refresh token
   (the old scopes did not ask for one), so they end at their first check after
   `SESSION_REVALIDATE_HOURS`, the same as before.

All steps are idempotent. A fresh database gets the table and the columns from the
`create_all` baseline (0001), because the models already declare them.

The downgrade drops the columns and the table.

Revision ID: 7c1e4a9b2d63
Revises: c87c51e806bd
Create Date: 2026-10-12 16:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "7c1e4a9b2d63"
down_revision: str | None = "c87c51e806bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS login_settings (
    id integer NOT NULL DEFAULT 1,
    web_session_days integer NOT NULL DEFAULT 90,
    pwa_session_days integer NOT NULL DEFAULT 180,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NULL,
    CONSTRAINT pk_login_settings PRIMARY KEY (id),
    CONSTRAINT ck_login_settings_singleton CHECK (id = 1),
    CONSTRAINT ck_login_settings_web_days CHECK (web_session_days BETWEEN 1 AND 400),
    CONSTRAINT ck_login_settings_pwa_days CHECK (pwa_session_days BETWEEN 1 AND 400)
)
"""

_SEED = """
INSERT INTO login_settings (id, web_session_days, pwa_session_days)
VALUES (1, 90, 180)
ON CONFLICT (id) DO NOTHING
"""

_CHECK = "ck_auth_session_client"


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute(_CREATE_TABLE)
    op.execute(_SEED)
    op.execute(
        "ALTER TABLE auth_session ADD COLUMN IF NOT EXISTS client text NOT NULL DEFAULT 'web'"
    )
    op.execute(
        "ALTER TABLE auth_session "
        "ADD COLUMN IF NOT EXISTS revalidated_at timestamptz NOT NULL DEFAULT now()"
    )
    op.execute(f"ALTER TABLE auth_session DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute(
        f"ALTER TABLE auth_session ADD CONSTRAINT {_CHECK} CHECK (client IN ('web', 'pwa'))"
    )


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    op.execute(f"ALTER TABLE auth_session DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute("ALTER TABLE auth_session DROP COLUMN IF EXISTS revalidated_at")
    op.execute("ALTER TABLE auth_session DROP COLUMN IF EXISTS client")
    op.execute("DROP TABLE IF EXISTS login_settings")
