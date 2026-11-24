"""Shared base of the ticket service ops classes: constructor, lookups, events, sender checks."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from pydantic import JsonValue
from sqlalchemy import ColumnElement, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.files.service import FilesService
from app.modules.tickets.access import AreaScope, works_in
from app.modules.tickets.models import (
    CLOSED_STATUSES,
    Ticket,
    TicketEvent,
    TicketNote,
    TicketSenderBlock,
)
from app.modules.tickets.numbers import draw_number, format_number
from app.modules.tickets.schemas import TicketListItem, TicketNoteOut
from app.modules.tickets.service.common import (
    NUMBER_DRAWS,
    BlockTarget,
    TicketTodoHooks,
    _Account,
    _area_of_id,
    _now,
    normalize_email,
    principal_id_of,
)
from app.modules.tickets.service.rows import _note_row, _person, _reporter
from app.modules.tickets.webhook_fields import emit_ticket_message, emit_ticket_status
from app.shared.errors import ForbiddenError, NotFoundError
from app.shared.mentions import mention_ids


class TicketServiceBase:
    """Constructor and helpers that every ops class of ``TicketService`` uses."""

    #: The mentions that the last ``add_note`` or ``edit_note`` added, for the mail.
    added_mentions: Sequence[uuid.UUID] = ()

    def __init__(
        self,
        session: AsyncSession,
        *,
        files: FilesService | None = None,
        todos: TicketTodoHooks | None = None,
    ) -> None:
        """Bind the service to a session and its file and to-do helpers."""
        self.session = session
        self.files = files or FilesService(session)
        self.todos = todos

    async def free_number(self, draws: int = NUMBER_DRAWS) -> str:
        """Draw a number that no ticket has.

        A draw that meets a used number is drawn again, because the number is the
        reference of a ticket in mails and must point to one ticket.

        Raises:
            RuntimeError: Every draw met a used number.
        """
        candidate = draw_number()
        taken = await self.session.scalar(select(Ticket.id).where(Ticket.number == candidate))
        if taken is not None and draws <= 1:
            raise RuntimeError("no free ticket number")
        return candidate if taken is None else await self.free_number(draws - 1)

    async def reporter_address(self, ticket: Ticket) -> str | None:
        """Return the address of the reporter: the account e-mail or the given e-mail."""
        if ticket.reporter_principal_id is None:
            return ticket.reporter_email
        return await self.session.scalar(
            select(PrincipalRow.email).where(PrincipalRow.id == ticket.reporter_principal_id)
        )

    async def sender_answered(self, ticket: Ticket, *, body: str) -> None:
        """Set ``in_progress`` after a message of the sender, without a commit.

        Only a ticket with the status ``waiting``, ``done`` or ``rejected`` changes. The
        status event has no person, so the team sees that the answer is there. The
        message is the webhook event ``ticket.message``, and the status change is
        ``ticket.status`` (§F/integrations/webhooks/002750, 002751).
        """
        old = ticket.status
        if old == "waiting" or old in CLOSED_STATUSES:
            self._set_status(ticket, "in_progress", None, None)
        ticket.updated_at = _now()
        await emit_ticket_message(self.session, ticket, body=body)
        await emit_ticket_status(self.session, ticket, old=old, new=ticket.status)

    def add_event(self, ticket: Ticket, kind: str, payload: dict[str, JsonValue]) -> None:
        """Add an event of the system to a ticket, without a commit."""
        self._event(ticket, kind, None, payload)

    @staticmethod
    def block_target(ticket: Ticket) -> BlockTarget | None:
        """Return what a block of this ticket's sender targets.

        An anonymized ticket has no sender any more and gives None.
        """
        match ticket.anonymized_at, ticket.reporter_principal_id, ticket.reporter_email:
            case (None, account, _) if account is not None:
                return ("principal", account)
            case (None, None, address) if address:
                return ("email", normalize_email(address))
            case _:
                return None

    @staticmethod
    def _account_condition(reporter_id: uuid.UUID) -> ColumnElement[bool]:
        """Match a block of the account or of the account e-mail (case-insensitive)."""
        account_email = (
            select(func.lower(cast(PrincipalRow.email, String)))
            .where(PrincipalRow.id == reporter_id)
            .scalar_subquery()
        )
        return or_(
            TicketSenderBlock.principal_id == reporter_id,
            TicketSenderBlock.email == account_email,
        )

    @staticmethod
    def _email_condition(address: str) -> ColumnElement[bool]:
        """Match a block of the normalized e-mail or of an account with that e-mail."""
        return or_(
            TicketSenderBlock.email == address,
            TicketSenderBlock.principal_id.in_(
                select(PrincipalRow.id).where(PrincipalRow.email == address)
            ),
        )

    @classmethod
    def _target_condition(cls, target: BlockTarget) -> ColumnElement[bool]:
        """Return the condition of every block that holds back the sender of a target."""
        if target[0] == "principal":
            return cls._account_condition(target[1])
        return cls._email_condition(target[1])

    async def _sender_blocked(self, ticket: Ticket) -> bool:
        target = self.block_target(ticket)
        if target is None:
            return False
        found = await self.session.scalar(
            select(TicketSenderBlock.id).where(self._target_condition(target)).limit(1)
        )
        return found is not None

    def _set_status(
        self,
        ticket: Ticket,
        status: str,
        duplicate: Ticket | None,
        actor: uuid.UUID | None,
    ) -> None:
        marker: dict[str, JsonValue] = (
            {"duplicateOf": format_number(duplicate.number)} if duplicate is not None else {}
        )
        self._event(ticket, "status", actor, {"from": ticket.status, "to": status, **marker})
        if status not in CLOSED_STATUSES:
            ticket.closed_at = None
        elif ticket.status not in CLOSED_STATUSES:
            ticket.closed_at = _now()
        ticket.duplicate_of_id = duplicate.id if duplicate is not None else None
        ticket.status = status

    def _event(
        self,
        ticket: Ticket,
        kind: str,
        actor: uuid.UUID | None,
        payload: dict[str, JsonValue],
    ) -> None:
        """Add an event of a ticket, stamped with the clock of the process.

        It is not now() of the transaction, because one change can write two events, and
        the timeline orders them by this time.
        """
        self.session.add(
            TicketEvent(
                ticket_id=ticket.id,
                actor_id=actor,
                kind=kind,
                payload=payload,
                created_at=_now(),
            )
        )

    async def _own_note(
        self, ticket_id: uuid.UUID, note_id: uuid.UUID, principal: Principal
    ) -> tuple[TicketNote, uuid.UUID]:
        note = await self.session.get(TicketNote, note_id)
        if note is None or note.ticket_id != ticket_id or note.deleted_at is not None:
            raise NotFoundError(f"note {note_id} not found")
        me = await principal_id_of(self.session, principal.sub)
        if me is None or note.author_id != me:
            raise ForbiddenError("Only the author edits a note.", code="not_note_author")
        return note, me

    async def _note_out(
        self, note: TicketNote, me: uuid.UUID, ticket: Ticket, *, for_reporter: bool = False
    ) -> TicketNoteOut:
        mentioned = () if for_reporter else mention_ids(note.mentions)
        accounts = await self._load_accounts({note.author_id, *mentioned})
        files = await self.files.message_attachments("ticket_note", [note.id])
        return _note_row(
            note, ticket, accounts, me, files.get(note.id, []), for_reporter=for_reporter
        )

    async def _get(
        self, ticket_id: uuid.UUID, *, lock: bool = False, areas: AreaScope = None
    ) -> Ticket:
        """Return the ticket when ``areas`` holds its Bereich; None holds every Bereich.

        Raises:
            NotFoundError: No ticket has this id, or its Bereich is outside ``areas``
                (HTTP 404).
        """
        ticket = await (
            self.session.get(Ticket, ticket_id, with_for_update=True, populate_existing=True)
            if lock
            else self.session.get(Ticket, ticket_id)
        )
        if ticket is None or not works_in(areas, _area_of_id(ticket)):
            raise NotFoundError(f"ticket {ticket_id} not found")
        return ticket

    async def _require_account(self, principal: Principal) -> uuid.UUID:
        me = await principal_id_of(self.session, principal.sub)
        if me is None:
            raise NotFoundError("account not found")
        return me

    async def _accounts(
        self, tickets: Sequence[Ticket], *, extra: Iterable[uuid.UUID | None] = ()
    ) -> dict[uuid.UUID, _Account]:
        return await self._load_accounts(
            {
                *extra,
                *(pid for t in tickets for pid in (t.reporter_principal_id, t.assignee_id)),
            }
        )

    async def _load_accounts(self, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, _Account]:
        wanted = {pid for pid in ids if pid is not None}
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email).where(
                    PrincipalRow.id.in_(wanted)
                )
            )
        ).all()
        return {pid: _Account(name, email) for pid, name, email in rows}

    def _list_item(self, ticket: Ticket, accounts: dict[uuid.UUID, _Account]) -> TicketListItem:
        return TicketListItem(
            id=ticket.id,
            number=format_number(ticket.number),
            area_id=_area_of_id(ticket),
            kind=ticket.kind,  # pyright: ignore[reportArgumentType]
            category_id=ticket.category_id,
            title=ticket.title,
            status=ticket.status,  # pyright: ignore[reportArgumentType]
            source=ticket.source or "help",  # pyright: ignore[reportArgumentType]
            reporter=_reporter(ticket, accounts),
            assignee=(
                _person(accounts, ticket.assignee_id) if ticket.assignee_id is not None else None
            ),
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
        )
