"""The view of the reporter account on its own tickets, and its messages."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.files.drafts import bind_drafts, check_message_drafts
from app.modules.tickets.models import CLOSED_STATUSES, REOPEN_DAYS, Ticket, TicketEvent, TicketNote
from app.modules.tickets.numbers import format_number
from app.modules.tickets.schemas import (
    ReporterNoteCreate,
    ReporterTicketDetail,
    ReporterTicketEvent,
    ReporterTicketItem,
    TicketAttachment,
    TicketNoteOut,
)
from app.modules.tickets.service.common import SENDER_BLOCKED, _area_of_id, _now, principal_id_of
from app.modules.tickets.service.filters import _search_filter, _status_kind_filter
from app.modules.tickets.service.notes import NoteOps
from app.modules.tickets.service.rows import _note_row
from app.modules.tickets.webhook_fields import emit_ticket_created
from app.shared.errors import ForbiddenError, NotFoundError
from app.shared.paging import Page


def reply_is_late(ticket: Ticket) -> bool:
    """Tell if a message of the sender comes more than ``REOPEN_DAYS`` days after the close."""
    return _reply_is_late(ticket)


def _reply_is_late(ticket: Ticket) -> bool:
    """Tell if a message of the sender comes more than ``REOPEN_DAYS`` days after the close."""
    return (
        ticket.status in CLOSED_STATUSES
        and ticket.closed_at is not None
        and _now() - ticket.closed_at > timedelta(days=REOPEN_DAYS)
    )


def _reporter_item(ticket: Ticket) -> ReporterTicketItem:
    return ReporterTicketItem(
        id=ticket.id,
        number=format_number(ticket.number),
        kind=ticket.kind,  # pyright: ignore[reportArgumentType]
        title=ticket.title,
        status=ticket.status,  # pyright: ignore[reportArgumentType]
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


async def reporter_reads_file(
    session: AsyncSession, principal: Principal, *, kind: str, owner_id: uuid.UUID
) -> bool:
    """Tell if the reporter account reads a file of its own ticket.

    ``kind`` ``ticket`` is a file of the report; ``ticket_note`` a file of a live
    ``public`` note. An anonymized ticket has no reporter.
    """
    me = await principal_id_of(session, principal.sub)
    if me is None:
        return False
    stmt = _file_owner_query(
        select(Ticket.id).where(Ticket.reporter_principal_id == me, Ticket.anonymized_at.is_(None)),
        kind=kind,
        owner_id=owner_id,
    )
    return stmt is not None and (await session.scalar(stmt.limit(1))) is not None


def _file_owner_query(
    own_tickets: Select[uuid.UUID], *, kind: str, owner_id: uuid.UUID
) -> Select[uuid.UUID] | None:
    """Narrow the own tickets to the owner of a file; another ``kind`` gives None."""
    match kind:
        case "ticket":
            return own_tickets.where(Ticket.id == owner_id)
        case "ticket_note":
            return own_tickets.join(TicketNote, TicketNote.ticket_id == Ticket.id).where(
                TicketNote.id == owner_id,
                TicketNote.deleted_at.is_(None),
                TicketNote.visibility == "public",
            )
        case _:
            return None


async def has_reported_tickets(session: AsyncSession, sub: str) -> bool:
    """Tell if the account of ``sub`` reported a ticket that is not anonymized."""
    me = await principal_id_of(session, sub)
    if me is None:
        return False
    found = await session.scalar(
        select(Ticket.id)
        .where(Ticket.reporter_principal_id == me, Ticket.anonymized_at.is_(None))
        .limit(1)
    )
    return found is not None


class ReporterOps(NoteOps):
    """The ``reporter_*`` reads and writes of the reporter account."""

    async def _reporter_ticket(
        self, ticket_id: uuid.UUID, principal: Principal, *, lock: bool = False
    ) -> tuple[Ticket, uuid.UUID]:
        """Return the ticket and the account when the caller reported it.

        Raises:
            NotFoundError: No ticket has this id, the caller has no account row, did
                not report it, or the ticket is anonymized (HTTP 404).
        """
        missing = NotFoundError(f"ticket {ticket_id} not found")
        me = await principal_id_of(self.session, principal.sub)
        if me is None:
            raise missing
        try:
            ticket = await self._get(ticket_id, lock=lock)
        except NotFoundError:
            raise missing from None
        if ticket.anonymized_at is not None or ticket.reporter_principal_id != me:
            raise missing
        return ticket, me

    async def reporter_list(
        self,
        me: uuid.UUID,
        *,
        statuses: Sequence[str] = (),
        kinds: Sequence[str] = (),
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[ReporterTicketItem]:
        """List the tickets that the account reported, newest first.

        ``q`` matches the title, the body and the number. Anonymized tickets have no
        reporter any more and never show. The body of a ticket that the team wrote by
        hand is the note of the team, so ``q`` does not read it.
        """
        own_body = case((Ticket.source == "team", ""), else_=Ticket.body)
        conds = (
            Ticket.reporter_principal_id == me,
            Ticket.anonymized_at.is_(None),
            *_status_kind_filter(statuses, kinds),
            *_search_filter((q or "").strip(), (Ticket.title, own_body)),
        )
        total = await self.session.scalar(select(func.count(Ticket.id)).where(*conds))
        rows = list(
            (
                await self.session.scalars(
                    select(Ticket)
                    .where(*conds)
                    .order_by(Ticket.created_at.desc(), Ticket.number.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        return Page[ReporterTicketItem](
            items=[_reporter_item(t) for t in rows],
            total=int(total or 0),
            limit=limit,
            offset=offset,
        )

    async def reporter_detail(
        self, ticket_id: uuid.UUID, principal: Principal
    ) -> ReporterTicketDetail:
        """Return the own ticket: the report, its files, the public notes and the status changes.

        Raises:
            NotFoundError: Not a ticket of the caller (HTTP 404).
        """
        ticket, me = await self._reporter_ticket(ticket_id, principal)
        notes = list(
            (
                await self.session.scalars(
                    select(TicketNote)
                    .where(
                        TicketNote.ticket_id == ticket.id,
                        TicketNote.deleted_at.is_(None),
                        TicketNote.visibility == "public",
                    )
                    .order_by(TicketNote.created_at, TicketNote.id)
                )
            ).all()
        )
        events = list(
            (
                await self.session.scalars(
                    select(TicketEvent)
                    .where(TicketEvent.ticket_id == ticket.id, TicketEvent.kind == "status")
                    .order_by(TicketEvent.created_at, TicketEvent.id)
                )
            ).all()
        )
        accounts = await self._load_accounts({n.author_id for n in notes})
        files = await self.files.message_attachments("ticket_note", [n.id for n in notes])
        return ReporterTicketDetail(
            **_reporter_item(ticket).model_dump(),
            body="" if ticket.source == "team" else ticket.body,
            attachments=tuple(
                TicketAttachment.of(a) for a in await self.files.list_for_ticket(ticket.id)
            ),
            notes=[
                _note_row(n, ticket, accounts, me, files.get(n.id, []), for_reporter=True)
                for n in notes
            ],
            events=tuple(
                ReporterTicketEvent(
                    id=e.id,
                    kind="status",
                    at=e.created_at,
                    payload={k: v for k, v in (e.payload or {}).items() if k in ("from", "to")},
                )
                for e in events
            ),
            closed_at=ticket.closed_at,
            can_reply=not await self._sender_blocked(ticket),
            reply_opens_new=_reply_is_late(ticket),
        )

    async def reporter_add_note(
        self,
        ticket_id: uuid.UUID,
        payload: ReporterNoteCreate,
        principal: Principal,
        *,
        pepper: str,
    ) -> TicketNoteOut:
        """Add a message of the reporter. It is ``public`` and binds its files.

        A message on a ticket with the status ``waiting``, ``done`` or ``rejected``
        sets ``in_progress`` and writes a status event without a person, so the team
        sees that the answer is there. The router sends a message on a ticket that is
        closed for more than ``REOPEN_DAYS`` days to ``reporter_follow_up``.

        Raises:
            NotFoundError: Not a ticket of the caller (HTTP 404).
            ForbiddenError: A sender block holds back the reporter (HTTP 403,
                ``sender_blocked``).
            ValidationProblem: Files without a draft token, or a draft that is missing,
                expired, foreign or infected (HTTP 422).

        The ticket row is always locked, because an anonymization between the check and
        the commit would miss the new note and leave the reporter on an anonymized
        ticket.
        """
        ticket, me = await self._reporter_ticket(ticket_id, principal, lock=True)
        if await self._sender_blocked(ticket):
            raise ForbiddenError("The sender is blocked.", code=SENDER_BLOCKED)
        await self.sender_answered(ticket, body=payload.body)
        return await self._insert_note(
            ticket,
            me,
            body=payload.body,
            visibility="public",
            attachment_ids=payload.attachment_ids,
            draft_token=payload.draft_token,
            pepper=pepper,
            for_reporter=True,
        )

    async def reporter_follow_up(
        self,
        ticket_id: uuid.UUID,
        payload: ReporterNoteCreate,
        principal: Principal,
        *,
        pepper: str,
    ) -> Ticket | None:
        """Turn a late message of the reporter into a new ticket, without a commit.

        The result is None while the ticket is open or its close is at most
        ``REOPEN_DAYS`` days old; the message then is a note (``reporter_add_note``).
        Else the message becomes a new ticket in the same Bereich with the same title,
        kind and Kategorie, and ``follow_up_of_id`` names the old ticket.

        Raises:
            NotFoundError: Not a ticket of the caller (HTTP 404).
            ForbiddenError: A sender block holds back the reporter (HTTP 403,
                ``sender_blocked``).
            ValidationProblem: Files without a draft token, or a draft that is missing,
                expired, foreign or infected (HTTP 422).
        """
        old, me = await self._reporter_ticket(ticket_id, principal, lock=True)
        if not _reply_is_late(old):
            return None
        if await self._sender_blocked(old):
            raise ForbiddenError("The sender is blocked.", code=SENDER_BLOCKED)
        token = await check_message_drafts(
            self.session,
            attachment_ids=payload.attachment_ids,
            token=payload.draft_token,
            pepper=pepper,
        )
        language = (old.context or {}).get("language")
        ticket = Ticket(
            id=uuid.uuid4(),
            number=await self.free_number(),
            area_id=_area_of_id(old),
            kind=old.kind,
            category_id=old.category_id,
            source="help",
            title=old.title,
            body=payload.body,
            status="new",
            reporter_principal_id=me,
            follow_up_of_id=old.id,
            context={"language": language} if language else {},
        )
        self.session.add(ticket)
        await self.session.flush()
        if token is not None:
            await bind_drafts(
                self.session,
                attachment_ids=payload.attachment_ids,
                token=token,
                pepper=pepper,
                ticket_id=ticket.id,
            )
        reporter = await self.reporter_address(ticket)
        await emit_ticket_created(self.session, ticket, reporter_email=reporter)
        self._event(
            ticket,
            "created",
            me,
            {"confirmationSent": reporter is not None, "followUpOf": format_number(old.number)},
        )
        await self.session.flush()
        return ticket

    async def reporter_edit_note(
        self, ticket_id: uuid.UUID, note_id: uuid.UUID, body: str, principal: Principal
    ) -> TicketNoteOut:
        """Change the text of an own message on an own ticket.

        Raises:
            NotFoundError: Not a ticket of the caller, or no live public note (HTTP 404).
            ForbiddenError: The note has another author (HTTP 403, ``not_note_author``), or
                a sender block holds back the reporter (HTTP 403, ``sender_blocked``).
        """
        ticket, me = await self._reporter_ticket(ticket_id, principal, lock=True)
        note = await self._reporter_note(ticket, note_id, principal)
        if await self._sender_blocked(ticket):
            raise ForbiddenError("The sender is blocked.", code=SENDER_BLOCKED)
        note.body = body
        note.edited_at = _now()
        await self.session.commit()
        return await self._note_out(note, me, ticket, for_reporter=True)

    async def reporter_delete_note(
        self, ticket_id: uuid.UUID, note_id: uuid.UUID, principal: Principal
    ) -> None:
        """Delete an own message on an own ticket, with its files.

        A sender block does not stop a delete: the reporter keeps the right to remove
        the own data.

        Raises:
            NotFoundError: Not a ticket of the caller, or no live public note (HTTP 404).
            ForbiddenError: The note has another author (HTTP 403, ``not_note_author``).
        """
        ticket, _me = await self._reporter_ticket(ticket_id, principal)
        await self._reporter_note(ticket, note_id, principal)
        await self.delete_note(ticket.id, note_id, principal)

    async def _reporter_note(
        self, ticket: Ticket, note_id: uuid.UUID, principal: Principal
    ) -> TicketNote:
        """Return an own note of the reporter; an internal note answers like a missing one.

        Raises:
            NotFoundError: No live public note with this id on the ticket (HTTP 404).
            ForbiddenError: The note has another author (HTTP 403, ``not_note_author``).
        """
        visible = await self.session.get(TicketNote, note_id)
        if visible is None or visible.visibility != "public":
            raise NotFoundError(f"note {note_id} not found")
        note, _me = await self._own_note(ticket.id, note_id, principal)
        return note
