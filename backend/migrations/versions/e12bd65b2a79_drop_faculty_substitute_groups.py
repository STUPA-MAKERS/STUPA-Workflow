"""Drop the faculty substitute groups (Z5).

The faculty groups are not in use (user decision 2026-10-05). The per-gremium
substitute pool (`delegation_substitute`) is the only substitute mechanism. No
UI ever wrote the two tables.

The upgrade drops two tables:

* `substitute_group_member`
* `substitute_group`

The upgrade does not keep the rows. The step is idempotent: a fresh database
does not get the tables from the `create_all` baseline (0001) any more, but
`92f23ad77fc5` creates them, so the statements use `IF EXISTS`.

The downgrade is lossy. It creates the two tables again with the DDL of
`92f23ad77fc5`, but empty. The dropped rows do not come back.

The audit actions `delegation_substitute_add` and
`delegation_substitute_remove` stay, because the pool uses them too. Old audit
rows with the target types `substitute_group` and `substitute_group_member`
stay as they are: the audit log is append-only.

Revision ID: e12bd65b2a79
Revises: 4c2570138998
Create Date: 2026-10-06 14:26:31.886362
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e12bd65b2a79"
down_revision: str | None = "4c2570138998"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The DDL of `92f23ad77fc5`, for the lossy downgrade.
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
    # The member table first: its foreign key points to `substitute_group`.
    op.execute("DROP TABLE IF EXISTS substitute_group_member")
    op.execute("DROP TABLE IF EXISTS substitute_group")


def downgrade() -> None:
    # Lossy: the tables come back empty.
    for stmt in _CREATE:
        op.execute(stmt)
