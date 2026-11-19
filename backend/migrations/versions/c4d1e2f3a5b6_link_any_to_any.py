"""Links between any two elements: the table ``link`` replaces ``todo_link`` (001400-001403).

The upgrade:

1. creates ``link`` (``a_kind``, ``a_id``, ``b_kind``, ``b_id``, ``created_by``,
   ``created_at``) with the kind checks, the check ``ck_link_not_self``, the unique index
   ``uq_link_ends`` and the lookup index ``ix_link_b``.
2. copies each row of ``todo_link`` with the card as one end and the target as the other
   end. The ends are in the stored order (``Link.between``): the kind by byte order
   (``COLLATE "C"``), then the id. Two rows that link the same two cards in both
   directions become one link; the older row wins, so ``created_by`` and ``created_at``
   stay those of the first link.
3. drops ``todo_link``.
4. creates the function ``link_drop_ends`` and an ``AFTER DELETE`` trigger of the same
   name on the table of each kind: a deleted element takes its links with it, as the
   ``ON DELETE CASCADE`` of ``todo_link`` did.

Every step is idempotent. A fresh database already gets ``link`` from the ``create_all``
baseline (0001), because the model sits in ``app.models``; it gets the triggers here.

The downgrade creates ``todo_link`` again with the links that have a card end, drops the
triggers, the function and ``link``. A link without a card end is lost, because
``todo_link`` has no place for it. A link between two cards becomes one row, with the
``a`` end as the card, because ``todo_link`` showed one row from both cards.

Revision ID: c4d1e2f3a5b6
Revises: a4c71e2b9d05
Create Date: 2026-11-19 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c4d1e2f3a5b6"
down_revision: str | None = "a4c71e2b9d05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The table of each link kind and the target column of ``todo_link``.
KINDS: tuple[tuple[str, str, str], ...] = (
    ("application", "application", "application_id"),
    ("meeting", "meeting", "meeting_id"),
    ("agenda_item", "meeting_agenda_item", "agenda_item_id"),
    ("vote", "vote", "vote_id"),
    ("appointment", "calendar_appointment", "appointment_id"),
    ("gremium", "gremium", "gremium_id"),
    ("invoice", "invoice", "invoice_id"),
    ("expense", "budget_expense", "expense_id"),
    ("budget", "budget", "budget_id"),
    ("ticket", "ticket", "ticket_id"),
    ("todo", "todo_card", "todo_id"),
)
_KIND_LIST = ", ".join(f"'{kind}'" for kind, _t, _c in KINDS)


def _create_link() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS link (
            id uuid CONSTRAINT pk_link PRIMARY KEY DEFAULT gen_random_uuid(),
            a_kind text NOT NULL,
            a_id uuid NOT NULL,
            b_kind text NOT NULL,
            b_id uuid NOT NULL,
            created_by uuid NOT NULL CONSTRAINT fk_link_created_by_principal
                REFERENCES principal (id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_link_a_kind CHECK (a_kind IN ({_KIND_LIST})),
            CONSTRAINT ck_link_b_kind CHECK (b_kind IN ({_KIND_LIST})),
            CONSTRAINT ck_link_not_self CHECK (NOT (a_kind = b_kind AND a_id = b_id))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_link_ends ON link (a_kind, a_id, b_kind, b_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_link_b ON link (b_kind, b_id)")


def _copy_todo_links() -> None:
    target_kind = (
        "CASE "
        + " ".join(f"WHEN {column} IS NOT NULL THEN '{kind}'" for kind, _t, column in KINDS)
        + " END"
    )
    target_id = "COALESCE(" + ", ".join(column for _k, _t, column in KINDS) + ")"
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('public.todo_link') IS NULL THEN
                RETURN;
            END IF;
            INSERT INTO link (id, a_kind, a_id, b_kind, b_id, created_by, created_at)
            SELECT DISTINCT ON (a_kind, a_id, b_kind, b_id)
                id, a_kind, a_id, b_kind, b_id, created_by, created_at
            FROM (
                SELECT
                    t.id, t.created_by, t.created_at,
                    CASE WHEN ord THEN 'todo' ELSE target_kind END AS a_kind,
                    CASE WHEN ord THEN t.card_id ELSE target_id END AS a_id,
                    CASE WHEN ord THEN target_kind ELSE 'todo' END AS b_kind,
                    CASE WHEN ord THEN target_id ELSE t.card_id END AS b_id
                FROM (
                    SELECT
                        l.*,
                        {target_kind} AS target_kind,
                        {target_id} AS target_id,
                        ('todo' COLLATE "C" < ({target_kind}) COLLATE "C")
                            OR ('todo' = {target_kind} AND l.card_id <= {target_id}) AS ord
                    FROM todo_link l
                ) t
            ) o
            ORDER BY a_kind, a_id, b_kind, b_id, created_at, id
            ON CONFLICT DO NOTHING;
            DROP TABLE todo_link;
        END $$
        """
    )


def _create_triggers() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION link_drop_ends() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM link
            WHERE (a_kind = TG_ARGV[0] AND a_id = OLD.id)
               OR (b_kind = TG_ARGV[0] AND b_id = OLD.id);
            RETURN OLD;
        END $$
        """
    )
    for kind, table, _column in KINDS:
        op.execute(f"DROP TRIGGER IF EXISTS link_drop_ends ON {table}")
        op.execute(
            f"CREATE TRIGGER link_drop_ends AFTER DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION link_drop_ends('{kind}')"
        )


def upgrade() -> None:
    """Create ``link``, move the card links into it, drop ``todo_link``, add the triggers."""
    _create_link()
    _copy_todo_links()
    _create_triggers()


def downgrade() -> None:
    """Create ``todo_link`` again from the links with a card end and drop ``link``."""
    columns = ",\n".join(
        f"{column} uuid CONSTRAINT fk_todo_link_{column}_{table} "
        f"REFERENCES {table} (id) ON DELETE CASCADE"
        for _k, table, column in KINDS
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS todo_link (
            id uuid CONSTRAINT pk_todo_link PRIMARY KEY DEFAULT gen_random_uuid(),
            card_id uuid NOT NULL CONSTRAINT fk_todo_link_card_id_todo_card
                REFERENCES todo_card (id) ON DELETE CASCADE,
            {columns},
            created_by uuid NOT NULL CONSTRAINT fk_todo_link_created_by_principal
                REFERENCES principal (id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_todo_link_one_target CHECK (
                num_nonnulls({", ".join(c for _k, _t, c in KINDS)}) = 1
            )
        )
        """
    )
    for kind, _table, column in KINDS:
        sides = (("a", "b"),) if kind == "todo" else (("a", "b"), ("b", "a"))
        for own, other in sides:
            op.execute(
                f"""
                INSERT INTO todo_link (id, card_id, {column}, created_by, created_at)
                SELECT gen_random_uuid(), {own}_id, {other}_id, created_by, created_at
                FROM link WHERE {own}_kind = 'todo' AND {other}_kind = '{kind}'
                """
            )
    for _kind, table, _column in KINDS:
        op.execute(f"DROP TRIGGER IF EXISTS link_drop_ends ON {table}")
    op.execute("DROP FUNCTION IF EXISTS link_drop_ends()")
    op.execute("DROP TABLE IF EXISTS link")
