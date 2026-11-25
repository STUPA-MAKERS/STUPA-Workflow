"""Teams: every Gremium gets its inherent team; boards, entries and invitations name teams.

The upgrade

1. creates ``team`` and ``team_member`` (F/collaboration/teams/003060, 003063),
2. creates the inherent team of every Gremium without one (003061),
3. renames the board kind ``team`` (a board of a global permission) to ``permission``
   (003073), then the kind ``gremium`` to ``team``, and replaces
   ``todo_board.gremium_id`` by ``todo_board.team_id``: the board of a Gremium becomes
   the board of its inherent team (003067),
4. creates a board for every team without one, with the four default columns,
5. replaces ``gremium_id`` by ``team_id`` in ``todo_board_entry`` (003068),
   ``calendar_invitation`` (003069) and ``calendar_external`` (003070); each row moves
   to the inherent team of its Gremium,
6. gives the Gremium permission ``team.manage`` to every Gremium role that holds
   ``todo.configure`` (003066).

Every step is idempotent. A fresh database already has the new tables and columns from
the ``create_all`` baseline (0001), so a step that finds no ``gremium_id`` column skips.

The downgrade moves the rows of the inherent teams back to their Gremien and deletes the
rows of the free teams, because the old schema has no place for them.

Revision ID: 9f288998cf57
Revises: e5a1c7d93b20
Create Date: 2026-11-25 19:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f288998cf57"
down_revision: str | None = "e5a1c7d93b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS team ("
    "name TEXT, parent_id UUID, gremium_id UUID, "
    "id UUID DEFAULT gen_random_uuid() NOT NULL, "
    "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, "
    "CONSTRAINT pk_team PRIMARY KEY (id), "
    "CONSTRAINT ck_team_name CHECK ((gremium_id IS NULL) <> (name IS NULL)), "
    "CONSTRAINT ck_team_inherent_root CHECK (gremium_id IS NULL OR parent_id IS NULL), "
    "CONSTRAINT ck_team_not_own_parent CHECK (parent_id IS NULL OR parent_id <> id), "
    "CONSTRAINT fk_team_parent_id_team FOREIGN KEY(parent_id) REFERENCES team (id) "
    "ON DELETE RESTRICT, "
    "CONSTRAINT uq_team_gremium_id UNIQUE (gremium_id), "
    "CONSTRAINT fk_team_gremium_id_gremium FOREIGN KEY(gremium_id) REFERENCES gremium (id) "
    "ON DELETE CASCADE)",
    "CREATE INDEX IF NOT EXISTS ix_team_parent_id ON team (parent_id)",
    "CREATE TABLE IF NOT EXISTS team_member ("
    "team_id UUID NOT NULL, principal_id UUID NOT NULL, "
    "role TEXT DEFAULT 'member' NOT NULL, "
    "CONSTRAINT pk_team_member PRIMARY KEY (team_id, principal_id), "
    "CONSTRAINT ck_team_member_role CHECK (role IN ('member', 'manager')), "
    "CONSTRAINT fk_team_member_team_id_team FOREIGN KEY(team_id) REFERENCES team (id) "
    "ON DELETE CASCADE, "
    "CONSTRAINT fk_team_member_principal_id_principal FOREIGN KEY(principal_id) "
    "REFERENCES principal (id) ON DELETE CASCADE)",
    "CREATE INDEX IF NOT EXISTS ix_team_member_principal_id ON team_member (principal_id)",
    "INSERT INTO team (gremium_id) SELECT g.id FROM gremium g "
    "WHERE NOT EXISTS (SELECT 1 FROM team t WHERE t.gremium_id = g.id)",
)

_BOARD_OWNER = (
    "(kind = 'team' AND team_id IS NOT NULL AND owner_id IS NULL AND permission IS NULL) OR "
    "(kind = 'personal' AND owner_id IS NOT NULL AND team_id IS NULL AND permission IS NULL) OR "
    "(kind = 'permission' AND permission IS NOT NULL AND team_id IS NULL "
    "AND owner_id IS NULL) OR "
    "(kind = 'free' AND team_id IS NULL AND owner_id IS NULL AND permission IS NULL)"
)

_BOARD: tuple[str, ...] = (
    "ALTER TABLE todo_board DROP CONSTRAINT IF EXISTS ck_todo_board_owner",
    "ALTER TABLE todo_board DROP CONSTRAINT IF EXISTS ck_todo_board_kind",
    "ALTER TABLE todo_board ADD COLUMN team_id UUID",
    "UPDATE todo_board b SET team_id = t.id FROM team t WHERE t.gremium_id = b.gremium_id",
    "UPDATE todo_board SET kind = 'permission' WHERE kind = 'team'",
    "UPDATE todo_board SET kind = 'team' WHERE kind = 'gremium'",
    "DROP INDEX IF EXISTS uq_todo_board_gremium",
    "ALTER TABLE todo_board DROP COLUMN gremium_id",
    "ALTER TABLE todo_board ADD CONSTRAINT fk_todo_board_team_id_team "
    "FOREIGN KEY(team_id) REFERENCES team (id) ON DELETE CASCADE",
    "CREATE UNIQUE INDEX uq_todo_board_team ON todo_board (team_id) WHERE team_id IS NOT NULL",
    "ALTER TABLE todo_board ADD CONSTRAINT ck_todo_board_kind "
    "CHECK (kind IN ('team', 'personal', 'permission', 'free'))",
    f"ALTER TABLE todo_board ADD CONSTRAINT ck_todo_board_owner CHECK ({_BOARD_OWNER})",
)

_TEAM_BOARDS = (
    "WITH boards AS ("
    "INSERT INTO todo_board (name, kind, team_id) "
    "SELECT COALESCE(t.name, g.name), 'team', t.id FROM team t "
    "LEFT JOIN gremium g ON g.id = t.gremium_id "
    "WHERE NOT EXISTS (SELECT 1 FROM todo_board b WHERE b.team_id = t.id) "
    "RETURNING id) "
    "INSERT INTO todo_column (board_id, name, position, is_done) "
    "SELECT b.id, c.name, c.position, c.is_done FROM boards b "
    "CROSS JOIN (VALUES ('Offen', 0, false), ('In Arbeit', 1, false), "
    "('Wartet', 2, false), ('Erledigt', 3, true)) AS c(name, position, is_done)"
)


def _target(table: str, other: str) -> tuple[str, ...]:
    """Move the Gremium target of ``table`` to the inherent team; ``other`` is the person."""
    other_check = f"(team_id IS NULL) <> ({other} IS NULL)" if other else None
    return (
        f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_target",
        f"ALTER TABLE {table} ADD COLUMN team_id UUID",
        f"UPDATE {table} x SET team_id = t.id FROM team t WHERE t.gremium_id = x.gremium_id",
        f"ALTER TABLE {table} DROP COLUMN gremium_id",
        f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_team_id_team "
        "FOREIGN KEY(team_id) REFERENCES team (id) ON DELETE CASCADE",
        f"CREATE INDEX IF NOT EXISTS ix_{table}_team_id ON {table} (team_id)",
        *(
            (f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_target CHECK ({other_check})",)
            if other_check
            else ()
        ),
    )


_ENTRY: tuple[str, ...] = (
    "DROP INDEX IF EXISTS uq_todo_board_entry_gremium",
    *_target("todo_board_entry", "principal_id"),
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_board_entry_team "
    "ON todo_board_entry (board_id, team_id) WHERE team_id IS NOT NULL",
)

_INVITATION: tuple[str, ...] = (
    "DROP INDEX IF EXISTS uq_calendar_invitation_gremium",
    *_target("calendar_invitation", "principal_id"),
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_calendar_invitation_team "
    "ON calendar_invitation (appointment_id, team_id) WHERE team_id IS NOT NULL",
)

_EXTERNAL: tuple[str, ...] = _target("calendar_external", "")

_GRANT = (
    "UPDATE gremium_role "
    "SET permissions = COALESCE(permissions, '[]'::jsonb) || '[\"team.manage\"]'::jsonb "
    "WHERE COALESCE(permissions, '[]'::jsonb) ? 'todo.configure' "
    "AND NOT COALESCE(permissions, '[]'::jsonb) ? 'team.manage'"
)


def _has_column(table: str, column: str) -> bool:
    """Tell if ``table`` has ``column`` in the database of the migration."""
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _TABLES:
        op.execute(stmt)
    for table, steps in (
        ("todo_board", _BOARD),
        ("todo_board_entry", _ENTRY),
        ("calendar_invitation", _INVITATION),
        ("calendar_external", _EXTERNAL),
    ):
        if _has_column(table, "gremium_id"):
            for stmt in steps:
                op.execute(stmt)
    op.execute(_TEAM_BOARDS)
    op.execute(_GRANT)


def _back(table: str) -> tuple[str, ...]:
    """Move the team target of ``table`` back to the Gremium; free teams drop their rows."""
    return (
        f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_target",
        f"ALTER TABLE {table} ADD COLUMN gremium_id UUID REFERENCES gremium (id) ON DELETE CASCADE",
        f"UPDATE {table} x SET gremium_id = t.gremium_id FROM team t WHERE t.id = x.team_id",
        f"DELETE FROM {table} WHERE team_id IS NOT NULL AND gremium_id IS NULL",
        f"ALTER TABLE {table} DROP COLUMN team_id",
    )


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    op.execute(
        "UPDATE gremium_role SET permissions = permissions - 'team.manage' "
        "WHERE permissions ? 'team.manage'"
    )
    for stmt in (
        *_back("todo_board_entry"),
        "ALTER TABLE todo_board_entry ADD CONSTRAINT ck_todo_board_entry_target "
        "CHECK ((gremium_id IS NULL) <> (principal_id IS NULL))",
        "CREATE UNIQUE INDEX uq_todo_board_entry_gremium "
        "ON todo_board_entry (board_id, gremium_id) WHERE gremium_id IS NOT NULL",
        "CREATE INDEX ix_todo_board_entry_gremium_id ON todo_board_entry (gremium_id)",
        *_back("calendar_invitation"),
        "ALTER TABLE calendar_invitation ADD CONSTRAINT ck_calendar_invitation_target "
        "CHECK ((gremium_id IS NULL) <> (principal_id IS NULL))",
        "CREATE UNIQUE INDEX uq_calendar_invitation_gremium "
        "ON calendar_invitation (appointment_id, gremium_id) WHERE gremium_id IS NOT NULL",
        "CREATE INDEX ix_calendar_invitation_gremium_id ON calendar_invitation (gremium_id)",
        "ALTER TABLE calendar_external ADD COLUMN gremium_id UUID "
        "REFERENCES gremium (id) ON DELETE CASCADE",
        "UPDATE calendar_external x SET gremium_id = t.gremium_id FROM team t "
        "WHERE t.id = x.team_id",
        "DELETE FROM calendar_external WHERE team_id IS NOT NULL AND gremium_id IS NULL",
        "ALTER TABLE calendar_external DROP COLUMN team_id",
        "CREATE INDEX ix_calendar_external_gremium_id ON calendar_external (gremium_id)",
        "ALTER TABLE todo_board DROP CONSTRAINT IF EXISTS ck_todo_board_owner",
        "ALTER TABLE todo_board DROP CONSTRAINT IF EXISTS ck_todo_board_kind",
        "ALTER TABLE todo_board ADD COLUMN gremium_id UUID "
        "REFERENCES gremium (id) ON DELETE CASCADE",
        "UPDATE todo_board b SET gremium_id = t.gremium_id FROM team t WHERE t.id = b.team_id",
        "DELETE FROM todo_board WHERE kind = 'team' AND gremium_id IS NULL",
        "UPDATE todo_board SET kind = 'gremium' WHERE kind = 'team'",
        "UPDATE todo_board SET kind = 'team' WHERE kind = 'permission'",
        "ALTER TABLE todo_board DROP COLUMN team_id",
        "CREATE UNIQUE INDEX uq_todo_board_gremium ON todo_board (gremium_id) "
        "WHERE gremium_id IS NOT NULL",
        "ALTER TABLE todo_board ADD CONSTRAINT ck_todo_board_kind "
        "CHECK (kind IN ('gremium', 'personal', 'team', 'free'))",
        "ALTER TABLE todo_board ADD CONSTRAINT ck_todo_board_owner CHECK ("
        "(kind = 'gremium' AND gremium_id IS NOT NULL AND owner_id IS NULL "
        "AND permission IS NULL) OR "
        "(kind = 'personal' AND owner_id IS NOT NULL AND gremium_id IS NULL "
        "AND permission IS NULL) OR "
        "(kind = 'team' AND permission IS NOT NULL AND gremium_id IS NULL "
        "AND owner_id IS NULL) OR "
        "(kind = 'free' AND gremium_id IS NULL AND owner_id IS NULL AND permission IS NULL))",
        "DROP TABLE IF EXISTS team_member",
        "DROP TABLE IF EXISTS team",
    ):
        op.execute(stmt)
