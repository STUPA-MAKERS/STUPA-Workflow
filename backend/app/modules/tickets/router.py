"""Tickets API router.

``POST /tickets`` is the report. It is open to a session and, while
``tickets.publicEnabled`` is on, to a person without one behind ALTCHA. The body cap,
the rate limit and ALTCHA run as dependencies in the order of ``POST /applications``.
The answer is the ticket number only.

``/tickets/mine`` is the view of a reporter account on its own tickets: any session
reads it, without a permission. The reporter reads the report, the ``public`` notes and
the status changes, and writes, edits and deletes its own messages; a write needs a
session cookie or a token with the scope ``tickets:write``. A ticket of somebody else
gives 404. These routes stand before ``/tickets/{ticket_id}``, so ``mine`` never parses
as an id.

Every other route needs ``ticket.manage`` (401/403 on a collection route). An
unknown ticket or note gives 404.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status

from app.deps import DbSession, Principal, SettingsDep, get_current_principal, require_principal
from app.modules.admin.site_config_service import active_branding
from app.modules.files.service import FilesService
from app.modules.notifications.mentions import notify_ticket_mentions
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.notifications.tickets import (
    notify_ticket_created,
    notify_ticket_note,
    notify_ticket_received,
)
from app.modules.tickets.access import TICKET_MANAGE
from app.modules.tickets.schemas import (
    NoteBody,
    NoteCreate,
    NotePatch,
    ReporterNoteCreate,
    ReporterTicketDetail,
    ReporterTicketItem,
    TicketBlockedSender,
    TicketCounts,
    TicketCreate,
    TicketCreated,
    TicketDetail,
    TicketKind,
    TicketListItem,
    TicketNoteOut,
    TicketPatch,
    TicketStatus,
)
from app.modules.tickets.service import (
    AssigneeFilter,
    SwallowedReport,
    TicketService,
    format_number,
    principal_id_of,
)
from app.modules.todos.hooks import TicketTodoBridge
from app.modules.todos.live import todo_broker
from app.settings import Settings
from app.shared.antiabuse import (
    enforce_ticket_payload_limit,
    rate_limit_ticket_messages,
    rate_limit_tickets,
    verify_altcha_unless_authenticated,
)
from app.shared.errors import ForbiddenError, ProblemDetail, ValidationProblem
from app.shared.paging import Page, PageParams
from app.shared.people import PersonRef

router = APIRouter(tags=["tickets"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


Manager = Annotated[Principal, Depends(require_principal(TICKET_MANAGE))]
Reader = Annotated[Principal, Depends(require_principal())]


def require_reporter_write(principal: Reader) -> Principal:
    """Let a reporter write with a session cookie or a token with ``tickets:write``.

    Raises:
        ForbiddenError: A token without the scope ``tickets:write`` (HTTP 403).
    """
    if not principal.scope_allows(TICKET_MANAGE):
        raise ForbiddenError("The token scope does not allow ticket messages.")
    return principal


ReporterWriter = Annotated[Principal, Depends(require_reporter_write)]


def get_ticket_service(session: DbSession, request: Request) -> TicketService:
    """Wire the service with the object storage and the to-do hooks.

    The storage removes the objects of the files of a deleted note. The hooks publish
    the board pings of ``completeTodos`` on the broker of the app.
    """
    storage = getattr(request.app.state, "object_storage", None)
    return TicketService(
        session,
        files=FilesService(session, storage=storage),
        todos=TicketTodoBridge(session, broker=todo_broker(request.app.state)),
    )


ServiceDep = Annotated[TicketService, Depends(get_ticket_service)]

#: Sends the two mails of a new ticket after the commit (background task).
TicketMailSender = Callable[[Settings, UUID, object], Awaitable[None]]


async def _deliver_ticket_mails(settings: Settings, ticket_id: UUID, pool: object) -> None:
    queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
    await notify_ticket_received(queue=queue, settings=settings, ticket_id=ticket_id)
    await notify_ticket_created(queue=queue, settings=settings, ticket_id=ticket_id)


def get_ticket_mail_sender() -> TicketMailSender:
    """Return the injectable mail sender that a test can override."""
    return _deliver_ticket_mails


#: Sends the mail of a new public message after the commit (background task).
NoteMailSender = Callable[[Settings, UUID, object], Awaitable[None]]


async def _deliver_note_mail(settings: Settings, note_id: UUID, pool: object) -> None:
    queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
    await notify_ticket_note(queue=queue, settings=settings, note_id=note_id)


def get_note_mail_sender() -> NoteMailSender:
    """Return the injectable mail sender of a message that a test can override."""
    return _deliver_note_mail


NoteMails = Annotated[NoteMailSender, Depends(get_note_mail_sender)]

#: Sends ``ticket_mentioned`` to the new mentions of a note (background task).
MentionMailSender = Callable[[Settings, UUID, list[UUID], object], Awaitable[None]]


async def _deliver_mention_mails(
    settings: Settings, note_id: UUID, recipients: list[UUID], pool: object
) -> None:
    queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
    await notify_ticket_mentions(
        queue=queue, settings=settings, note_id=note_id, recipients=recipients
    )


def get_mention_mail_sender() -> MentionMailSender:
    """Return the injectable mention-mail sender that a test can override."""
    return _deliver_mention_mails


MentionMails = Annotated[MentionMailSender, Depends(get_mention_mail_sender)]


def _queue_mention_mails(
    background: BackgroundTasks,
    send: MentionMailSender,
    settings: Settings,
    request: Request,
    note_id: UUID,
    added: Sequence[UUID],
) -> None:
    """Queue the mention mails of the mentions that a write added; none, no task."""
    if added:
        pool = getattr(request.app.state, "arq_pool", None)
        background.add_task(send, settings, note_id, list(added), pool)


async def require_public_or_session(
    db: DbSession,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
) -> None:
    """Refuse a report without a session while ``tickets.publicEnabled`` is off.

    Raises:
        ForbiddenError: No session and public reports are off (HTTP 403,
            ``tickets_public_disabled``).
    """
    if principal is not None:
        return
    if not (await active_branding(db)).tickets.public_enabled:
        raise ForbiddenError(
            "Reports without a login are switched off.", code="tickets_public_disabled"
        )


@router.post(
    "/tickets",
    response_model=TicketCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(enforce_ticket_payload_limit),
        Depends(rate_limit_tickets),
        Depends(require_public_or_session),
        Depends(verify_altcha_unless_authenticated),
    ],
    responses=_errors(400, 403, 413, 422, 429),
)
async def create_ticket(
    payload: TicketCreate,
    service: ServiceDep,
    db: DbSession,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    send_mails: Annotated[TicketMailSender, Depends(get_ticket_mail_sender)],
) -> TicketCreated:
    """Report a problem, a question or an idea.

    ALTCHA applies to a report without a session only. Errors: 400 invalid ALTCHA, 403
    public reports off, 413 body too large, 422 validation (missing email, bad drafts),
    429 rate limit.

    With a session the account is the reporter and ``email`` is ignored. Without
    one, ``email`` is required (422). ``attachmentIds`` and ``draftToken`` bind the
    draft uploads of ``POST /apply/attachments``. After the commit the reporter gets
    the confirmation ``ticket_received`` and the team the mail ``ticket_created``.

    A report of a blocked sender gets the same answer with a fresh number, but
    nothing is stored and no mail goes out.
    """
    reporter_id = await principal_id_of(db, principal.sub) if principal is not None else None
    email = str(payload.email) if payload.email is not None else None
    if reporter_id is None and email is None:
        raise ValidationProblem(
            "An e-mail address is required without a login.",
            errors=[{"field": "email", "msg": "required without a login"}],
        )
    ticket = await service.create(
        payload, reporter_id=reporter_id, email=email, pepper=settings.magic_link_secret
    )
    if not isinstance(ticket, SwallowedReport):
        pool = getattr(request.app.state, "arq_pool", None)
        background.add_task(send_mails, settings, ticket.id, pool)
    return TicketCreated(number=format_number(ticket.number))


@router.get(
    "/tickets/mine",
    response_model=Page[ReporterTicketItem],
    responses=_errors(401, 422),
)
async def list_my_tickets(
    service: ServiceDep,
    db: DbSession,
    principal: Reader,
    page: Annotated[PageParams, Depends()],
    statuses: Annotated[list[TicketStatus] | None, Query(alias="status")] = None,
    kinds: Annotated[list[TicketKind] | None, Query(alias="kind")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[ReporterTicketItem]:
    """List the tickets that the caller reported, newest first.

    ``status`` and ``kind`` repeat; ``q`` matches title, body and number. A session
    without an account row gets an empty page.
    """
    me = await principal_id_of(db, principal.sub)
    if me is None:
        return Page[ReporterTicketItem](items=[], total=0, limit=page.limit, offset=page.offset)
    return await service.reporter_list(
        me,
        statuses=statuses or (),
        kinds=kinds or (),
        q=q,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/tickets/mine/{ticket_id}",
    response_model=ReporterTicketDetail,
    responses=_errors(401, 404),
)
async def get_my_ticket(
    ticket_id: UUID, service: ServiceDep, principal: Reader
) -> ReporterTicketDetail:
    """The own ticket: the report, its files, the public notes and the status changes."""
    return await service.reporter_detail(ticket_id, principal)


@router.post(
    "/tickets/mine/{ticket_id}/notes",
    response_model=TicketNoteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_ticket_messages)],
    responses=_errors(401, 403, 404, 422, 429),
)
async def add_my_ticket_note(
    ticket_id: UUID,
    payload: ReporterNoteCreate,
    service: ServiceDep,
    principal: ReporterWriter,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    send_mail: NoteMails,
) -> TicketNoteOut:
    """Write a message on an own ticket. It is public. A block gives 403 ``sender_blocked``.

    After the commit the team gets the mail ``ticket_message``.
    """
    note = await service.reporter_add_note(
        ticket_id, payload, principal, pepper=settings.magic_link_secret
    )
    background.add_task(send_mail, settings, note.id, getattr(request.app.state, "arq_pool", None))
    return note


@router.patch(
    "/tickets/mine/{ticket_id}/notes/{note_id}",
    response_model=TicketNoteOut,
    responses=_errors(401, 403, 404, 422),
)
async def edit_my_ticket_note(
    ticket_id: UUID,
    note_id: UUID,
    payload: NoteBody,
    service: ServiceDep,
    principal: ReporterWriter,
) -> TicketNoteOut:
    """Change an own message. Another author gives 403 ``not_note_author``."""
    return await service.reporter_edit_note(ticket_id, note_id, payload.body, principal)


@router.delete(
    "/tickets/mine/{ticket_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(401, 403, 404),
)
async def delete_my_ticket_note(
    ticket_id: UUID, note_id: UUID, service: ServiceDep, principal: ReporterWriter
) -> Response:
    """Delete an own message and its files. Another author gives 403 ``not_note_author``."""
    await service.reporter_delete_note(ticket_id, note_id, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _assignee_filter(raw: str | None) -> AssigneeFilter | None:
    if raw is None or raw in ("me", "none"):
        return raw
    try:
        return UUID(raw)
    except ValueError as exc:
        raise ValidationProblem(
            "assignee is a UUID, 'me' or 'none'.",
            errors=[{"field": "assignee", "msg": "not a UUID, 'me' or 'none'"}],
        ) from exc


@router.get(
    "/tickets",
    response_model=Page[TicketListItem],
    responses=_errors(401, 403, 422),
)
async def list_tickets(
    service: ServiceDep,
    db: DbSession,
    principal: Manager,
    page: Annotated[PageParams, Depends()],
    statuses: Annotated[list[TicketStatus] | None, Query(alias="status")] = None,
    kinds: Annotated[list[TicketKind] | None, Query(alias="kind")] = None,
    assignee: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[TicketListItem]:
    """List the tickets, newest first.

    ``status`` and ``kind`` repeat. ``assignee`` is a principal id, ``me`` or
    ``none``. ``q`` matches title, body, number, and the reporter name and e-mail.
    """
    wanted = _assignee_filter(assignee)
    me = await principal_id_of(db, principal.sub) if wanted == "me" else None
    return await service.list(
        statuses=statuses or (),
        kinds=kinds or (),
        assignee=wanted,
        me=me,
        q=q,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/tickets/counts", response_model=TicketCounts, responses=_errors(401, 403))
async def ticket_counts(service: ServiceDep, _principal: Manager) -> TicketCounts:
    """Count the tickets per status (``new`` feeds the badge of the rail)."""
    return await service.counts()


@router.get("/tickets/assignees", response_model=list[PersonRef], responses=_errors(401, 403))
async def ticket_assignees(service: ServiceDep, _principal: Manager) -> list[PersonRef]:
    """List the possible assignees: the active holders of ``ticket.manage``, by name."""
    return await service.assignees()


@router.get(
    "/tickets/blocked-senders",
    response_model=list[TicketBlockedSender],
    responses=_errors(401, 403),
)
async def blocked_senders(service: ServiceDep, _principal: Manager) -> list[TicketBlockedSender]:
    """List the blocked senders, newest first."""
    return await service.blocked_senders()


@router.delete(
    "/tickets/blocked-senders/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(401, 403, 404),
)
async def delete_blocked_sender(
    block_id: UUID, service: ServiceDep, _principal: Manager
) -> Response:
    """Lift one block. An unknown block gives 404."""
    await service.delete_block(block_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tickets/{ticket_id}", response_model=TicketDetail, responses=_errors(401, 403, 404))
async def get_ticket(ticket_id: UUID, service: ServiceDep, principal: Manager) -> TicketDetail:
    """The whole ticket: body, context, attachments, notes and events."""
    return await service.detail(ticket_id, principal)


@router.patch(
    "/tickets/{ticket_id}", response_model=TicketDetail, responses=_errors(401, 403, 404, 422)
)
async def patch_ticket(
    ticket_id: UUID, payload: TicketPatch, service: ServiceDep, principal: Manager
) -> TicketDetail:
    """Change the status, the assignee (``null`` unassigns) or the kind.

    ``duplicateOfId`` goes with ``status: rejected``; ``completeTodos`` with ``done``
    or ``rejected``. A foreign assignee gives 422 ``assignee_not_allowed``, a bad
    duplicate 422 ``duplicate_invalid``.
    """
    return await service.patch(ticket_id, payload, principal)


@router.post(
    "/tickets/{ticket_id}/block-sender",
    response_model=TicketDetail,
    responses=_errors(401, 403, 404, 409, 422),
)
async def block_sender(ticket_id: UUID, service: ServiceDep, principal: Manager) -> TicketDetail:
    """Block the reporter of the ticket: the account, or the e-mail of a report without one.

    A second block changes nothing. An anonymized ticket gives 409
    ``ticket_sender_unknown``, the own account or address 422 ``sender_is_self``.
    """
    return await service.block_sender(ticket_id, principal)


@router.delete(
    "/tickets/{ticket_id}/block-sender",
    response_model=TicketDetail,
    responses=_errors(401, 403, 404, 409),
)
async def unblock_sender(ticket_id: UUID, service: ServiceDep, principal: Manager) -> TicketDetail:
    """Lift the block of the ticket's reporter; without a block nothing changes."""
    return await service.unblock_sender(ticket_id, principal)


@router.post(
    "/tickets/{ticket_id}/notes",
    response_model=TicketNoteOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 404, 422),
)
async def add_ticket_note(
    ticket_id: UUID,
    payload: NoteCreate,
    service: ServiceDep,
    principal: Manager,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    send_mail: NoteMails,
    send_mentions: MentionMails,
) -> TicketNoteOut:
    """Add a note. ``attachmentIds`` and ``draftToken`` bind its files.

    ``visibility`` is ``internal`` (the default) or ``public``: the reporter account
    reads a public note in ``/tickets/mine`` and gets the mail ``ticket_answer``.

    ``mentions`` names holders of ``ticket.manage`` (``GET /tickets/assignees``);
    another id gives 422 ``mention_not_member``. Each mentioned person except the
    author gets the mail ``ticket_mentioned``.

    A draft that is missing, expired, foreign or infected gives 422
    ``draft_attachments_missing``; files on an anonymized ticket 422
    ``ticket_anonymized``.
    """
    note = await service.add_note(ticket_id, payload, principal, pepper=settings.magic_link_secret)
    if note.visibility == "public":
        pool = getattr(request.app.state, "arq_pool", None)
        background.add_task(send_mail, settings, note.id, pool)
    _queue_mention_mails(
        background, send_mentions, settings, request, note.id, service.added_mentions
    )
    return note


@router.patch(
    "/tickets/{ticket_id}/notes/{note_id}",
    response_model=TicketNoteOut,
    responses=_errors(401, 403, 404, 422),
)
async def edit_ticket_note(
    ticket_id: UUID,
    note_id: UUID,
    payload: NotePatch,
    service: ServiceDep,
    principal: Manager,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    send_mentions: MentionMails,
) -> TicketNoteOut:
    """Change an own note. Another author gives 403 ``not_note_author``.

    ``mentions`` null keeps the stored mentions; a list replaces them (422
    ``mention_not_member`` as at the create). Only a person that the list adds gets
    the mail ``ticket_mentioned``.
    """
    note = await service.edit_note(
        ticket_id, note_id, payload.body, principal, mentions=payload.mentions
    )
    _queue_mention_mails(
        background, send_mentions, settings, request, note.id, service.added_mentions
    )
    return note


@router.delete(
    "/tickets/{ticket_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(401, 403, 404),
)
async def delete_ticket_note(
    ticket_id: UUID, note_id: UUID, service: ServiceDep, principal: Manager
) -> Response:
    """Delete an own note and its files. Another author gives 403 ``not_note_author``."""
    await service.delete_note(ticket_id, note_id, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
