"""Veranstaltungen: an Event is an element of its own with a team.

The upgrade

1. creates the table ``event`` (F/collaboration/events/003022, 003023),
2. adds the kind ``event`` to the kind checks of ``link`` and the trigger
   ``link_drop_ends`` to ``event``, so a deleted Event takes its links with it (003033),
3. makes an Event of each card with event data (003031): the fields, the creator and the
   date of the card; the team of the board of the card, else the one team entry of the
   board with the role edit or manage, else a new team with the name of the board, its
   person entries as members and its own board; the status ``settled`` for a card in the
   done column or in the archive, else the start status; each link of the card also at
   the Event; and a link between the card and its Event,
4. drops ``todo_card_event``: a card holds no event data (003022).

The upgrade grants no permission, because the rights to an Event come from its team
(003026).

Every step is idempotent. A fresh database already has ``event`` from the ``create_all``
baseline (0001), and its ``todo_card_event`` (from 84414cd99f16) holds no row.

The downgrade gives each card back the event data of the Event that it links, deletes the
links with an Event as an end and drops ``event``. It keeps the teams and boards that the
upgrade made, because they hold work of their own by then.

Revision ID: 7c4e2a9d1b85
Revises: 5d8c2a7e41f3
Create Date: 2026-11-25 23:00:00.000000
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "7c4e2a9d1b85"
down_revision: str | None = "5d8c2a7e41f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The link kinds before this revision.
_OLD: tuple[str, ...] = (
    "application",
    "meeting",
    "agenda_item",
    "vote",
    "appointment",
    "gremium",
    "invoice",
    "expense",
    "order",
    "budget",
    "ticket",
    "todo",
    "paperless",
)
#: The link kinds of this revision: ``event`` after ``order``, as ``LINK_KINDS`` lists them.
_NEW: tuple[str, ...] = (
    *_OLD[: _OLD.index("order") + 1],
    "event",
    *_OLD[_OLD.index("order") + 1 :],
)
#: The characters of a number (as ``app.modules.orders.numbers``).
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

_CREATE = """
CREATE TABLE IF NOT EXISTS event (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    number text NOT NULL,
    team_id uuid NOT NULL,
    status text NOT NULL,
    title text NOT NULL,
    description_md text,
    starts_on date,
    start_time time,
    ends_on date,
    end_time time,
    place text,
    participants integer,
    series_id uuid,
    shop_url text,
    version integer NOT NULL DEFAULT 1,
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_event PRIMARY KEY (id),
    CONSTRAINT uq_event_number UNIQUE (number),
    CONSTRAINT fk_event_team_id_team FOREIGN KEY (team_id)
        REFERENCES team (id) ON DELETE RESTRICT,
    CONSTRAINT fk_event_series_id_todo_event_series FOREIGN KEY (series_id)
        REFERENCES todo_event_series (id) ON DELETE SET NULL,
    CONSTRAINT fk_event_created_by_principal FOREIGN KEY (created_by)
        REFERENCES principal (id) ON DELETE SET NULL,
    CONSTRAINT ck_event_title CHECK (length(btrim(title)) BETWEEN 1 AND 300),
    CONSTRAINT ck_event_dates
        CHECK (ends_on IS NULL OR (starts_on IS NOT NULL AND ends_on >= starts_on)),
    CONSTRAINT ck_event_times CHECK (
        (start_time IS NULL OR starts_on IS NOT NULL)
        AND (end_time IS NULL OR ends_on IS NOT NULL)
        AND (start_time IS NULL OR end_time IS NULL
             OR ends_on > starts_on OR end_time >= start_time)
    ),
    CONSTRAINT ck_event_participants CHECK (participants IS NULL OR participants >= 0),
    CONSTRAINT ck_event_shop_url CHECK (shop_url IS NULL OR shop_url ~* '^https?://')
)
"""
_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_event_team_id ON event (team_id)",
    "CREATE INDEX IF NOT EXISTS ix_event_series_id ON event (series_id)",
    "CREATE INDEX IF NOT EXISTS ix_event_starts_on ON event (starts_on)",
)
_CARD_EVENT = """
CREATE TABLE IF NOT EXISTS todo_card_event (
    card_id uuid PRIMARY KEY REFERENCES todo_card (id) ON DELETE CASCADE,
    starts_on date,
    ends_on date,
    start_time time,
    end_time time,
    place text,
    participants integer,
    series_id uuid REFERENCES todo_event_series (id) ON DELETE SET NULL
)
"""


def _kind_checks(kinds: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{kind}'" for kind in kinds)
    for side in ("a", "b"):
        op.execute(f"ALTER TABLE link DROP CONSTRAINT IF EXISTS ck_link_{side}_kind")
        op.execute(
            f"ALTER TABLE link ADD CONSTRAINT ck_link_{side}_kind CHECK ({side}_kind IN ({listed}))"
        )


def _number(taken: set[str]) -> str:
    """Draw a free number of eight characters."""
    drawn = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return _number(taken) if drawn in taken else drawn


def _status(bind: sa.Connection, done: bool) -> str:
    """The status of a migrated Event: ``settled`` when done, else the start (003031)."""
    wanted = "settled" if done else "planned"
    found = bind.execute(
        sa.text(
            "SELECT key FROM status_def WHERE list_kind = 'event' ORDER BY "
            "(key = :wanted) DESC, "
            "(CASE WHEN :done THEN phase = 'done' ELSE is_start END) DESC, position LIMIT 1"
        ),
        {"wanted": wanted, "done": done},
    ).scalar()
    return str(found or wanted)


def _new_team(bind: sa.Connection, board: Mapping[str, Any], creator: uuid.UUID) -> uuid.UUID:
    """Make a team for a board without one team entry, with its own board (003031, 003067)."""
    team_id = uuid.uuid4()
    bind.execute(
        sa.text("INSERT INTO team (id, name) VALUES (:id, :name)"),
        {"id": team_id, "name": board["name"]},
    )
    entries = bind.execute(
        sa.text(
            "SELECT principal_id, role FROM todo_board_entry "
            "WHERE board_id = :board AND principal_id IS NOT NULL"
        ),
        {"board": board["id"]},
    ).all()
    managers = {pid for pid, role in entries if role == "manage"} or {creator}
    members = {pid for pid, _role in entries} | managers
    for pid in members:
        bind.execute(
            sa.text(
                "INSERT INTO team_member (team_id, principal_id, role) "
                "VALUES (:team, :pid, :role) ON CONFLICT DO NOTHING"
            ),
            {"team": team_id, "pid": pid, "role": "manager" if pid in managers else "member"},
        )
    new_board = uuid.uuid4()
    bind.execute(
        sa.text("INSERT INTO todo_board (id, name, kind, team_id) VALUES (:id, :name, 'team', :t)"),
        {"id": new_board, "name": board["name"], "t": team_id},
    )
    bind.execute(
        sa.text(
            "INSERT INTO todo_column (board_id, name, position, is_done) "
            "SELECT :board, c.name, c.position, c.is_done FROM (VALUES ('Offen', 0, false), "
            "('In Arbeit', 1, false), ('Wartet', 2, false), ('Erledigt', 3, true)) "
            "AS c(name, position, is_done)"
        ),
        {"board": new_board},
    )
    return team_id


def _team_of(
    bind: sa.Connection, board: Mapping[str, Any], creator: uuid.UUID, made: dict[Any, Any]
) -> uuid.UUID:
    """The team of an Event of a card on ``board`` (003031)."""
    if board["team_id"] is not None:
        return board["team_id"]
    if board["id"] in made:
        return made[board["id"]]
    entries = (
        bind.execute(
            sa.text(
                "SELECT team_id FROM todo_board_entry WHERE board_id = :board "
                "AND team_id IS NOT NULL AND role IN ('edit', 'manage')"
            ),
            {"board": board["id"]},
        )
        .scalars()
        .all()
    )
    team = entries[0] if len(entries) == 1 else _new_team(bind, board, creator)
    made[board["id"]] = team
    return team


_CARDS = """
SELECT c.id, c.title, c.description_md, c.created_by, c.created_at, c.archived_at,
       col.is_done, e.starts_on, e.ends_on, e.start_time, e.end_time, e.place,
       e.participants, e.series_id, b.id AS board_id, b.name AS board_name,
       b.team_id AS board_team_id
FROM todo_card_event e
JOIN todo_card c ON c.id = e.card_id
JOIN todo_column col ON col.id = c.column_id
JOIN todo_board b ON b.id = c.board_id
ORDER BY c.created_at, c.id
"""


def _migrate_cards(bind: sa.Connection) -> None:
    """Make an Event of each card with event data (003031)."""
    if bind.execute(sa.text("SELECT to_regclass('todo_card_event')")).scalar() is None:
        return
    taken = set(bind.execute(sa.text("SELECT number FROM event")).scalars().all())
    made: dict[Any, Any] = {}
    for card in bind.execute(sa.text(_CARDS)).mappings().all():
        board = {
            "id": card["board_id"],
            "name": card["board_name"],
            "team_id": card["board_team_id"],
        }
        number = _number(taken)
        taken.add(number)
        event_id = uuid.uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO event (id, number, team_id, status, title, description_md, "
                "starts_on, start_time, ends_on, end_time, place, participants, series_id, "
                "created_by, created_at, updated_at) VALUES (:id, :number, :team, :status, "
                ":title, :description, :starts_on, :start_time, :ends_on, :end_time, :place, "
                ":participants, :series, :creator, :created, :created)"
            ),
            {
                "id": event_id,
                "number": number,
                "team": _team_of(bind, board, card["created_by"], made),
                "status": _status(bind, bool(card["is_done"] or card["archived_at"])),
                "title": (card["title"] or "Veranstaltung")[:300],
                "description": card["description_md"],
                "starts_on": card["starts_on"],
                "start_time": card["start_time"],
                "ends_on": card["ends_on"],
                "end_time": card["end_time"],
                "place": card["place"],
                "participants": card["participants"],
                "series": card["series_id"],
                "creator": card["created_by"],
                "created": card["created_at"],
            },
        )
        others = bind.execute(
            sa.text(
                "SELECT a_kind, a_id, b_kind, b_id, created_by, created_at FROM link "
                "WHERE (a_kind = 'todo' AND a_id = :card) OR (b_kind = 'todo' AND b_id = :card)"
            ),
            {"card": card["id"]},
        ).all()
        ends = [
            (
                (b_kind, b_id, by, at)
                if (a_kind, a_id) == ("todo", card["id"])
                else (a_kind, a_id, by, at)
            )
            for a_kind, a_id, b_kind, b_id, by, at in others
        ]
        for kind, target, by, at in [
            *ends,
            ("todo", card["id"], card["created_by"], card["created_at"]),
        ]:
            _link(bind, ("event", event_id), (kind, target), by, at)


def _link(
    bind: sa.Connection,
    one: tuple[str, uuid.UUID],
    other: tuple[str, uuid.UUID],
    by: uuid.UUID,
    at: Any,
) -> None:
    """Store a link with its ends in the order of ``Link.between``: kind, then id, as bytes."""
    (a_kind, a_id), (b_kind, b_id) = sorted(
        (one, other), key=lambda end: (end[0].encode(), uuid.UUID(str(end[1])).bytes)
    )
    bind.execute(
        sa.text(
            "INSERT INTO link (id, a_kind, a_id, b_kind, b_id, created_by, created_at) "
            "VALUES (gen_random_uuid(), :ak, :ai, :bk, :bi, :by, :at) ON CONFLICT DO NOTHING"
        ),
        {"ak": a_kind, "ai": a_id, "bk": b_kind, "bi": b_id, "by": by, "at": at},
    )


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute(_CREATE)
    for stmt in _INDEXES:
        op.execute(stmt)
    _kind_checks(_NEW)
    op.execute("DROP TRIGGER IF EXISTS link_drop_ends ON event")
    op.execute(
        "CREATE TRIGGER link_drop_ends AFTER DELETE ON event "
        "FOR EACH ROW EXECUTE FUNCTION link_drop_ends('event')"
    )
    _migrate_cards(op.get_bind())
    op.execute("DROP TABLE IF EXISTS todo_card_event")


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    op.execute(_CARD_EVENT)
    op.execute(
        "INSERT INTO todo_card_event (card_id, starts_on, ends_on, start_time, end_time, "
        "place, participants, series_id) "
        "SELECT DISTINCT ON (l.b_id) l.b_id, e.starts_on, e.ends_on, e.start_time, "
        "e.end_time, e.place, e.participants, e.series_id FROM link l "
        "JOIN event e ON e.id = l.a_id WHERE l.a_kind = 'event' AND l.b_kind = 'todo' "
        "ON CONFLICT DO NOTHING"
    )
    op.execute("DELETE FROM link WHERE a_kind = 'event' OR b_kind = 'event'")
    op.execute("DROP TRIGGER IF EXISTS link_drop_ends ON event")
    _kind_checks(_OLD)
    op.execute("DROP TABLE IF EXISTS event")
    op.execute("DROP TABLE IF EXISTS event")
