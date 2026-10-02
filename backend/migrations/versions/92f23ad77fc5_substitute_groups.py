"""Add the faculty substitute groups (Z5).

The upgrade creates two tables:

* `substitute_group` is a faculty group of one gremium with an i18n name and a
  sort position. The unique pair `(id, gremium_id)` is the target of the
  composite foreign key below.
* `substitute_group_member` puts a principal into a group as `member` or as
  `substitute`. The primary key is `(group_id, principal_id)`. The column
  `gremium_id` is a copy of the gremium of the group. The composite foreign key
  on `(group_id, gremium_id)` keeps the copy correct and deletes the rows with
  the group. A partial unique index puts a member into at most one group per
  gremium.

The step is idempotent: a fresh database already gets the tables from the
`create_all` baseline (0001), so the statements use `IF NOT EXISTS`.

There is no data migration. The existing `delegation_substitute` entries stay
valid. The administration adds the faculty groups.

The default privileges in `deploy/db/roles.sql` give the `app` role access to
the new tables, so no grant is necessary.

The downgrade drops both tables.

Revision ID: 92f23ad77fc5
Revises: 734556b61a72
Create Date: 2026-10-02 10:12:44.118930
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "92f23ad77fc5"
down_revision: str | None = "734556b61a72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS substitute_group (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        gremium_id uuid NOT NULL
            CONSTRAINT fk_substitute_group_gremium_id_gremium
            REFERENCES gremium (id) ON DELETE CASCADE,
        name_i18n jsonb NOT NULL DEFAULT '{}',
        position integer NOT NULL DEFAULT 0,
        created_by text,
        CONSTRAINT uq_substitute_group_id_gremium UNIQUE (id, gremium_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_substitute_group_gremium ON substitute_group (gremium_id)",
    """
    CREATE TABLE IF NOT EXISTS substitute_group_member (
        created_at timestamptz NOT NULL DEFAULT now(),
        group_id uuid NOT NULL,
        principal_id uuid NOT NULL
            CONSTRAINT fk_substitute_group_member_principal_id_principal
            REFERENCES principal (id) ON DELETE CASCADE,
        gremium_id uuid NOT NULL,
        kind text NOT NULL,
        created_by text,
        CONSTRAINT pk_substitute_group_member PRIMARY KEY (group_id, principal_id),
        CONSTRAINT fk_substitute_group_member_group
            FOREIGN KEY (group_id, gremium_id)
            REFERENCES substitute_group (id, gremium_id) ON DELETE CASCADE,
        CONSTRAINT ck_substitute_group_member_kind
            CHECK (kind IN ('member', 'substitute'))
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_substitute_group_member_gremium_member "
    "ON substitute_group_member (gremium_id, principal_id) WHERE kind = 'member'",
    "CREATE INDEX IF NOT EXISTS ix_substitute_group_member_principal "
    "ON substitute_group_member (principal_id)",
)


def upgrade() -> None:
    for stmt in _CREATE:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS substitute_group_member")
    op.execute("DROP TABLE IF EXISTS substitute_group")
