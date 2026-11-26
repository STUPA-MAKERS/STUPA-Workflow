"""team_info: the Info tab of a free team (F/collaboration/teams/003077).

The upgrade creates ``team_info`` (one row per team: Markdown text, links as JSONB,
version, last editor), the same shape as ``gremium_info``.

Idempotent. A fresh database already gets the table from the ``create_all`` baseline
(0001), because the model sits in ``app.models``. A migrated database gets it through
``CREATE TABLE IF NOT EXISTS``.

The downgrade drops the table.

Revision ID: ffe68b6e919b
Revises: b3e7d1c9a402
Create Date: 2026-11-26 11:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "ffe68b6e919b"
down_revision: str | None = "b3e7d1c9a402"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS team_info (
        team_id uuid NOT NULL,
        body_md text NOT NULL DEFAULT '',
        links jsonb NOT NULL DEFAULT '[]',
        version integer NOT NULL DEFAULT 0,
        updated_at timestamptz NOT NULL DEFAULT now(),
        updated_by uuid,
        CONSTRAINT pk_team_info PRIMARY KEY (team_id),
        CONSTRAINT fk_team_info_team_id_team
            FOREIGN KEY (team_id) REFERENCES team (id) ON DELETE CASCADE,
        CONSTRAINT fk_team_info_updated_by_principal
            FOREIGN KEY (updated_by) REFERENCES principal (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_team_info_updated_by ON team_info (updated_by)",
)

_DOWNGRADE: tuple[str, ...] = ("DROP TABLE IF EXISTS team_info",)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
