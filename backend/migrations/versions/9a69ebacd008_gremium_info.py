"""gremium_info: the Info tab of a Gremium; the gremium permission ``info.write``.

The upgrade creates ``gremium_info`` (one row per Gremium: Markdown text, links as JSONB,
version, last editor). It adds ``info.write`` to the forced roles ``vorstand`` and
``manager`` of every Gremium, because a new forced permission reaches only new
Gremien through the role catalog, and the backfill of a listing adds missing roles,
never missing permissions.

Idempotent. A fresh database already gets the table from the ``create_all`` baseline
(0001), because the model sits in ``app.models``. A migrated database gets it through
``CREATE TABLE IF NOT EXISTS``.

The downgrade drops the table and removes ``info.write`` from every gremium role.

Revision ID: 9a69ebacd008
Revises: 5d1e8a3c9b72
Create Date: 2026-11-15 14:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "9a69ebacd008"
down_revision: str | None = "5d1e8a3c9b72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS gremium_info (
        gremium_id uuid NOT NULL,
        body_md text NOT NULL DEFAULT '',
        links jsonb NOT NULL DEFAULT '[]',
        version integer NOT NULL DEFAULT 0,
        updated_at timestamptz NOT NULL DEFAULT now(),
        updated_by uuid,
        CONSTRAINT pk_gremium_info PRIMARY KEY (gremium_id),
        CONSTRAINT fk_gremium_info_gremium_id_gremium
            FOREIGN KEY (gremium_id) REFERENCES gremium (id) ON DELETE CASCADE,
        CONSTRAINT fk_gremium_info_updated_by_principal
            FOREIGN KEY (updated_by) REFERENCES principal (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_gremium_info_updated_by ON gremium_info (updated_by)",
    (
        "UPDATE gremium_role SET permissions = permissions || '[\"info.write\"]'::jsonb "
        "WHERE key IN ('vorstand', 'manager') AND NOT permissions ? 'info.write'"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "UPDATE gremium_role SET permissions = permissions - 'info.write' "
    "WHERE permissions ? 'info.write'",
    "DROP TABLE IF EXISTS gremium_info",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
