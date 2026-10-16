"""To-dos: the ten ``todo_*`` tables, ``meeting_agenda_item.todo_id`` and the data.

The upgrade:

1. creates ``todo_board`` (kind ``gremium|personal|team`` with exactly the owner
   column of the kind, one board per gremium and per owner), ``todo_column`` (one
   done column per board), ``todo_card`` (``rank`` with the collation ``C``),
   ``todo_assignee``, ``todo_label`` (unique name per board, case-insensitive),
   ``todo_card_label``, ``todo_check_item``, ``todo_comment``, ``todo_event`` and
   ``todo_link`` (exactly one target).
2. adds ``meeting_agenda_item.todo_id`` (``ON DELETE SET NULL``) with the unique
   index ``uq_agenda_meeting_todo``.
3. adds the gremium permission ``todo.write`` to every gremium role and
   ``todo.configure`` to the roles ``vorstand`` and ``manager``.
4. creates a board for every gremium without one, named after the gremium, with the
   columns Offen, In Arbeit, Wartet and Erledigt (the done column).
5. creates the team board "Plattform" for ``ticket.manage`` with the same columns,
   unless a team board with that permission exists.

Every key is named ``pk_<table>`` like the baseline names it, so both paths match.
All steps are idempotent. A fresh database already gets the tables and the column
from the ``create_all`` baseline (0001), because the models sit in ``app.models``.

The downgrade removes the grants, the column and the tables in reverse order.

Revision ID: 59ccfd0a0856
Revises: 86718c748401
Create Date: 2026-10-16 00:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "59ccfd0a0856"
down_revision: str | None = "86718c748401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS todo_board (
        id uuid CONSTRAINT pk_todo_board PRIMARY KEY DEFAULT gen_random_uuid(),
        name text NOT NULL,
        kind text NOT NULL,
        gremium_id uuid CONSTRAINT fk_todo_board_gremium_id_gremium
            REFERENCES gremium (id) ON DELETE CASCADE,
        owner_id uuid CONSTRAINT fk_todo_board_owner_id_principal REFERENCES principal (id),
        permission text,
        archive_after_days integer DEFAULT 30,
        archived_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_todo_board_kind CHECK (kind IN ('gremium', 'personal', 'team')),
        CONSTRAINT ck_todo_board_owner CHECK (
            (kind = 'gremium' AND gremium_id IS NOT NULL AND owner_id IS NULL
                AND permission IS NULL)
            OR (kind = 'personal' AND owner_id IS NOT NULL AND gremium_id IS NULL
                AND permission IS NULL)
            OR (kind = 'team' AND permission IS NOT NULL AND gremium_id IS NULL
                AND owner_id IS NULL)
        ),
        CONSTRAINT ck_todo_board_archive_after_days
            CHECK (archive_after_days IS NULL OR archive_after_days BETWEEN 1 AND 365)
    )
    """,
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_board_gremium ON todo_board (gremium_id) "
        "WHERE gremium_id IS NOT NULL"
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_board_owner ON todo_board (owner_id) "
        "WHERE owner_id IS NOT NULL"
    ),
    """
    CREATE TABLE IF NOT EXISTS todo_column (
        id uuid CONSTRAINT pk_todo_column PRIMARY KEY DEFAULT gen_random_uuid(),
        board_id uuid NOT NULL CONSTRAINT fk_todo_column_board_id_todo_board
            REFERENCES todo_board (id) ON DELETE CASCADE,
        name text NOT NULL,
        position integer NOT NULL DEFAULT 0,
        is_done boolean NOT NULL DEFAULT false
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_todo_column_board_id ON todo_column (board_id)",
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_column_done ON todo_column (board_id) "
        "WHERE is_done"
    ),
    """
    CREATE TABLE IF NOT EXISTS todo_card (
        id uuid CONSTRAINT pk_todo_card PRIMARY KEY DEFAULT gen_random_uuid(),
        board_id uuid NOT NULL CONSTRAINT fk_todo_card_board_id_todo_board
            REFERENCES todo_board (id) ON DELETE CASCADE,
        column_id uuid NOT NULL CONSTRAINT fk_todo_card_column_id_todo_column
            REFERENCES todo_column (id),
        rank text COLLATE "C" NOT NULL,
        title text NOT NULL,
        description_md text,
        due_date date,
        due_reminded_on date,
        created_by uuid NOT NULL CONSTRAINT fk_todo_card_created_by_principal
            REFERENCES principal (id),
        completed_at timestamptz,
        archived_at timestamptz,
        version integer NOT NULL DEFAULT 1,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_todo_card_board_column_rank "
        "ON todo_card (board_id, column_id, rank)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_todo_card_due_date ON todo_card (due_date) "
        "WHERE archived_at IS NULL"
    ),
    """
    CREATE TABLE IF NOT EXISTS todo_assignee (
        card_id uuid NOT NULL CONSTRAINT fk_todo_assignee_card_id_todo_card
            REFERENCES todo_card (id) ON DELETE CASCADE,
        principal_id uuid NOT NULL CONSTRAINT fk_todo_assignee_principal_id_principal
            REFERENCES principal (id),
        CONSTRAINT pk_todo_assignee PRIMARY KEY (card_id, principal_id)
    )
    """,
    ("CREATE INDEX IF NOT EXISTS ix_todo_assignee_principal_id ON todo_assignee (principal_id)"),
    """
    CREATE TABLE IF NOT EXISTS todo_label (
        id uuid CONSTRAINT pk_todo_label PRIMARY KEY DEFAULT gen_random_uuid(),
        board_id uuid NOT NULL CONSTRAINT fk_todo_label_board_id_todo_board
            REFERENCES todo_board (id) ON DELETE CASCADE,
        name text NOT NULL,
        color text NOT NULL,
        CONSTRAINT ck_todo_label_color
            CHECK (color IN ('green', 'blue', 'violet', 'amber', 'red', 'gray'))
    )
    """,
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_label_board_name "
        "ON todo_label (board_id, lower(name))"
    ),
    """
    CREATE TABLE IF NOT EXISTS todo_card_label (
        card_id uuid NOT NULL CONSTRAINT fk_todo_card_label_card_id_todo_card
            REFERENCES todo_card (id) ON DELETE CASCADE,
        label_id uuid NOT NULL CONSTRAINT fk_todo_card_label_label_id_todo_label
            REFERENCES todo_label (id) ON DELETE CASCADE,
        CONSTRAINT pk_todo_card_label PRIMARY KEY (card_id, label_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS todo_check_item (
        id uuid CONSTRAINT pk_todo_check_item PRIMARY KEY DEFAULT gen_random_uuid(),
        card_id uuid NOT NULL CONSTRAINT fk_todo_check_item_card_id_todo_card
            REFERENCES todo_card (id) ON DELETE CASCADE,
        text text NOT NULL,
        done boolean NOT NULL DEFAULT false,
        position integer NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_todo_check_item_card_id ON todo_check_item (card_id)",
    """
    CREATE TABLE IF NOT EXISTS todo_comment (
        id uuid CONSTRAINT pk_todo_comment PRIMARY KEY DEFAULT gen_random_uuid(),
        card_id uuid NOT NULL CONSTRAINT fk_todo_comment_card_id_todo_card
            REFERENCES todo_card (id) ON DELETE CASCADE,
        author_id uuid NOT NULL CONSTRAINT fk_todo_comment_author_id_principal
            REFERENCES principal (id),
        body text NOT NULL,
        mentions jsonb NOT NULL DEFAULT '[]'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        edited_at timestamptz,
        deleted_at timestamptz
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_todo_comment_card_id ON todo_comment (card_id)",
    """
    CREATE TABLE IF NOT EXISTS todo_event (
        id uuid CONSTRAINT pk_todo_event PRIMARY KEY DEFAULT gen_random_uuid(),
        card_id uuid NOT NULL CONSTRAINT fk_todo_event_card_id_todo_card
            REFERENCES todo_card (id) ON DELETE CASCADE,
        actor_id uuid CONSTRAINT fk_todo_event_actor_id_principal REFERENCES principal (id),
        kind text NOT NULL,
        payload jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_todo_event_kind CHECK (kind IN (
            'created', 'moved', 'assigned', 'due', 'linked', 'unlinked', 'checklist',
            'renamed', 'archived', 'restored'
        ))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_todo_event_card_id ON todo_event (card_id)",
    """
    CREATE TABLE IF NOT EXISTS todo_link (
        id uuid CONSTRAINT pk_todo_link PRIMARY KEY DEFAULT gen_random_uuid(),
        card_id uuid NOT NULL CONSTRAINT fk_todo_link_card_id_todo_card
            REFERENCES todo_card (id) ON DELETE CASCADE,
        application_id uuid CONSTRAINT fk_todo_link_application_id_application
            REFERENCES application (id) ON DELETE CASCADE,
        meeting_id uuid CONSTRAINT fk_todo_link_meeting_id_meeting
            REFERENCES meeting (id) ON DELETE CASCADE,
        agenda_item_id uuid CONSTRAINT fk_todo_link_agenda_item_id_meeting_agenda_item
            REFERENCES meeting_agenda_item (id) ON DELETE CASCADE,
        ticket_id uuid CONSTRAINT fk_todo_link_ticket_id_ticket
            REFERENCES ticket (id) ON DELETE CASCADE,
        todo_id uuid CONSTRAINT fk_todo_link_todo_id_todo_card
            REFERENCES todo_card (id) ON DELETE CASCADE,
        created_by uuid NOT NULL CONSTRAINT fk_todo_link_created_by_principal
            REFERENCES principal (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_todo_link_one_target CHECK (
            num_nonnulls(application_id, meeting_id, agenda_item_id, ticket_id, todo_id) = 1
        )
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_todo_link_card_id ON todo_link (card_id)",
)

_LINK_COLUMNS: tuple[str, ...] = (
    "application_id",
    "meeting_id",
    "agenda_item_id",
    "ticket_id",
    "todo_id",
)

_LINK_INDEXES: tuple[str, ...] = tuple(
    stmt
    for column in _LINK_COLUMNS
    for stmt in (
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_link_{column} "
        f"ON todo_link (card_id, {column}) WHERE {column} IS NOT NULL",
        f"CREATE INDEX IF NOT EXISTS ix_todo_link_{column} "
        f"ON todo_link ({column}) WHERE {column} IS NOT NULL",
    )
)

_AGENDA: tuple[str, ...] = (
    (
        "ALTER TABLE meeting_agenda_item ADD COLUMN IF NOT EXISTS todo_id uuid "
        "CONSTRAINT fk_meeting_agenda_item_todo_id_todo_card "
        "REFERENCES todo_card (id) ON DELETE SET NULL"
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agenda_meeting_todo "
        "ON meeting_agenda_item (meeting_id, todo_id) WHERE todo_id IS NOT NULL"
    ),
)

_GRANTS: tuple[str, ...] = (
    (
        "UPDATE gremium_role "
        "SET permissions = COALESCE(permissions, '[]'::jsonb) || '[\"todo.write\"]'::jsonb "
        "WHERE NOT COALESCE(permissions, '[]'::jsonb) ? 'todo.write'"
    ),
    (
        "UPDATE gremium_role "
        "SET permissions = COALESCE(permissions, '[]'::jsonb) || '[\"todo.configure\"]'::jsonb "
        "WHERE key IN ('vorstand', 'manager') "
        "AND NOT COALESCE(permissions, '[]'::jsonb) ? 'todo.configure'"
    ),
)

# The four default columns of a new board, as rows of (name, position, is_done).
_COLUMNS_SQL = (
    "INSERT INTO todo_column (board_id, name, position, is_done) "
    "SELECT b.id, c.name, c.position, c.is_done FROM {boards} b "
    "CROSS JOIN (VALUES ('Offen', 0, false), ('In Arbeit', 1, false), "
    "('Wartet', 2, false), ('Erledigt', 3, true)) AS c(name, position, is_done)"
)

_BOARDS: tuple[str, ...] = (
    (
        "WITH boards AS ("
        "INSERT INTO todo_board (name, kind, gremium_id) "
        "SELECT g.name, 'gremium', g.id FROM gremium g "
        "WHERE NOT EXISTS (SELECT 1 FROM todo_board t WHERE t.gremium_id = g.id) "
        "RETURNING id) " + _COLUMNS_SQL.format(boards="boards")
    ),
    (
        "WITH boards AS ("
        "INSERT INTO todo_board (name, kind, permission) "
        "SELECT 'Plattform', 'team', 'ticket.manage' "
        "WHERE NOT EXISTS (SELECT 1 FROM todo_board t "
        "WHERE t.kind = 'team' AND t.permission = 'ticket.manage') "
        "RETURNING id) " + _COLUMNS_SQL.format(boards="boards")
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "UPDATE gremium_role SET permissions = permissions - 'todo.configure' "
    "WHERE permissions ? 'todo.configure'",
    "UPDATE gremium_role SET permissions = permissions - 'todo.write' "
    "WHERE permissions ? 'todo.write'",
    "DROP INDEX IF EXISTS uq_agenda_meeting_todo",
    "ALTER TABLE meeting_agenda_item DROP COLUMN IF EXISTS todo_id",
    "DROP TABLE IF EXISTS todo_link",
    "DROP TABLE IF EXISTS todo_event",
    "DROP TABLE IF EXISTS todo_comment",
    "DROP TABLE IF EXISTS todo_check_item",
    "DROP TABLE IF EXISTS todo_card_label",
    "DROP TABLE IF EXISTS todo_label",
    "DROP TABLE IF EXISTS todo_assignee",
    "DROP TABLE IF EXISTS todo_card",
    "DROP TABLE IF EXISTS todo_column",
    "DROP TABLE IF EXISTS todo_board",
)


def upgrade() -> None:
    for stmt in (*_TABLES, *_LINK_INDEXES, *_AGENDA, *_GRANTS, *_BOARDS):
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
