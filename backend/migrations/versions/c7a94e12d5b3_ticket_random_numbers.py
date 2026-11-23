"""Tickets: the number becomes eight random characters.

The upgrade:

1. changes ``ticket.number`` from an integer of ``ticket_number_seq`` to text.
2. gives each existing ticket a new random number, because a number in sequence shows
   the count of the tickets and lets a person guess the number of a different ticket.
3. writes the new number into each status event that names a duplicate
   (``payload.duplicateOf``), so the timeline does not name a number that finds no
   ticket.
4. drops the sequence.

The upgrade does nothing when the column is text already. A fresh database gets the
text column from the ``create_all`` baseline (0001), because the model sits in
``app.models``; only the sequence of the older ticket migration is left to drop.

The downgrade numbers the tickets in the order of their creation, because the random
numbers have no order, and restores the sequence. The events keep the text that they
have.

Revision ID: c7a94e12d5b3
Revises: b4b30d8dba4d
Create Date: 2026-11-23 16:00:00.000000
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7a94e12d5b3"
down_revision: str | None = "b4b30d8dba4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_LENGTH = 8

_COLUMN_TYPE = sa.text(
    "SELECT data_type FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = 'ticket' AND column_name = 'number'"
)


def _draw(taken: set[str]) -> str:
    """Draw a number that is not in ``taken``."""
    candidate = "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
    return candidate if candidate not in taken else _draw(taken)


def _old_form(number: int) -> str:
    """Render a number of the sequence the way the events stored it."""
    return f"T-{number:04d}"


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    bind = op.get_bind()
    if bind.scalar(_COLUMN_TYPE) != "integer":
        op.execute("DROP SEQUENCE IF EXISTS ticket_number_seq")
        return
    rows = bind.execute(sa.text("SELECT id, number FROM ticket ORDER BY number")).all()
    taken: set[str] = set()
    fresh: dict[int, str] = {}
    for _, old in rows:
        fresh[old] = _draw(taken)
        taken.add(fresh[old])
    op.execute("ALTER TABLE ticket ALTER COLUMN number DROP DEFAULT")
    op.execute("ALTER TABLE ticket ALTER COLUMN number TYPE text USING number::text")
    for ticket_id, old in rows:
        bind.execute(
            sa.text("UPDATE ticket SET number = :number WHERE id = :id"),
            {"number": fresh[old], "id": ticket_id},
        )
        bind.execute(
            sa.text(
                "UPDATE ticket_event "
                "SET payload = jsonb_set(payload, '{duplicateOf}', to_jsonb(CAST(:new AS text))) "
                "WHERE kind = 'status' AND payload ->> 'duplicateOf' = :old"
            ),
            {"new": f"T-{fresh[old]}", "old": _old_form(old)},
        )
    op.execute("DROP SEQUENCE IF EXISTS ticket_number_seq")


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    bind = op.get_bind()
    if bind.scalar(_COLUMN_TYPE) == "integer":
        return
    op.execute("CREATE SEQUENCE IF NOT EXISTS ticket_number_seq")
    op.execute("ALTER TABLE ticket DROP CONSTRAINT IF EXISTS uq_ticket_number")
    op.execute(
        "UPDATE ticket SET number = ranked.position::text FROM ("
        "SELECT id, row_number() OVER (ORDER BY created_at, id) AS position FROM ticket"
        ") AS ranked WHERE ticket.id = ranked.id"
    )
    op.execute("ALTER TABLE ticket ALTER COLUMN number TYPE integer USING number::integer")
    op.execute(
        "SELECT setval('ticket_number_seq', "
        "COALESCE((SELECT max(number) FROM ticket), 0) + 1, false)"
    )
    op.execute("ALTER TABLE ticket ALTER COLUMN number SET DEFAULT nextval('ticket_number_seq')")
    op.execute("ALTER TABLE ticket ADD CONSTRAINT uq_ticket_number UNIQUE (number)")
    op.execute("ALTER SEQUENCE ticket_number_seq OWNED BY ticket.number")
