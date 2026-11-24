"""The reads of the team: list, counts, assignees and the detail view."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import aliased

from app.modules.applications.access import resolve_app_read
from app.modules.applications.models import Application
from app.modules.applications.service.service_base import _title_of
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.people import PersonRef, person_of
from app.modules.auth.principal import Principal
from app.modules.meetings.models import Meeting
from app.modules.tickets.access import AreaScope, area_workers
from app.modules.tickets.models import Ticket, TicketEvent, TicketNote
from app.modules.tickets.numbers import format_number
from app.modules.tickets.paperless import PAPERLESS_USE, paperless_of
from app.modules.tickets.schemas import (
    ContextTarget,
    TicketAttachment,
    TicketCounts,
    TicketDetail,
    TicketListItem,
    TicketRef,
)
from app.modules.tickets.service.common import (
    _ROUTE_RE,
    AssigneeFilter,
    _uuid_or_none,
    principal_id_of,
)
from app.modules.tickets.service.filters import (
    _area_filter,
    _assignee_filter,
    _search_filter,
    _status_kind_filter,
)
from app.modules.tickets.service.mail import MailOps
from app.modules.tickets.service.rows import _event_out, _mail_out, _note_row, _people_of
from app.shared.errors import ForbiddenError
from app.shared.paging import Page


class ReadOps(MailOps):
    """List, count and detail reads of the team, scoped to its Bereiche."""

    async def list(
        self,
        *,
        statuses: Sequence[str] = (),
        kinds: Sequence[str] = (),
        assignee: AssigneeFilter | None = None,
        me: uuid.UUID | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
        areas: AreaScope = None,
        area_ids: Sequence[uuid.UUID] = (),
    ) -> Page[TicketListItem]:
        """List the tickets, newest first, with the filters of ``GET /tickets``.

        ``q`` matches the title, the body, the number (``T-7K3QX9MD``, ``7k3q``),
        and the name and e-mail of the reporter. ``areas`` is the scope of the caller
        and ``area_ids`` the filter for the Bereich; a ticket shows only when both
        hold its Bereich.
        """
        reporter = aliased(PrincipalRow)
        term = (q or "").strip()
        texts = (
            Ticket.title,
            Ticket.body,
            cast(Ticket.reporter_email, String),
            reporter.display_name,
            cast(reporter.email, String),
        )
        conds = (
            *_area_filter(areas, area_ids),
            *_status_kind_filter(statuses, kinds),
            *_assignee_filter(assignee, me),
            *_search_filter(term, texts),
        )
        base = (
            select(Ticket)
            .outerjoin(reporter, reporter.id == Ticket.reporter_principal_id)
            .where(*conds)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(base.with_only_columns(Ticket.id).subquery())
        )
        rows = list(
            (
                await self.session.scalars(
                    base.order_by(Ticket.created_at.desc(), Ticket.number.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        accounts = await self._accounts(rows)
        return Page[TicketListItem](
            items=[self._list_item(t, accounts) for t in rows],
            total=int(total or 0),
            limit=limit,
            offset=offset,
        )

    async def counts(self, *, areas: AreaScope = None) -> TicketCounts:
        """Count the tickets of the Bereiche ``areas`` per status."""
        rows = (
            await self.session.execute(
                select(Ticket.status, func.count())
                .where(*_area_filter(areas, ()))
                .group_by(Ticket.status)
            )
        ).all()
        by_status = {status: int(n) for status, n in rows}
        return TicketCounts(
            new=by_status.get("new", 0),
            in_progress=by_status.get("in_progress", 0),
            waiting=by_status.get("waiting", 0),
            done=by_status.get("done", 0),
            rejected=by_status.get("rejected", 0),
        )

    async def assignees(self, areas: Collection[uuid.UUID] | None = None) -> list[PersonRef]:
        """List the persons with the work right in one of ``areas``, by name.

        None stands for every Bereich. For one Bereich the list holds its possible
        assignees.
        """
        people = [
            person_of(pid, name, email)
            for pid, name, email in await area_workers(self.session, areas)
        ]
        named = [p for p in people if p.principal_id is not None]
        return sorted(named, key=lambda p: ((p.display_name or "").casefold(), str(p.principal_id)))

    async def detail(
        self, ticket_id: uuid.UUID, principal: Principal, *, areas: AreaScope = None
    ) -> TicketDetail:
        """Return the whole ticket: notes, events, attachments and the links.

        Raises:
            NotFoundError: No ticket has this id in the Bereiche ``areas`` (HTTP 404).
        """
        ticket = await self._get(ticket_id, areas=areas)
        me = await principal_id_of(self.session, principal.sub)
        notes = list(
            (
                await self.session.scalars(
                    select(TicketNote)
                    .where(TicketNote.ticket_id == ticket.id, TicketNote.deleted_at.is_(None))
                    .order_by(TicketNote.created_at, TicketNote.id)
                )
            ).all()
        )
        events = list(
            (
                await self.session.scalars(
                    select(TicketEvent)
                    .where(TicketEvent.ticket_id == ticket.id)
                    .order_by(TicketEvent.created_at, TicketEvent.id)
                )
            ).all()
        )
        accounts = await self._accounts([ticket], extra=_people_of(notes, events))
        readable = await self._readable_cards(events, principal)
        duplicate = (
            await self.session.get(Ticket, ticket.duplicate_of_id)
            if ticket.duplicate_of_id is not None
            else None
        )
        followed = (
            await self.session.get(Ticket, ticket.follow_up_of_id)
            if ticket.follow_up_of_id is not None
            else None
        )
        item = self._list_item(ticket, accounts)
        files = await self.files.message_attachments("ticket_note", [n.id for n in notes])
        mails = await self._mails(ticket.id)
        senders = {m.note_id: m for m in mails if m.note_id is not None}
        return TicketDetail(
            **item.model_dump(),
            body=ticket.body,
            context=dict(ticket.context or {}),
            attachments=tuple(
                TicketAttachment.of(a) for a in await self.files.list_for_ticket(ticket.id)
            ),
            notes=tuple(
                _note_row(n, ticket, accounts, me, files.get(n.id, []), mail=senders.get(n.id))
                for n in notes
            ),
            events=tuple(_event_out(e, accounts, readable) for e in events),
            duplicate_of=(
                TicketRef(id=duplicate.id, number=format_number(duplicate.number))
                if duplicate is not None
                else None
            ),
            follow_up_of=(
                TicketRef(id=followed.id, number=format_number(followed.number))
                if followed is not None
                else None
            ),
            context_target=await self._context_target(ticket, principal),
            open_todo_count=(
                await self.todos.open_count(ticket.id, principal) if self.todos else 0
            ),
            closed_at=ticket.closed_at,
            anonymized_at=ticket.anonymized_at,
            sender_blocked=await self._sender_blocked(ticket),
            mails=tuple(_mail_out(m) for m in mails),
            mail_answer=await self._mail_answer(ticket, mails),
            paperless=(
                await paperless_of(self.session, ticket) if principal.has(PAPERLESS_USE) else None
            ),
        )

    async def _readable_cards(
        self, events: Sequence[TicketEvent], principal: Principal
    ) -> set[uuid.UUID]:
        """The cards of the ``todo_done`` events whose title the viewer may read.

        Without the to-do hooks no title shows.
        """
        ids = {
            card_id
            for e in events
            if e.kind == "todo_done"
            and (card_id := _uuid_or_none((e.payload or {}).get("cardId"))) is not None
        }
        if not ids or self.todos is None:
            return set()
        return await self.todos.readable_cards(ids, principal)

    async def _context_target(self, ticket: Ticket, principal: Principal) -> ContextTarget | None:
        """Resolve ``context.route`` to the application or meeting it names.

        The target shows only when the viewer reads it through the gate of its own
        module; anything else gives None.
        """
        route = (ticket.context or {}).get("route")
        match = _ROUTE_RE.match(route) if isinstance(route, str) else None
        if match is None:
            return None
        kind, raw_id = match.groups()
        try:
            target_id = uuid.UUID(raw_id)
        except ValueError:
            return None
        if kind == "applications":
            return await self._application_target(target_id, principal)
        return await self._meeting_target(target_id, principal)

    async def _application_target(
        self, application_id: uuid.UUID, principal: Principal
    ) -> ContextTarget | None:
        app = await self.session.get(Application, application_id)
        if app is None or app.email_confirmed_at is None:
            return None
        try:
            await resolve_app_read(self.session, application_id, principal, None)
        except ForbiddenError:
            return None
        return ContextTarget(kind="application", id=app.id, title=_title_of(app.data) or "")

    async def _meeting_target(
        self, meeting_id: uuid.UUID, principal: Principal
    ) -> ContextTarget | None:
        from app.modules.livevote.service import MeetingService

        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            return None
        try:
            await MeetingService(self.session).assert_can_read(meeting_id, principal)
        except ForbiddenError:
            return None
        return ContextTarget(kind="meeting", id=meeting.id, title=meeting.title)
