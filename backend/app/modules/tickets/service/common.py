"""Shared constants, problem codes, types and small helpers of the ticket service."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import SQLCoreOperations

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.tickets.models import PLATFORM_AREA_ID, Ticket

#: The draws of a free number before the service gives up. One draw meets a used number
#: with a chance of the ticket count divided by 31 to the power of 8.
NUMBER_DRAWS = 8


#: The route of an application or a meeting in ``context.route``.
_ROUTE_RE = re.compile(
    r"^/(applications|meetings)/"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"(?:[/?#].*)?$"
)


AssigneeFilter = uuid.UUID | Literal["me", "none"]


logger = logging.getLogger("app.tickets")


#: The problem code of a block on a ticket without a reporter (anonymized).
SENDER_UNKNOWN = "ticket_sender_unknown"


#: The problem code of a block of the own account or address.
SENDER_IS_SELF = "sender_is_self"


#: The problem code of a note with files on an anonymized ticket.
TICKET_ANONYMIZED = "ticket_anonymized"


#: The problem code of a message of a reporter that a sender block holds back.
SENDER_BLOCKED = "sender_blocked"


#: The problem code of a report to a Bereich other than ``Plattform`` without a session.
AREA_NEEDS_SESSION = "ticket_area_needs_session"


#: The problem code of a report to a Bereich without the switch ``in_app``.
AREA_NOT_REACHABLE = "ticket_area_not_reachable"


#: The problem code of a ticket by hand for an address in a Bereich without a Postfach.
AREA_WITHOUT_MAILBOX = "ticket_area_without_mailbox"


#: The problem code of a ticket by hand that names no person, two, or an unknown account.
REPORTER_INVALID = "ticket_reporter_invalid"


#: The problem code of a download of a mail source without a clean scan result.
MAIL_SOURCE_CLOSED = "mail_source_closed"


#: What a block targets: an account id or a normalized e-mail address.
BlockTarget = tuple[Literal["principal"], uuid.UUID] | tuple[Literal["email"], str]


#: A text column that the search ``q`` reads.
_Text = SQLCoreOperations[str | None]


def normalize_email(value: str) -> str:
    """Normalize an address for ``ticket_sender_block.email``: strip and lowercase."""
    return value.strip().lower()


@dataclass(frozen=True, slots=True)
class SwallowedReport:
    """The answer to a report of a blocked sender: a number, and no ticket.

    ``id`` is always None, so the router sends no mail.
    """

    number: str
    id: None = None


def _now() -> datetime:
    return datetime.now(UTC)


class TicketTodoHooks(Protocol):
    """The to-do coupling of a ticket, provided by the todos module."""

    async def open_count(self, ticket_id: uuid.UUID, principal: Principal) -> int:
        """Count the open linked cards that the principal can read."""
        ...

    async def complete(self, ticket_id: uuid.UUID, principal: Principal) -> None:
        """Move the open linked cards that the principal can write into done."""
        ...

    async def readable_cards(
        self, card_ids: Iterable[uuid.UUID], principal: Principal
    ) -> set[uuid.UUID]:
        """Return the cards whose board the principal reads (``todo_done`` titles)."""
        ...


@dataclass(frozen=True, slots=True)
class _Account:
    display_name: str | None
    email: str | None


async def principal_id_of(session: AsyncSession, sub: str) -> uuid.UUID | None:
    """Return the row id of the account with this ``sub``."""
    return await session.scalar(select(PrincipalRow.id).where(PrincipalRow.sub == sub))


def _area_of_id(ticket: Ticket) -> uuid.UUID:
    """Return the Bereich of a ticket; a row before its first flush is of ``Plattform``."""
    return ticket.area_id or PLATFORM_AREA_ID


def _area_of(ticket: Ticket) -> frozenset[uuid.UUID]:
    """Return the Bereich of a ticket as the scope of ``area_workers``."""
    return frozenset({_area_of_id(ticket)})


def _id_or_none(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _uuid_or_none(raw: JsonValue) -> uuid.UUID | None:
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None
