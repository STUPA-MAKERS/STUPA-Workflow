"""Ticket service: report, list, detail, change, notes, anonymization.

The service trusts its caller for the permission: the router lets only a holder of
``ticket.manage`` reach every method except ``create``. The service still decides
who may be the assignee (a holder of ``ticket.manage``) and who may edit a note
(its author).

The to-do coupling (``openTodoCount`` and ``completeTodos``) runs through
``TicketTodoHooks``. Without hooks the count is 0 and ``completeTodos`` changes no
card.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import JsonValue
from sqlalchemy import ColumnElement, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.applications.access import resolve_app_read
from app.modules.applications.models import Application
from app.modules.applications.service.service_base import _title_of
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.files.drafts import bind_drafts, check_drafts
from app.modules.files.service import FilesService
from app.modules.livevote.models import Meeting
from app.modules.tickets.access import TICKET_MANAGE
from app.modules.tickets.models import (
    CLOSED_STATUSES,
    TICKET_STATUSES,
    Ticket,
    TicketEvent,
    TicketNote,
)
from app.modules.tickets.schemas import (
    ContextTarget,
    TicketAttachment,
    TicketCounts,
    TicketCreate,
    TicketDetail,
    TicketEventOut,
    TicketListItem,
    TicketNoteOut,
    TicketPatch,
    TicketRef,
    TicketReporter,
)
from app.search import escape_like
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem
from app.shared.paging import Page
from app.shared.people import (
    DELETED_PERSON,
    PersonRef,
    permission_holders,
    person_of,
)

#: ``T-0040``, ``t0040``, ``0040`` and ``40`` all name ticket 40.
_NUMBER_RE = re.compile(r"^(?:t-?)?0*(\d{1,9})$", re.IGNORECASE)
#: The route of an application or a meeting in ``context.route``.
_ROUTE_RE = re.compile(r"^/(applications|meetings)/([0-9a-fA-F-]{36})(?:[/?#].*)?$")

AssigneeFilter = uuid.UUID | Literal["me", "none"]


def format_number(number: int) -> str:
    """Render a ticket number: ``T-`` and at least four digits."""
    return f"T-{number:04d}"


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


async def ticket_managers(
    session: AsyncSession, *, principal_id: uuid.UUID | None = None
) -> list[tuple[uuid.UUID, str | None, str | None]]:
    """Return ``(id, display_name, email)`` of the active holders of ``ticket.manage``.

    See ``permission_holders``: role assignments plus OIDC group mappings, the admin
    role always counts, merged or inactive accounts never. ``principal_id`` narrows
    the result to one account.
    """
    return await permission_holders(session, TICKET_MANAGE, principal_id=principal_id)


async def principal_id_of(session: AsyncSession, sub: str) -> uuid.UUID | None:
    """Return the row id of the account with this ``sub``."""
    return await session.scalar(select(PrincipalRow.id).where(PrincipalRow.sub == sub))


class TicketService:
    """Ticket operations bound to an ``AsyncSession``."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        files: FilesService | None = None,
        todos: TicketTodoHooks | None = None,
    ) -> None:
        self.session = session
        self.files = files or FilesService(session)
        self.todos = todos

    # -- report -----------------------------------------------------------------

    async def create(
        self,
        payload: TicketCreate,
        *,
        reporter_id: uuid.UUID | None,
        email: str | None,
        pepper: str,
    ) -> Ticket:
        """Store a report, bind its draft attachments and write the ``created`` event.

        ``reporter_id`` is the account of a session, else ``email`` is the address of
        the reporter. The router makes sure that one of them is set.

        Raises:
            ValidationProblem: Attachments without a draft token, or a draft that is
                missing, expired, foreign or infected (HTTP 422).
        """
        if payload.attachment_ids and not payload.draft_token:
            raise ValidationProblem(
                "Attachments need the draft token of their upload.",
                errors=[{"field": "draftToken", "msg": "required with attachmentIds"}],
            )
        if payload.attachment_ids and payload.draft_token:
            await check_drafts(
                self.session,
                attachment_ids=payload.attachment_ids,
                token=payload.draft_token,
                pepper=pepper,
            )
        ticket = Ticket(
            id=uuid.uuid4(),
            kind=payload.kind,
            title=payload.title.strip() or payload.title,
            body=payload.body,
            status="new",
            reporter_principal_id=reporter_id,
            reporter_email=None if reporter_id is not None else email,
            context=payload.context.model_dump(by_alias=True, exclude_none=True),
        )
        self.session.add(ticket)
        await self.session.flush()
        if payload.attachment_ids and payload.draft_token:
            await bind_drafts(
                self.session,
                attachment_ids=payload.attachment_ids,
                token=payload.draft_token,
                pepper=pepper,
                ticket_id=ticket.id,
            )
        confirmation = await self.reporter_address(ticket) is not None
        self.session.add(
            TicketEvent(
                ticket_id=ticket.id,
                actor_id=reporter_id,
                kind="created",
                payload={"confirmationSent": confirmation},
            )
        )
        await self.session.commit()
        return ticket

    async def reporter_address(self, ticket: Ticket) -> str | None:
        """Return the address of the reporter: the account e-mail or the given e-mail."""
        if ticket.reporter_principal_id is None:
            return ticket.reporter_email
        return await self.session.scalar(
            select(PrincipalRow.email).where(PrincipalRow.id == ticket.reporter_principal_id)
        )

    # -- reads ------------------------------------------------------------------

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
    ) -> Page[TicketListItem]:
        """List the tickets, newest first, with the filters of ``GET /tickets``.

        ``q`` matches the title, the body, the number (``T-0040``, ``0040``, ``40``),
        and the name and e-mail of the reporter.
        """
        reporter = aliased(PrincipalRow)
        conds: list[ColumnElement[bool]] = []
        if statuses:
            conds.append(Ticket.status.in_(list(statuses)))
        if kinds:
            conds.append(Ticket.kind.in_(list(kinds)))
        if assignee == "none":
            conds.append(Ticket.assignee_id.is_(None))
        elif assignee == "me":
            conds.append(Ticket.assignee_id == me)
        elif assignee is not None:
            conds.append(Ticket.assignee_id == assignee)
        term = (q or "").strip()
        if term:
            pattern = f"%{escape_like(term)}%"
            matches: list[ColumnElement[bool]] = [
                Ticket.title.ilike(pattern, escape="\\"),
                Ticket.body.ilike(pattern, escape="\\"),
                cast(Ticket.reporter_email, String).ilike(pattern, escape="\\"),
                reporter.display_name.ilike(pattern, escape="\\"),
                cast(reporter.email, String).ilike(pattern, escape="\\"),
            ]
            number = _NUMBER_RE.match(term)
            if number is not None:
                matches.append(Ticket.number == int(number.group(1)))
            conds.append(or_(*matches))
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

    async def counts(self) -> TicketCounts:
        """Count the tickets per status."""
        rows = (
            await self.session.execute(select(Ticket.status, func.count()).group_by(Ticket.status))
        ).all()
        by_status = {status: int(n) for status, n in rows}
        return TicketCounts(
            new=by_status.get("new", 0),
            in_progress=by_status.get("in_progress", 0),
            done=by_status.get("done", 0),
            rejected=by_status.get("rejected", 0),
        )

    async def assignees(self) -> list[PersonRef]:
        """List the possible assignees (the holders of ``ticket.manage``), by name."""
        people = [
            person_of(pid, name, email) for pid, name, email in await ticket_managers(self.session)
        ]
        named = [p for p in people if p.principal_id is not None]
        return sorted(named, key=lambda p: ((p.display_name or "").casefold(), str(p.principal_id)))

    async def detail(self, ticket_id: uuid.UUID, principal: Principal) -> TicketDetail:
        """Return the whole ticket: notes, events, attachments and the links.

        Raises:
            NotFoundError: No ticket has this id (HTTP 404).
        """
        ticket = await self._get(ticket_id)
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
        people: set[uuid.UUID | None] = {n.author_id for n in notes}
        for event in events:
            people.add(event.actor_id)
            if event.kind == "assignee":
                people.update(_ids_of(event.payload))
        accounts = await self._accounts([ticket], extra=people)
        readable = await self._readable_cards(events, principal)
        duplicate = (
            await self.session.get(Ticket, ticket.duplicate_of_id)
            if ticket.duplicate_of_id is not None
            else None
        )
        item = self._list_item(ticket, accounts)
        return TicketDetail(
            **item.model_dump(),
            body=ticket.body,
            context=dict(ticket.context or {}),
            attachments=[
                TicketAttachment.of(a) for a in await self.files.list_for_ticket(ticket.id)
            ],
            notes=[
                TicketNoteOut(
                    id=n.id,
                    author=_person(accounts, n.author_id),
                    body=n.body,
                    at=n.created_at,
                    edited_at=n.edited_at,
                    is_own=me is not None and n.author_id == me,
                )
                for n in notes
            ],
            events=[_event_out(e, accounts, readable) for e in events],
            duplicate_of=(
                TicketRef(id=duplicate.id, number=format_number(duplicate.number))
                if duplicate is not None
                else None
            ),
            context_target=await self._context_target(ticket, principal),
            open_todo_count=(
                await self.todos.open_count(ticket.id, principal) if self.todos else 0
            ),
            closed_at=ticket.closed_at,
            anonymized_at=ticket.anonymized_at,
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

    # -- writes -----------------------------------------------------------------

    async def patch(
        self, ticket_id: uuid.UUID, payload: TicketPatch, principal: Principal
    ) -> TicketDetail:
        """Change the status, the assignee or the kind, and write one event per change.

        A status change into ``done`` or ``rejected`` sets ``closed_at``, a reopen
        clears it. ``duplicateOfId`` goes with ``status: rejected`` only and names
        another ticket. ``completeTodos`` goes with ``done`` or ``rejected`` only.

        Raises:
            NotFoundError: No ticket has this id (HTTP 404).
            ValidationProblem: ``assignee_not_allowed``, ``duplicate_invalid``, or
                ``completeTodos`` without a closing status (HTTP 422).
        """
        ticket = await self._get(ticket_id)
        fields = payload.model_fields_set
        actor = await principal_id_of(self.session, principal.sub)
        duplicate = await self._duplicate_target(ticket, payload)
        if payload.complete_todos and payload.status not in CLOSED_STATUSES:
            raise ValidationProblem(
                "completeTodos goes with the status done or rejected.",
                errors=[{"field": "completeTodos", "msg": "needs status done or rejected"}],
            )
        if (
            "assignee_id" in fields
            and payload.assignee_id is not None
            and not await ticket_managers(self.session, principal_id=payload.assignee_id)
        ):
            raise ValidationProblem(
                "The assignee must hold ticket.manage.",
                code="assignee_not_allowed",
                errors=[{"field": "assigneeId", "msg": "not a ticket manager"}],
            )
        changed = False
        if payload.status is not None and (
            payload.status != ticket.status or duplicate is not None
        ):
            self._set_status(ticket, payload.status, duplicate, actor)
            changed = True
        if "assignee_id" in fields and payload.assignee_id != ticket.assignee_id:
            self._event(
                ticket,
                "assignee",
                actor,
                {
                    "from": _id_or_none(ticket.assignee_id),
                    "to": _id_or_none(payload.assignee_id),
                },
            )
            ticket.assignee_id = payload.assignee_id
            changed = True
        if payload.kind is not None and payload.kind != ticket.kind:
            self._event(ticket, "kind", actor, {"from": ticket.kind, "to": payload.kind})
            ticket.kind = payload.kind
            changed = True
        if changed:
            ticket.updated_at = _now()
        await self.session.commit()
        if payload.complete_todos and self.todos is not None:
            await self.todos.complete(ticket.id, principal)
        return await self.detail(ticket.id, principal)

    async def _duplicate_target(self, ticket: Ticket, payload: TicketPatch) -> Ticket | None:
        if payload.duplicate_of_id is None:
            return None
        target = (
            await self.session.get(Ticket, payload.duplicate_of_id)
            if payload.status == "rejected" and payload.duplicate_of_id != ticket.id
            else None
        )
        if target is None:
            raise ValidationProblem(
                "duplicateOfId names another ticket and goes with status rejected.",
                code="duplicate_invalid",
                errors=[{"field": "duplicateOfId", "msg": "invalid duplicate"}],
            )
        return target

    def _set_status(
        self,
        ticket: Ticket,
        status: str,
        duplicate: Ticket | None,
        actor: uuid.UUID | None,
    ) -> None:
        payload: dict[str, JsonValue] = {"from": ticket.status, "to": status}
        if duplicate is not None:
            payload["duplicateOf"] = format_number(duplicate.number)
        self._event(ticket, "status", actor, payload)
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
        # The clock of the process, not now() of the transaction: one change can
        # write two events, and the timeline orders them by this time.
        self.session.add(
            TicketEvent(
                ticket_id=ticket.id,
                actor_id=actor,
                kind=kind,
                payload=payload,
                created_at=_now(),
            )
        )

    async def add_note(
        self, ticket_id: uuid.UUID, body: str, principal: Principal
    ) -> TicketNoteOut:
        """Add an internal note.

        Raises:
            NotFoundError: No ticket has this id, or the caller has no account row
                (HTTP 404).
        """
        ticket = await self._get(ticket_id)
        author = await self._require_account(principal)
        note = TicketNote(id=uuid.uuid4(), ticket_id=ticket.id, author_id=author, body=body)
        self.session.add(note)
        ticket.updated_at = _now()
        await self.session.commit()
        await self.session.refresh(note)
        return await self._note_out(note, author)

    async def edit_note(
        self, ticket_id: uuid.UUID, note_id: uuid.UUID, body: str, principal: Principal
    ) -> TicketNoteOut:
        """Change the text of an own note and set ``edited_at``.

        Raises:
            NotFoundError: No live note with this id on this ticket (HTTP 404).
            ForbiddenError: The note has another author (HTTP 403, ``not_note_author``).
        """
        note, me = await self._own_note(ticket_id, note_id, principal)
        note.body = body
        note.edited_at = _now()
        await self.session.commit()
        return await self._note_out(note, me)

    async def delete_note(
        self, ticket_id: uuid.UUID, note_id: uuid.UUID, principal: Principal
    ) -> None:
        """Soft-delete an own note (``deleted_at``); the detail omits it.

        Raises:
            NotFoundError: No live note with this id on this ticket (HTTP 404).
            ForbiddenError: The note has another author (HTTP 403, ``not_note_author``).
        """
        note, _me = await self._own_note(ticket_id, note_id, principal)
        note.deleted_at = _now()
        await self.session.commit()

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

    async def _note_out(self, note: TicketNote, me: uuid.UUID) -> TicketNoteOut:
        accounts = await self._load_accounts({note.author_id})
        return TicketNoteOut(
            id=note.id,
            author=_person(accounts, note.author_id),
            body=note.body,
            at=note.created_at,
            edited_at=note.edited_at,
            is_own=note.author_id == me,
        )

    # -- anonymization ----------------------------------------------------------

    async def anonymize(self, ticket: Ticket, *, actor: str) -> None:
        """Remove the personal data of a ticket, without a commit.

        The reporter (account and e-mail), the context and the attachments (rows and
        objects) go; title, body, notes and events stay. ``anonymized_at`` marks it.
        """
        await self.files.delete_for_ticket(ticket.id, actor=actor)
        ticket.reporter_principal_id = None
        ticket.reporter_email = None
        ticket.context = {}
        ticket.anonymized_at = _now()

    # -- helpers ----------------------------------------------------------------

    async def _get(self, ticket_id: uuid.UUID) -> Ticket:
        ticket = await self.session.get(Ticket, ticket_id)
        if ticket is None:
            raise NotFoundError(f"ticket {ticket_id} not found")
        return ticket

    async def _require_account(self, principal: Principal) -> uuid.UUID:
        me = await principal_id_of(self.session, principal.sub)
        if me is None:
            raise NotFoundError("account not found")
        return me

    async def _accounts(
        self, tickets: Sequence[Ticket], *, extra: set[uuid.UUID | None] | None = None
    ) -> dict[uuid.UUID, _Account]:
        ids: set[uuid.UUID | None] = set(extra or set())
        for ticket in tickets:
            ids.add(ticket.reporter_principal_id)
            ids.add(ticket.assignee_id)
        return await self._load_accounts(ids)

    async def _load_accounts(self, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, _Account]:
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
            kind=ticket.kind,  # pyright: ignore[reportArgumentType]
            title=ticket.title,
            status=ticket.status,  # pyright: ignore[reportArgumentType]
            reporter=_reporter(ticket, accounts),
            assignee=(
                _person(accounts, ticket.assignee_id) if ticket.assignee_id is not None else None
            ),
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
        )

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
        target_id = uuid.UUID(raw_id)
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


def _id_or_none(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _ids_of(payload: dict[str, JsonValue]) -> set[uuid.UUID | None]:
    out: set[uuid.UUID | None] = set()
    for key in ("from", "to"):
        raw = payload.get(key)
        if isinstance(raw, str):
            out.add(uuid.UUID(raw))
    return out


def _person(accounts: dict[uuid.UUID, _Account], principal_id: uuid.UUID) -> PersonRef:
    account = accounts.get(principal_id)
    if account is None:
        return DELETED_PERSON
    return person_of(principal_id, account.display_name, account.email)


def _reporter(ticket: Ticket, accounts: dict[uuid.UUID, _Account]) -> TicketReporter:
    if ticket.anonymized_at is not None:
        return TicketReporter(anonymized=True)
    if ticket.reporter_principal_id is None:
        return TicketReporter(email=ticket.reporter_email)
    person = _person(accounts, ticket.reporter_principal_id)
    account = accounts.get(ticket.reporter_principal_id)
    return TicketReporter(
        principal_id=person.principal_id,
        display_name=person.display_name,
        email=account.email if account is not None else None,
    )


def _uuid_or_none(raw: JsonValue) -> uuid.UUID | None:
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def _event_out(
    event: TicketEvent,
    accounts: dict[uuid.UUID, _Account],
    readable_cards: set[uuid.UUID] | None = None,
) -> TicketEventOut:
    payload: dict[str, JsonValue] = dict(event.payload or {})
    if event.kind == "todo_done" and _uuid_or_none(payload.get("cardId")) not in (
        readable_cards or set()
    ):
        # The card title shows only to a reader of the board of the card.
        payload["cardTitle"] = None
    if event.kind == "assignee":
        for key in ("from", "to"):
            raw = payload.get(key)
            payload[key] = (
                _person(accounts, uuid.UUID(raw)).model_dump(by_alias=True, mode="json")
                if isinstance(raw, str)
                else None
            )
    return TicketEventOut(
        id=event.id,
        kind=event.kind,  # pyright: ignore[reportArgumentType]
        actor=_person(accounts, event.actor_id) if event.actor_id is not None else None,
        at=event.created_at,
        payload=payload,
    )


__all__ = [
    "TICKET_STATUSES",
    "AssigneeFilter",
    "TicketService",
    "TicketTodoHooks",
    "format_number",
    "principal_id_of",
    "ticket_managers",
]
