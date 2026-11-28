"""Schemas of the activity page (specs 001270-001277).

An entry is flat and presentational, like a search hit: the page shows one row per entry
and does not need to know the shape of an Antrag, a card, a ticket or a meeting. The
``change`` key says what happened; the client turns it into a text in the language of the
reader.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.shared.schemas import FrozenCamelModel

#: The kinds of item of the page, in the order of the filter chips (spec 001274).
ItemKind = Literal["application", "todo", "ticket", "meeting"]

#: The kinds of actor. ``person`` has a name (or none: "Ohne Namen"), ``system`` is the
#: platform itself, ``applicant`` is the applicant without an account, and ``committee``
#: stands for a member in the applicant view, which names the Gremium, never a person.
ActorKind = Literal["person", "system", "applicant", "committee"]

#: What happened. The client holds one text per key.
ChangeKind = Literal[
    "application.status",
    "application.edited",
    "comment",
    "todo.created",
    "todo.moved",
    "todo.assigned",
    "todo.unassigned",
    "todo.due",
    "todo.linked",
    "todo.unlinked",
    "todo.checklist",
    "todo.renamed",
    "todo.archived",
    "todo.restored",
    "ticket.created",
    "ticket.status",
    "ticket.assignee",
    "ticket.kind",
    "ticket.todo_done",
    "meeting.status",
    "meeting.updated",
    "protocol.finalized",
    "protocol.approved",
    "protocol.reopened",
    "protocol.sent",
]


class ActivityActor(FrozenCamelModel, frozen=True):
    """Who made the change."""

    kind: ActorKind
    #: The display name of a ``person``. ``None`` reads as "Ohne Namen" (spec 000159).
    name: str | None = None


class ActivityEntry(FrozenCamelModel, frozen=True):
    """One row of the page (spec 001277)."""

    #: Unique over all sources, and the second part of the cursor.
    id: str
    at: datetime
    item_kind: ItemKind = Field(alias="itemKind")
    item_id: str = Field(alias="itemId")
    item_title: str | None = Field(alias="itemTitle")
    #: The detail page of the item, app-relative.
    url: str
    change: ChangeKind
    #: A short text of the change: the first line of a comment, a state, a column name.
    detail: str | None = None
    #: A status key that the client translates (ticket and meeting status).
    status: str | None = None
    actor: ActivityActor
    #: The actor is the reader (spec 001273).
    own: bool = False
    #: The event is after the last visit (spec 001275).
    is_new: bool = Field(alias="isNew", default=False)


class ActivityPage(FrozenCamelModel, frozen=True):
    """One step of the page, newest first (spec 001276)."""

    entries: list[ActivityEntry]
    #: The cursor of the next step, or ``None`` at the end.
    next_cursor: str | None = Field(alias="nextCursor", default=None)
    #: The last visit before this read, or ``None`` for the first visit.
    seen_at: datetime | None = Field(alias="seenAt", default=None)
    #: The time of the server at the read. The client sends it back as the new mark.
    read_at: datetime = Field(alias="readAt")


class ActivityStatus(FrozenCamelModel, frozen=True):
    """Whether an event of another person waits after the last visit."""

    has_new: bool = Field(alias="hasNew")


class NavigationStatus(FrozenCamelModel, frozen=True):
    """The four marks of the navigation (spec 002001).

    ``tasks`` counts the applications to act on and the open to-dos of the caller,
    ``tickets`` the new tickets (``None`` without ``ticket.manage`` or with tickets off),
    ``live`` whether a readable meeting runs, ``activity`` whether an event waits.
    """

    tasks: int
    tickets: int | None
    live: bool
    activity: bool


class ActivitySeen(FrozenCamelModel, frozen=True):
    """The body of ``POST /activity/seen``: the time up to which the reader has seen."""

    at: datetime
