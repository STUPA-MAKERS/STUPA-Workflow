"""The ``WHERE`` parts of the ticket lists: Bereich, status and kind, assignee, search."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, or_

from app.modules.tickets.access import AreaScope
from app.modules.tickets.models import Ticket
from app.modules.tickets.numbers import number_part, parse_number
from app.modules.tickets.service.common import AssigneeFilter, _Text
from app.shared.search import escape_like


def _area_filter(
    areas: AreaScope, area_ids: Sequence[uuid.UUID]
) -> tuple[ColumnElement[bool], ...]:
    """Return the conditions of the scope of the caller and of the Bereich filter."""
    return (
        *((Ticket.area_id.in_(areas),) if areas is not None else ()),
        *((Ticket.area_id.in_(list(area_ids)),) if area_ids else ()),
    )


def _status_kind_filter(
    statuses: Sequence[str], kinds: Sequence[str]
) -> tuple[ColumnElement[bool], ...]:
    """Return the conditions of the ``status`` and ``kind`` filters; an empty one adds none."""
    return (
        *((Ticket.status.in_(list(statuses)),) if statuses else ()),
        *((Ticket.kind.in_(list(kinds)),) if kinds else ()),
    )


def _assignee_filter(
    assignee: AssigneeFilter | None, me: uuid.UUID | None
) -> tuple[ColumnElement[bool], ...]:
    """Return the condition of the ``assignee`` filter: ``none``, ``me``, an id or nothing."""
    match assignee:
        case None:
            return ()
        case "none":
            return (Ticket.assignee_id.is_(None),)
        case "me":
            return (Ticket.assignee_id == me,)
        case _:
            return (Ticket.assignee_id == assignee,)


def _search_filter(term: str, texts: Sequence[_Text]) -> tuple[ColumnElement[bool], ...]:
    """Return the condition of ``q``: a text column contains it, or it names the number.

    A full number matches its ticket. A part of a number matches every ticket whose
    number contains it, so a person finds a ticket while typing. A blank term adds no
    condition.
    """
    pattern = f"%{escape_like(term)}%"
    full = parse_number(term)
    part = number_part(term)
    by_number = (
        (Ticket.number == full,)
        if full is not None
        else ((Ticket.number.contains(part, autoescape=True),) if part is not None else ())
    )
    matches = (*(text.ilike(pattern, escape="\\") for text in texts), *by_number)
    return (or_(*matches),) if term else ()
