"""Groups of Antragsarten with a text per group and a manual order (specs 001180, 001183).

The upgrade creates ``application_type_group`` (an i18n name, an i18n Markdown text and a
sort position) and gives ``application_type`` the columns ``group_id`` and ``position``. A
deleted group leaves its types without a group (``ON DELETE SET NULL``).

The upgrade numbers the existing types in the order of their key, because the key set the
order before, so step 1 keeps its order until an admin moves a type.

Idempotent. A fresh database already has the table and the columns from the
``create_all`` baseline (0001), because the models sit in ``app.models``. The default
privileges in ``deploy/db/roles.sql`` give the ``app`` role access to the new table.

Revision ID: b7e2c4a91f03
Revises: a3f1c7e2d905
Create Date: 2026-11-16 17:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b7e2c4a91f03"
down_revision: str | None = "a3f1c7e2d905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS application_type_group (
        id uuid DEFAULT gen_random_uuid() NOT NULL,
        created_at timestamptz DEFAULT now() NOT NULL,
        name_i18n jsonb DEFAULT '{}' NOT NULL,
        text_i18n jsonb DEFAULT '{}' NOT NULL,
        position integer DEFAULT 0 NOT NULL,
        CONSTRAINT pk_application_type_group PRIMARY KEY (id)
    )
    """,
    "ALTER TABLE application_type ADD COLUMN IF NOT EXISTS group_id uuid",
    "ALTER TABLE application_type ADD COLUMN IF NOT EXISTS position integer DEFAULT 0 NOT NULL",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conname = 'fk_application_type_group_id_application_type_group'
        ) THEN
            ALTER TABLE application_type
              ADD CONSTRAINT fk_application_type_group_id_application_type_group
              FOREIGN KEY (group_id) REFERENCES application_type_group (id) ON DELETE SET NULL;
        END IF;
    END $$
    """,
    "CREATE INDEX IF NOT EXISTS ix_application_type_group_id ON application_type (group_id)",
    """
    UPDATE application_type AS t
       SET position = n.rn
      FROM (SELECT id, row_number() OVER (ORDER BY key) - 1 AS rn FROM application_type) AS n
     WHERE t.id = n.id AND t.position = 0 AND t.group_id IS NULL
    """,
)


def upgrade() -> None:
    """Add the groups of Antragsarten and the manual order."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the groups of Antragsarten and the manual order."""
    op.execute("DROP INDEX IF EXISTS ix_application_type_group_id")
    op.execute(
        "ALTER TABLE application_type DROP CONSTRAINT IF EXISTS "
        "fk_application_type_group_id_application_type_group"
    )
    op.execute("ALTER TABLE application_type DROP COLUMN IF EXISTS position")
    op.execute("ALTER TABLE application_type DROP COLUMN IF EXISTS group_id")
    op.execute("DROP TABLE IF EXISTS application_type_group")
