"""To-dos: free boards and member entries; the global permission ``todo.create_board``.

The upgrade:

1. widens ``ck_todo_board_kind`` and ``ck_todo_board_owner`` for the kind ``free``, a
   board without an owner column (spec 001060).
2. creates ``todo_board_entry``: the member entries of a board, each one gremium or one
   person with the role ``read``, ``edit`` or ``manage`` (specs 001062, 001077).
3. grants ``todo.create_board`` to the role ``admin`` (spec 001061). The admin bypass
   grants it anyway; the row makes the role page show it.

Idempotent. A fresh database already gets the table and the constraints from the
``create_all`` baseline (0001), because the models sit in ``app.models``.

The downgrade deletes the free boards, drops the table, restores the old checks and
removes the permission rows.

Revision ID: c6010961aa02
Revises: 5e7a2c9d4b18
Create Date: 2026-11-16 04:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c6010961aa02"
down_revision: str | None = "5e7a2c9d4b18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNER_OLD = (
    "(kind = 'gremium' AND gremium_id IS NOT NULL AND owner_id IS NULL "
    "AND permission IS NULL) OR "
    "(kind = 'personal' AND owner_id IS NOT NULL AND gremium_id IS NULL "
    "AND permission IS NULL) OR "
    "(kind = 'team' AND permission IS NOT NULL AND gremium_id IS NULL "
    "AND owner_id IS NULL)"
)
_OWNER_NEW = (
    _OWNER_OLD + " OR (kind = 'free' AND gremium_id IS NULL AND owner_id IS NULL "
    "AND permission IS NULL)"
)

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE todo_board DROP CONSTRAINT IF EXISTS ck_todo_board_kind",
    "ALTER TABLE todo_board ADD CONSTRAINT ck_todo_board_kind "
    "CHECK (kind IN ('gremium', 'personal', 'team', 'free'))",
    "ALTER TABLE todo_board DROP CONSTRAINT IF EXISTS ck_todo_board_owner",
    f"ALTER TABLE todo_board ADD CONSTRAINT ck_todo_board_owner CHECK ({_OWNER_NEW})",
    """
    CREATE TABLE IF NOT EXISTS todo_board_entry (
        id uuid CONSTRAINT pk_todo_board_entry PRIMARY KEY DEFAULT gen_random_uuid(),
        board_id uuid NOT NULL CONSTRAINT fk_todo_board_entry_board_id_todo_board
            REFERENCES todo_board (id) ON DELETE CASCADE,
        gremium_id uuid CONSTRAINT fk_todo_board_entry_gremium_id_gremium
            REFERENCES gremium (id) ON DELETE CASCADE,
        principal_id uuid CONSTRAINT fk_todo_board_entry_principal_id_principal
            REFERENCES principal (id) ON DELETE CASCADE,
        role text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_todo_board_entry_role CHECK (role IN ('read', 'edit', 'manage')),
        CONSTRAINT ck_todo_board_entry_target
            CHECK ((gremium_id IS NULL) <> (principal_id IS NULL))
    )
    """,
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_board_entry_gremium "
        "ON todo_board_entry (board_id, gremium_id) WHERE gremium_id IS NOT NULL"
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_board_entry_principal "
        "ON todo_board_entry (board_id, principal_id) WHERE principal_id IS NOT NULL"
    ),
    "CREATE INDEX IF NOT EXISTS ix_todo_board_entry_gremium_id ON todo_board_entry (gremium_id)",
    (
        "CREATE INDEX IF NOT EXISTS ix_todo_board_entry_principal_id "
        "ON todo_board_entry (principal_id)"
    ),
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'todo.create_board' FROM role r WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'todo.create_board'",
    "DROP TABLE IF EXISTS todo_board_entry",
    "DELETE FROM todo_board WHERE kind = 'free'",
    "ALTER TABLE todo_board DROP CONSTRAINT IF EXISTS ck_todo_board_owner",
    f"ALTER TABLE todo_board ADD CONSTRAINT ck_todo_board_owner CHECK ({_OWNER_OLD})",
    "ALTER TABLE todo_board DROP CONSTRAINT IF EXISTS ck_todo_board_kind",
    "ALTER TABLE todo_board ADD CONSTRAINT ck_todo_board_kind "
    "CHECK (kind IN ('gremium', 'personal', 'team'))",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
