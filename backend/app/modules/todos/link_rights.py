"""The change right of each link kind (spec 001404).

A person adds or removes a link when the person reads both ends and may change at least
one of them. The change right of an end is the right that changes the element itself:

* application — the edit right of the Antrag (``require_app_edit``);
* meeting, agenda_item — ``session.manage`` in the Gremium of the meeting;
* vote — ``vote.manage`` or ``session.manage`` in the Gremium of the vote (its meeting,
  else its eligible group);
* appointment — the creator of the Termin or ``calendar.manage`` (``rules.can_edit``);
* gremium — ``admin.gremien``;
* invoice, expense — ``budget.book``;
* budget — ``budget.structure``;
* ticket — ``ticket.manage``;
* todo — the write right on the board of the card (``BoardAccess.can_write``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.access import require_app_edit
from app.modules.auth.policy import has_gremium_permission
from app.modules.auth.principal import Principal
from app.modules.calendar import rules as calendar_rules
from app.modules.calendar.appointments import AppointmentService
from app.modules.calendar.models import Appointment
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.tickets.access import TICKET_MANAGE
from app.modules.todos.access import BoardAccess
from app.modules.todos.models import TodoBoard, TodoCard
from app.modules.voting.models import Vote
from app.shared.errors import ForbiddenError, NotFoundError, UnauthorizedError

#: The global right that changes an element of the kind.
GLOBAL_RIGHT: dict[str, str] = {
    "gremium": "admin.gremien",
    "invoice": "budget.book",
    "expense": "budget.book",
    "budget": "budget.structure",
    "ticket": TICKET_MANAGE,
}
#: The gremium rights that change a vote.
VOTE_RIGHTS: tuple[str, ...] = ("vote.manage", "session.manage")


@dataclass(frozen=True, slots=True)
class LinkRights:
    """Tell for one principal whether it changes an element of a link kind.

    Attributes:
        session: The database session.
        access: The board access check of the cards.
    """

    session: AsyncSession
    access: BoardAccess

    async def can_change(self, kind: str, target_id: uuid.UUID, principal: Principal) -> bool:
        """Tell if the principal changes the element ``(kind, target_id)``."""
        if kind in GLOBAL_RIGHT:
            return principal.has(GLOBAL_RIGHT[kind])
        match kind:
            case "application":
                return await self._application(target_id, principal)
            case "meeting":
                return await self._meeting(target_id, principal)
            case "agenda_item":
                item = await self.session.get(MeetingAgendaItem, target_id)
                return item is not None and await self._meeting(item.meeting_id, principal)
            case "vote":
                return await self._vote(target_id, principal)
            case "appointment":
                return await self._appointment(target_id, principal)
            case "todo":
                return await self._card(target_id, principal)
            case _:
                return False

    async def _application(self, application_id: uuid.UUID, principal: Principal) -> bool:
        try:
            await require_app_edit(application_id, self.session, principal, None)
        except (ForbiddenError, NotFoundError, UnauthorizedError):
            return False
        return True

    async def _in_gremium(
        self, gremium_id: uuid.UUID | None, principal: Principal, *rights: str
    ) -> bool:
        if gremium_id is None:
            return False
        return any(
            [await has_gremium_permission(self.session, principal, r, gremium_id) for r in rights]
        )

    async def _meeting(self, meeting_id: uuid.UUID, principal: Principal) -> bool:
        meeting = await self.session.get(Meeting, meeting_id)
        return meeting is not None and await self._in_gremium(
            meeting.gremium_id, principal, "session.manage"
        )

    async def _vote(self, vote_id: uuid.UUID, principal: Principal) -> bool:
        vote = await self.session.get(Vote, vote_id)
        if vote is None:
            return False
        meeting = await self.session.get(Meeting, vote.meeting_id) if vote.meeting_id else None
        gremium_id = meeting.gremium_id if meeting is not None else _uuid(vote.eligible_group)
        return await self._in_gremium(gremium_id, principal, *VOTE_RIGHTS)

    async def _appointment(self, appointment_id: uuid.UUID, principal: Principal) -> bool:
        row = await self.session.get(Appointment, appointment_id)
        if row is None:
            return False
        viewer = await AppointmentService(self.session).viewer(principal)
        return calendar_rules.can_edit(viewer, row.creator_id)

    async def _card(self, card_id: uuid.UUID, principal: Principal) -> bool:
        card = await self.session.get(TodoCard, card_id)
        board = await self.session.get(TodoBoard, card.board_id) if card is not None else None
        return board is not None and await self.access.can_write(board, principal)


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None
