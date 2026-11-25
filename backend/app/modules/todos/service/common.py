"""Shared constants, types and small helpers of the to-do service."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.modules.auth.people import DELETED_PERSON, PersonRef
from app.modules.todos.grouping import grouped
from app.modules.todos.link_store import Edge
from app.modules.todos.links import Resolved
from app.modules.todos.models import (
    LINK_KINDS,
    TodoBoard,
    TodoBoardEntry,
    TodoCard,
    TodoCardEvent,
    TodoColumn,
)
from app.shared.errors import ConflictError, ValidationProblem

#: The local calendar of the due dates ("due within 7 days", "due tomorrow").
BERLIN = ZoneInfo("Europe/Berlin")


#: An open card due within this many days counts in ``dueSoonCount``.
DUE_SOON_DAYS = 7


#: The length of the comment excerpt in the mention mail.
EXCERPT_LENGTH = 200


MailKind = Literal["assigned", "mentioned", "board_added"]


_KIND_ORDER = {"personal": 0, "team": 1, "free": 2, "permission": 3}


#: The most persons that the shared picker answers for one query.
_PICKER_PEOPLE = 10


def _now() -> datetime:
    return datetime.now(UTC)


def berlin_today(now: datetime | None = None) -> date:
    """Return today's date in Europe/Berlin."""
    return (now or _now()).astimezone(BERLIN).date()


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _invalid(msg: str, code: str, field_name: str) -> ValidationProblem:
    return ValidationProblem(msg, code=code, errors=[{"field": field_name, "msg": msg}])


@dataclass(frozen=True, slots=True)
class TodoMail:
    """A mail that the router sends after the commit.

    ``event_id`` is new for every mail and goes into the idempotency key, because
    the key is the arq job id: a second assignment or an identical mention on the
    same card would otherwise reuse the key and arq would drop it.
    """

    kind: MailKind
    card_id: uuid.UUID | None
    recipients: tuple[uuid.UUID, ...]
    actor_id: uuid.UUID
    excerpt: str | None = None
    event_id: uuid.UUID = field(default_factory=uuid.uuid4, compare=False)
    #: ``board_added``: the board and the role of the new entry (spec 001071).
    board_id: uuid.UUID | None = None
    role: str | None = None


@dataclass(frozen=True, slots=True)
class CardLink:
    """A link as a card shows it: the id of the row and the other end (spec 001401)."""

    id: uuid.UUID
    kind: str
    target_id: uuid.UUID


def card_links(found: Iterable[Edge]) -> dict[uuid.UUID, tuple[CardLink, ...]]:
    """The links of each card, the oldest first: a link has no direction (spec 001401)."""
    pairs = ((edge.own_id, CardLink(edge.id, edge.kind, edge.target_id)) for edge in found)
    return {card_id: _first_per_target(group) for card_id, group in grouped(pairs).items()}


def _first_per_target(links: Sequence[CardLink]) -> tuple[CardLink, ...]:
    """Keep the first link to each target, in order: a link in each direction shows once."""
    first = {(c.kind, c.target_id): c for c in reversed(links)}
    return tuple(first[key] for key in dict.fromkeys((c.kind, c.target_id) for c in links))


@dataclass(frozen=True, slots=True)
class _Facts:
    """What the tiles of a set of cards show, loaded in one query per kind."""

    labels: Mapping[uuid.UUID, tuple[uuid.UUID, ...]] = field(default_factory=dict)
    assignees: Mapping[uuid.UUID, tuple[uuid.UUID, ...]] = field(default_factory=dict)
    checklist: Mapping[uuid.UUID, tuple[int, int]] = field(default_factory=dict)
    comments: Mapping[uuid.UUID, int] = field(default_factory=dict)
    links: Mapping[uuid.UUID, tuple[CardLink, ...]] = field(default_factory=dict)
    people: Mapping[uuid.UUID, PersonRef] = field(default_factory=dict)
    resolved: Mapping[tuple[str, uuid.UUID], Resolved] = field(default_factory=dict)
    events: Mapping[uuid.UUID, TodoCardEvent] = field(default_factory=dict)
    series: Mapping[uuid.UUID, str] = field(default_factory=dict)


def _uuid_of(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None


def _ref_of(payload: dict[str, Any]) -> tuple[str, uuid.UUID] | None:
    kind = payload.get("linkKind")
    target = _uuid_of(payload.get("targetId"))
    if kind in LINK_KINDS and target is not None:
        return (kind, target)
    return None


def _excerpt(body: str) -> str:
    flat = " ".join(body.split())
    return flat if len(flat) <= EXCERPT_LENGTH else flat[: EXCERPT_LENGTH - 1] + "…"


def _person(persons: Mapping[uuid.UUID, PersonRef], principal_id: uuid.UUID | None) -> PersonRef:
    if principal_id is None:
        return DELETED_PERSON
    return persons.get(principal_id, DELETED_PERSON)


def _not_archived(board: TodoBoard) -> None:
    """Raise 409 ``board_archived`` for an archived board (read-only, spec 001068)."""
    if board.archived_at is not None:
        raise ConflictError("The board is archived.", code="board_archived")


def _board_order(board: TodoBoard) -> tuple[int, str, str]:
    """Sort key of the boards: personal, gremium, free, then team, each by name."""
    return (_KIND_ORDER.get(board.kind, 4), board.name.casefold(), str(board.id))


def _in_column_order(cards: Iterable[TodoCard], columns: Sequence[TodoColumn]) -> list[TodoCard]:
    """Order the cards by the position of their column, then by rank.

    A card of a column that is not in ``columns`` goes last.
    """
    position = {c.id: index for index, c in enumerate(columns)}
    return sorted(cards, key=lambda c: (position.get(c.column_id, len(columns)), c.rank, str(c.id)))


def _new_entry(board_id: uuid.UUID, kind: str, target_id: uuid.UUID, role: str) -> TodoBoardEntry:
    """A new entry row of a team (``kind`` team) or of a person."""
    return TodoBoardEntry(
        id=uuid.uuid4(),
        board_id=board_id,
        team_id=target_id if kind == "team" else None,
        principal_id=target_id if kind == "person" else None,
        role=role,
    )
