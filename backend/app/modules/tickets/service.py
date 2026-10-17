"""Ticket service: report, list, detail, change, notes, anonymization.

The service trusts its caller for the permission: the router lets only a holder of
``ticket.manage`` reach every method except ``create`` and the ``reporter_*`` methods.
The service still decides who may be the assignee (a holder of ``ticket.manage``) and
who may edit a note (its author).

The ``reporter_*`` methods are the view of the reporter account on its own tickets:
the report, the ``public`` notes and the status changes, plus its own messages. They
check the reporter themselves and answer 404 for any other ticket, so the routes are
no existence oracle. An anonymized ticket has no reporter any more.

The to-do coupling (``openTodoCount`` and ``completeTodos``) runs through
``TicketTodoHooks``. Without hooks the count is 0 and ``completeTodos`` changes no
card.

A team note can mention holders of ``ticket.manage`` (``mentions``, the set of
``assignees``); another id is 422 ``mention_not_member``. ``add_note`` and
``edit_note`` put the mentions that they added into ``added_mentions``, and the router
mails exactly those after the commit. A message of the reporter mentions nobody, its
edit keeps the stored mentions, and the view of the reporter never shows them.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import JsonValue
from sqlalchemy import ColumnElement, String, cast, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.applications.access import resolve_app_read
from app.modules.applications.models import Application
from app.modules.applications.service.service_base import _title_of
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.files.drafts import bind_drafts, check_drafts, check_message_drafts
from app.modules.files.schemas import MessageAttachmentOut
from app.modules.files.service import FilesService
from app.modules.livevote.models import Meeting
from app.modules.tickets.access import TICKET_MANAGE
from app.modules.tickets.models import (
    CLOSED_STATUSES,
    TICKET_NUMBER_SEQ,
    TICKET_STATUSES,
    Ticket,
    TicketEvent,
    TicketNote,
    TicketSenderBlock,
)
from app.modules.tickets.schemas import (
    ContextTarget,
    NoteCreate,
    ReporterNoteCreate,
    ReporterTicketDetail,
    ReporterTicketEvent,
    ReporterTicketItem,
    TicketAttachment,
    TicketBlockedSender,
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
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from app.shared.mentions import (
    check_mentions,
    mention_ids,
    new_mentions,
    stored_mentions,
    unique_mentions,
)
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

#: What a block targets: an account id or a normalized e-mail address.
BlockTarget = tuple[Literal["principal"], uuid.UUID] | tuple[Literal["email"], str]


def normalize_email(value: str) -> str:
    """Normalize an address for ``ticket_sender_block.email``: strip and lowercase."""
    return value.strip().lower()


@dataclass(frozen=True, slots=True)
class SwallowedReport:
    """The answer to a report of a blocked sender: a number, and no ticket.

    ``id`` is always None, so the router sends no mail.
    """

    number: int
    id: None = None


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

    #: The mentions that the last ``add_note`` or ``edit_note`` added, for the mail.
    added_mentions: Sequence[uuid.UUID] = ()

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
    ) -> Ticket | SwallowedReport:
        """Store a report, bind its draft attachments and write the ``created`` event.

        ``reporter_id`` is the account of a session, else ``email`` is the address of
        the reporter. The router makes sure that one of them is set.

        A report of a blocked sender (``matching_block``) passes every check of a
        normal report first, so its errors look the same. It then takes a number from
        ``ticket_number_seq`` and stores nothing: no ticket, no event, no bind. The
        result is a ``SwallowedReport`` and the router sends no mail. The drafts stay
        unbound until the purge.

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
        block_id = await self.matching_block(reporter_id=reporter_id, email=email)
        if block_id is not None:
            return await self._swallow(block_id)
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

    async def matching_block(
        self, *, reporter_id: uuid.UUID | None, email: str | None
    ) -> uuid.UUID | None:
        """Return the block that a new report meets, else None.

        With an account the block names the account, or the account e-mail. Without
        one the block names the given e-mail, or an account with that e-mail. Both
        compares are case-insensitive.
        """
        cond = self._sender_condition(reporter_id=reporter_id, email=email)
        if cond is None:
            return None
        return await self.session.scalar(
            select(TicketSenderBlock.id).where(cond).order_by(TicketSenderBlock.created_at).limit(1)
        )

    @classmethod
    def _sender_condition(
        cls, *, reporter_id: uuid.UUID | None, email: str | None
    ) -> ColumnElement[bool] | None:
        """Return the condition of the blocks that hold back this sender, else None.

        The report, the ``senderBlocked`` flag and the unblock of a ticket share this
        condition, so a block that swallows a report always shows on the ticket and
        lifts there.
        """
        if reporter_id is not None:
            return cls._account_condition(reporter_id)
        if email:
            return cls._email_condition(normalize_email(email))
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

    async def _swallow(self, block_id: uuid.UUID) -> SwallowedReport:
        """Take a number for a blocked report and count the hit; store no ticket.

        The log line names the block, never the address.
        """
        number = await self.session.scalar(select(TICKET_NUMBER_SEQ.next_value()))
        await self.session.execute(
            update(TicketSenderBlock)
            .where(TicketSenderBlock.id == block_id)
            .values(hit_count=TicketSenderBlock.hit_count + 1, last_hit_at=_now())
        )
        await self.session.commit()
        logger.info("report held back by sender block %s", block_id)
        return SwallowedReport(number=int(number or 0))

    # -- sender blocks ------------------------------------------------------------

    @staticmethod
    def block_target(ticket: Ticket) -> BlockTarget | None:
        """Return what a block of this ticket's sender targets.

        An anonymized ticket has no sender any more and gives None.
        """
        if ticket.anonymized_at is not None:
            return None
        if ticket.reporter_principal_id is not None:
            return ("principal", ticket.reporter_principal_id)
        if ticket.reporter_email:
            return ("email", normalize_email(ticket.reporter_email))
        return None

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

    def _sender_target(self, ticket: Ticket) -> BlockTarget:
        target = self.block_target(ticket)
        if target is None:
            raise ConflictError("The ticket has no sender any more.", code=SENDER_UNKNOWN)
        return target

    async def block_sender(self, ticket_id: uuid.UUID, principal: Principal) -> TicketDetail:
        """Block the sender of a ticket; a second block changes nothing.

        Raises:
            NotFoundError: No ticket has this id (HTTP 404).
            ConflictError: The ticket is anonymized (HTTP 409, ``ticket_sender_unknown``).
            ValidationProblem: The sender is the caller (HTTP 422, ``sender_is_self``).
        """
        ticket = await self._get(ticket_id)
        target = self._sender_target(ticket)
        me = await principal_id_of(self.session, principal.sub)
        if target[0] == "principal":
            is_self = me is not None and target[1] == me
        else:
            own = (
                await self.session.scalar(select(PrincipalRow.email).where(PrincipalRow.id == me))
                if me is not None
                else None
            )
            is_self = own is not None and normalize_email(own) == target[1]
        if is_self:
            raise ValidationProblem(
                "You cannot block yourself.",
                code=SENDER_IS_SELF,
                errors=[{"field": "ticketId", "msg": "the sender is the caller"}],
            )
        values: dict[str, object] = {
            "source_ticket_id": ticket.id,
            "created_by": me,
            "principal_id": target[1] if target[0] == "principal" else None,
            "email": target[1] if target[0] == "email" else None,
        }
        await self.session.execute(
            insert(TicketSenderBlock).values(**values).on_conflict_do_nothing()
        )
        await self.session.commit()
        return await self.detail(ticket.id, principal)

    async def unblock_sender(self, ticket_id: uuid.UUID, principal: Principal) -> TicketDetail:
        """Lift every block that holds back a ticket's sender; without one nothing changes.

        That is the block of the account and of its e-mail, or the block of the e-mail
        and of every account with that e-mail, the same blocks that swallow a report.

        Raises:
            NotFoundError: No ticket has this id (HTTP 404).
            ConflictError: The ticket is anonymized (HTTP 409, ``ticket_sender_unknown``).
        """
        ticket = await self._get(ticket_id)
        target = self._sender_target(ticket)
        await self.session.execute(delete(TicketSenderBlock).where(self._target_condition(target)))
        await self.session.commit()
        return await self.detail(ticket.id, principal)

    async def blocked_senders(self) -> list[TicketBlockedSender]:
        """List the blocked senders, newest first."""
        rows = list(
            (
                await self.session.scalars(
                    select(TicketSenderBlock).order_by(
                        TicketSenderBlock.created_at.desc(), TicketSenderBlock.id
                    )
                )
            ).all()
        )
        people: set[uuid.UUID | None] = set()
        for row in rows:
            people.add(row.principal_id)
            people.add(row.created_by)
        accounts = await self._load_accounts(people)
        sources = {r.source_ticket_id for r in rows if r.source_ticket_id is not None}
        numbers: dict[uuid.UUID, int] = (
            {
                tid: int(number)
                for tid, number in (
                    await self.session.execute(
                        select(Ticket.id, Ticket.number).where(Ticket.id.in_(sources))
                    )
                ).all()
            }
            if sources
            else {}
        )
        out: list[TicketBlockedSender] = []
        for row in rows:
            account = accounts.get(row.principal_id) if row.principal_id is not None else None
            source = numbers.get(row.source_ticket_id) if row.source_ticket_id else None
            out.append(
                TicketBlockedSender(
                    id=row.id,
                    kind="principal" if row.principal_id is not None else "email",
                    person=(
                        _person(accounts, row.principal_id)
                        if row.principal_id is not None
                        else None
                    ),
                    email=account.email if account is not None else row.email,
                    blocked_by=(
                        _person(accounts, row.created_by) if row.created_by is not None else None
                    ),
                    blocked_at=row.created_at,
                    source_ticket=(
                        TicketRef(id=row.source_ticket_id, number=format_number(source))
                        if row.source_ticket_id is not None and source is not None
                        else None
                    ),
                    hit_count=row.hit_count,
                    last_hit_at=row.last_hit_at,
                )
            )
        return out

    async def delete_block(self, block_id: uuid.UUID) -> None:
        """Lift one block by its id.

        Raises:
            NotFoundError: No block has this id (HTTP 404).
        """
        removed = (
            await self.session.execute(
                delete(TicketSenderBlock)
                .where(TicketSenderBlock.id == block_id)
                .returning(TicketSenderBlock.id)
            )
        ).first()
        if removed is None:
            raise NotFoundError(f"block {block_id} not found")
        await self.session.commit()

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

    async def _checked_mentions(
        self, mentions: Sequence[uuid.UUID], before: Sequence[uuid.UUID] = ()
    ) -> list[uuid.UUID]:
        """Return the mentions without duplicates, after the check against ``assignees``.

        Only the mentions that are not in ``before`` are checked, so an edit keeps a
        mention of a person who lost ``ticket.manage`` since the create.

        Raises:
            ValidationProblem: A new mention of a person who does not hold
                ``ticket.manage`` (HTTP 422, ``mention_not_member``).
        """
        wanted = unique_mentions(mentions)
        added = new_mentions(wanted, before)
        if added:
            allowed = {p.principal_id for p in await self.assignees()}
            check_mentions(added, {pid for pid in allowed if pid is not None})
        return wanted

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
        for note in notes:
            people.update(mention_ids(note.mentions))
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
        files = await self.files.message_attachments("ticket_note", [n.id for n in notes])
        return TicketDetail(
            **item.model_dump(),
            body=ticket.body,
            context=dict(ticket.context or {}),
            attachments=[
                TicketAttachment.of(a) for a in await self.files.list_for_ticket(ticket.id)
            ],
            notes=[_note_row(n, ticket, accounts, me, files.get(n.id, [])) for n in notes],
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
            sender_blocked=await self._sender_blocked(ticket),
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
        self, ticket_id: uuid.UUID, payload: NoteCreate, principal: Principal, *, pepper: str
    ) -> TicketNoteOut:
        """Add a note (``internal`` or ``public``) and bind its files.

        Raises:
            NotFoundError: No ticket has this id, or the caller has no account row
                (HTTP 404).
            ValidationProblem: Files on an anonymized ticket (``ticket_anonymized``),
                files without a draft token, or a draft that is missing, expired,
                foreign or infected, or a mention of a person who does not hold
                ``ticket.manage`` (``mention_not_member``) (HTTP 422).
        """
        # With files the ticket row is locked, so the retention cron (which locks it
        # too) cannot anonymize it between this check and the commit: it ran once and
        # would not see the file again.
        ticket = await self._get(ticket_id, lock=bool(payload.attachment_ids))
        author = await self._require_account(principal)
        wanted = await self._checked_mentions(payload.mentions)
        note = await self._insert_note(
            ticket,
            author,
            body=payload.body,
            visibility=payload.visibility,
            attachment_ids=payload.attachment_ids,
            draft_token=payload.draft_token,
            pepper=pepper,
            mentions=wanted,
        )
        self.added_mentions = wanted
        return note

    async def _insert_note(
        self,
        ticket: Ticket,
        author: uuid.UUID,
        *,
        body: str,
        visibility: str,
        attachment_ids: list[uuid.UUID],
        draft_token: str | None,
        pepper: str,
        for_reporter: bool = False,
        mentions: Sequence[uuid.UUID] = (),
    ) -> TicketNoteOut:
        """Store a note, bind its files and commit. The caller read the ticket."""
        if attachment_ids and ticket.anonymized_at is not None:
            raise ValidationProblem(
                "The ticket is anonymized and takes no files.",
                code=TICKET_ANONYMIZED,
                errors=[{"field": "attachmentIds", "msg": "ticket is anonymized"}],
            )
        token = await check_message_drafts(
            self.session,
            attachment_ids=attachment_ids,
            token=draft_token,
            pepper=pepper,
        )
        note = TicketNote(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            author_id=author,
            body=body,
            visibility=visibility,
            mentions=stored_mentions(mentions),
        )
        self.session.add(note)
        if token is not None:
            await self.session.flush()
            await bind_drafts(
                self.session,
                attachment_ids=attachment_ids,
                token=token,
                pepper=pepper,
                ticket_note_id=note.id,
            )
        ticket.updated_at = _now()
        await self.session.commit()
        await self.session.refresh(note)
        return await self._note_out(note, author, ticket, for_reporter=for_reporter)

    async def edit_note(
        self,
        ticket_id: uuid.UUID,
        note_id: uuid.UUID,
        body: str,
        principal: Principal,
        *,
        mentions: Sequence[uuid.UUID] | None = None,
    ) -> TicketNoteOut:
        """Change the text of an own note and set ``edited_at``; the files stay.

        ``mentions`` None keeps the stored mentions; a list replaces them after the
        check of ``add_note``. ``added_mentions`` holds the ids that the list adds.

        Raises:
            NotFoundError: No live note with this id on this ticket (HTTP 404).
            ForbiddenError: The note has another author (HTTP 403, ``not_note_author``).
            ValidationProblem: A mention of a person who does not hold
                ``ticket.manage`` (HTTP 422, ``mention_not_member``).
        """
        note, me = await self._own_note(ticket_id, note_id, principal)
        self.added_mentions = []
        if mentions is not None:
            before = mention_ids(note.mentions)
            wanted = await self._checked_mentions(mentions, before)
            self.added_mentions = new_mentions(wanted, before)
            note.mentions = stored_mentions(wanted)
        note.body = body
        note.edited_at = _now()
        await self.session.commit()
        return await self._note_out(note, me, await self._get(ticket_id))

    async def delete_note(
        self, ticket_id: uuid.UUID, note_id: uuid.UUID, principal: Principal
    ) -> None:
        """Soft-delete an own note (``deleted_at``) and remove its files.

        Raises:
            NotFoundError: No live note with this id on this ticket (HTTP 404).
            ForbiddenError: The note has another author (HTTP 403, ``not_note_author``).
        """
        note, _me = await self._own_note(ticket_id, note_id, principal)
        note.deleted_at = _now()
        await self.files.delete_for_messages("ticket_note", [note.id], actor=principal.sub)
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

    async def _note_out(
        self, note: TicketNote, me: uuid.UUID, ticket: Ticket, *, for_reporter: bool = False
    ) -> TicketNoteOut:
        wanted: set[uuid.UUID | None] = {note.author_id}
        if not for_reporter:
            wanted.update(mention_ids(note.mentions))
        accounts = await self._load_accounts(wanted)
        files = await self.files.message_attachments("ticket_note", [note.id])
        return _note_row(
            note, ticket, accounts, me, files.get(note.id, []), for_reporter=for_reporter
        )

    # -- the view of the reporter -----------------------------------------------

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
        reporter any more and never show.
        """
        conds: list[ColumnElement[bool]] = [
            Ticket.reporter_principal_id == me,
            Ticket.anonymized_at.is_(None),
        ]
        if statuses:
            conds.append(Ticket.status.in_(list(statuses)))
        if kinds:
            conds.append(Ticket.kind.in_(list(kinds)))
        term = (q or "").strip()
        if term:
            pattern = f"%{escape_like(term)}%"
            matches: list[ColumnElement[bool]] = [
                Ticket.title.ilike(pattern, escape="\\"),
                Ticket.body.ilike(pattern, escape="\\"),
            ]
            number = _NUMBER_RE.match(term)
            if number is not None:
                matches.append(Ticket.number == int(number.group(1)))
            conds.append(or_(*matches))
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
            body=ticket.body,
            attachments=[
                TicketAttachment.of(a) for a in await self.files.list_for_ticket(ticket.id)
            ],
            notes=[
                _note_row(n, ticket, accounts, me, files.get(n.id, []), for_reporter=True)
                for n in notes
            ],
            events=[
                ReporterTicketEvent(
                    id=e.id,
                    kind="status",
                    at=e.created_at,
                    payload={k: v for k, v in (e.payload or {}).items() if k in ("from", "to")},
                )
                for e in events
            ],
            closed_at=ticket.closed_at,
            can_reply=not await self._sender_blocked(ticket),
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

        Raises:
            NotFoundError: Not a ticket of the caller (HTTP 404).
            ForbiddenError: A sender block holds back the reporter (HTTP 403,
                ``sender_blocked``).
            ValidationProblem: Files without a draft token, or a draft that is missing,
                expired, foreign or infected (HTTP 422).
        """
        # Always under the row lock: an anonymization that runs between the check and the
        # commit would miss the new note and leave the reporter on an anonymized ticket.
        ticket, me = await self._reporter_ticket(ticket_id, principal, lock=True)
        if await self._sender_blocked(ticket):
            raise ForbiddenError("The sender is blocked.", code=SENDER_BLOCKED)
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

    # -- anonymization ----------------------------------------------------------

    async def anonymize(self, ticket: Ticket, *, actor: str) -> None:
        """Remove the personal data of a ticket, without a commit.

        The reporter (account and e-mail), the context and the files of the report and
        of every note (rows and objects) go; title, body, the note texts and events
        stay. The public notes of the reporter lose their author: a reporter writes only
        public notes, and an internal note of the same account is the work of a team
        member, who must keep the right to change it. A sender block from this
        ticket stays. The ``created`` event loses its actor, because that actor is the
        reporter and the detail would show the name.
        ``anonymized_at`` marks it.
        """
        await self.files.delete_for_ticket(ticket.id, actor=actor)
        if ticket.reporter_principal_id is not None:
            await self.session.execute(
                update(TicketNote)
                .where(
                    TicketNote.ticket_id == ticket.id,
                    TicketNote.author_id == ticket.reporter_principal_id,
                    TicketNote.visibility == "public",
                )
                .values(author_id=None)
            )
        await self.session.execute(
            update(TicketEvent)
            .where(TicketEvent.ticket_id == ticket.id, TicketEvent.kind == "created")
            .values(actor_id=None)
        )
        ticket.reporter_principal_id = None
        ticket.reporter_email = None
        ticket.context = {}
        ticket.anonymized_at = _now()

    # -- helpers ----------------------------------------------------------------

    async def _get(self, ticket_id: uuid.UUID, *, lock: bool = False) -> Ticket:
        if lock:
            ticket = await self.session.get(
                Ticket, ticket_id, with_for_update=True, populate_existing=True
            )
        else:
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


def _id_or_none(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _ids_of(payload: dict[str, JsonValue]) -> set[uuid.UUID | None]:
    out: set[uuid.UUID | None] = set()
    for key in ("from", "to"):
        raw = payload.get(key)
        if isinstance(raw, str):
            out.add(uuid.UUID(raw))
    return out


def _person(accounts: dict[uuid.UUID, _Account], principal_id: uuid.UUID | None) -> PersonRef:
    account = accounts.get(principal_id) if principal_id is not None else None
    if principal_id is None or account is None:
        return DELETED_PERSON
    return person_of(principal_id, account.display_name, account.email)


def _note_row(
    note: TicketNote,
    ticket: Ticket,
    accounts: dict[uuid.UUID, _Account],
    me: uuid.UUID | None,
    attachments: list[MessageAttachmentOut],
    *,
    for_reporter: bool = False,
) -> TicketNoteOut:
    """Build the wire note.

    For the reporter a team author shows by name only: neither the e-mail nor the
    account id of a holder of ``ticket.manage`` reaches the reporter, because the id
    opens the avatar of that e-mail. For the same reason the reporter gets no
    mentions (an empty list).
    """
    author = _person(accounts, note.author_id)
    if for_reporter and note.author_id is not None:
        account = accounts.get(note.author_id)
        own = account is not None and note.author_id == me
        author = PersonRef(
            principal_id=note.author_id if own else None,
            display_name=account.display_name if account is not None else None,
        )
    return TicketNoteOut(
        id=note.id,
        author=author,
        body=note.body,
        at=note.created_at,
        edited_at=note.edited_at,
        is_own=me is not None and note.author_id == me,
        attachments=attachments,
        visibility=note.visibility or "internal",  # pyright: ignore[reportArgumentType]
        from_reporter=(
            note.author_id is not None and note.author_id == ticket.reporter_principal_id
        ),
        mentions=(
            [] if for_reporter else [_person(accounts, pid) for pid in mention_ids(note.mentions)]
        ),
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
    stmt = select(Ticket.id).where(
        Ticket.reporter_principal_id == me, Ticket.anonymized_at.is_(None)
    )
    if kind == "ticket":
        stmt = stmt.where(Ticket.id == owner_id)
    elif kind == "ticket_note":
        stmt = stmt.join(TicketNote, TicketNote.ticket_id == Ticket.id).where(
            TicketNote.id == owner_id,
            TicketNote.deleted_at.is_(None),
            TicketNote.visibility == "public",
        )
    else:
        return False
    return (await session.scalar(stmt.limit(1))) is not None


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


async def erase_sender_blocks(
    session: AsyncSession, *, principal_id: uuid.UUID | None = None, email: str | None = None
) -> None:
    """Delete the blocks of an account and of an address, without a commit (erasure)."""
    conds: list[ColumnElement[bool]] = []
    if principal_id is not None:
        conds.append(TicketSenderBlock.principal_id == principal_id)
    if email:
        conds.append(TicketSenderBlock.email == normalize_email(email))
    if conds:
        await session.execute(delete(TicketSenderBlock).where(or_(*conds)))


async def sender_blocks_of(
    session: AsyncSession, *, principal_id: uuid.UUID | None, email: str
) -> list[TicketSenderBlock]:
    """Return the blocks of an account and of an address, oldest first (Auskunft)."""
    conds: list[ColumnElement[bool]] = [TicketSenderBlock.email == normalize_email(email)]
    if principal_id is not None:
        conds.append(TicketSenderBlock.principal_id == principal_id)
    return list(
        (
            await session.scalars(
                select(TicketSenderBlock)
                .where(or_(*conds))
                .order_by(TicketSenderBlock.created_at, TicketSenderBlock.id)
            )
        ).all()
    )


__all__ = [
    "TICKET_STATUSES",
    "AssigneeFilter",
    "SwallowedReport",
    "TicketService",
    "TicketTodoHooks",
    "erase_sender_blocks",
    "format_number",
    "has_reported_tickets",
    "normalize_email",
    "principal_id_of",
    "reporter_reads_file",
    "sender_blocks_of",
    "ticket_managers",
]
