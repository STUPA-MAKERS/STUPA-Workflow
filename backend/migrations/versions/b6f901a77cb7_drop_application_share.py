"""drop_application_share: remove the public read-only links to an application.

The feature is gone from the code, so the table ``application_share`` and the
permission ``application.share`` go too. The upgrade deletes every share row, so a
link that someone still holds stops working. It also deletes the permission from every
global role and from every gremium role.

The downgrade brings back the empty table and the grant to ``admin`` only, the state of
``e5d02c8a41f7``. The deleted rows do not come back, because the database never held
the tokens, only their hashes.

Revision ID: b6f901a77cb7
Revises: a3c1e7f20b94
Create Date: 2026-11-05 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b6f901a77cb7"
down_revision: str | None = "a3c1e7f20b94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every statement is idempotent, because migration 0001 builds a fresh schema from the
#: current models, which have no share table.
_UPGRADE: tuple[str, ...] = (
    "DROP TABLE IF EXISTS application_share",
    "DELETE FROM role_permission WHERE permission = 'application.share'",
    (
        "UPDATE gremium_role SET permissions = permissions - 'application.share' "
        "WHERE permissions ? 'application.share'"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS application_share (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        application_id uuid NOT NULL
            REFERENCES application (id) ON DELETE CASCADE,
        token_hash bytea NOT NULL,
        expires_at timestamptz NOT NULL,
        revoked_at timestamptz,
        created_by text,
        label text
    )
    """,
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_application_share_token_hash "
        "ON application_share (token_hash)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_application_share_application_id "
        "ON application_share (application_id)"
    ),
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'application.share' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
