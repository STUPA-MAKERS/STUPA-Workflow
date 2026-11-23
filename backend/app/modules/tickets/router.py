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

Every other route of ``/tickets`` is the work of the team. It needs the work right
in at least one Bereich: the global permission ``ticket.manage``, or the gremium
permission ``ticket.work`` in the Gremium of a Bereich (403 without one). A ticket of
a Bereich in which the caller does not work gives 404, like an unknown ticket. The
sender blocks hold back a person in every Bereich, so their routes need
``ticket.manage``.

``GET /tickets/report-areas`` lists the Bereiche that a signed-in person can choose
in the ticket dialog. ``POST /tickets/manual`` is the ticket that a person of the team
writes by hand.

``/admin/ticket-areas`` is the list of the Bereiche of the admin page "Hilfe &
Tickets" behind ``admin.site``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status

from app.deps import DbSession, Principal, SettingsDep, get_current_principal, require_principal
from app.modules.auth.people import PersonRef
from app.modules.files.service import FilesService
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.site_config.reads import active_branding
from app.modules.tickets.access import TICKET_MANAGE, AreaScope, area_scope, works_anywhere
from app.modules.tickets.areas import TicketAreaService
from app.modules.tickets.mails import (
    notify_ticket_assigned,
    notify_ticket_created,
    notify_ticket_note,
    notify_ticket_received,
)
from app.modules.tickets.mention_mails import notify_ticket_mentions
from app.modules.tickets.schemas import (
    NoteBody,
    NoteCreate,
    NotePatch,
    ReporterNoteCreate,
    ReporterTicketDetail,
    ReporterTicketItem,
    TicketAreaChoice,
    TicketAreaCreate,
    TicketAreaOut,
    TicketAreaPatch,
    TicketBlockedSender,
    TicketCounts,
    TicketCreate,
    TicketCreated,
    TicketDetail,
    TicketFollowUp,
    TicketKind,
    TicketListItem,
    TicketManualCreate,
    TicketNoteOut,
    TicketPatch,
    TicketRef,
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
from app.shared.errors import ForbiddenError, NotFoundError, ProblemDetail, ValidationProblem
from app.shared.paging import Page, PageParams

router = APIRouter(tags=["tickets"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return dict.fromkeys(codes, _PROBLEM)


Manager = Annotated[Principal, Depends(require_principal(TICKET_MANAGE))]
Reader = Annotated[Principal, Depends(require_principal())]
SiteAdmin = Annotated[Principal, Depends(require_principal("admin.site"))]


@dataclass(frozen=True, slots=True)
class TicketWorker:
    """A caller with the work right in at least one Bereich.

    ``areas`` holds the Bereiche of the caller; None stands for every Bereich.
    """

    principal: Principal
    areas: AreaScope


async def require_worker(principal: Reader, db: DbSession) -> TicketWorker:
    """Let a person with the work right in at least one Bereich pass.

    Raises:
        ForbiddenError: Neither ``ticket.manage`` nor ``ticket.work`` in the Gremium
            of a Bereich (HTTP 403).
    """
    areas = await area_scope(db, principal)
    if not works_anywhere(areas):
        raise ForbiddenError("The work on tickets needs the work right in a Bereich.")
    return TicketWorker(principal=principal, areas=areas)


Worker = Annotated[TicketWorker, Depends(require_worker)]


def require_reporter_write(principal: Reader) -> Principal:
    """Let a reporter write with a session cookie or a token with ``tickets:write``.

    Raises:
        ForbiddenError: A token without the scope ``tickets:write`` (HTTP 403).
    """
    if not principal.scope_allows(TICKET_MANAGE):
        raise ForbiddenError("The token scope does not allow ticket messages.")
    return principal


ReporterWriter = Annotated[Principal, Depends(require_reporter_write)]


def get_area_service(session: DbSession) -> TicketAreaService:
    """Wire the service of the Bereiche."""
    return TicketAreaService(session)


AreaServiceDep = Annotated[TicketAreaService, Depends(get_area_service)]


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

#: Sends ``ticket_assigned`` to the new assignee of a ticket (background task).
AssignedMailSender = Callable[[Settings, UUID, object], Awaitable[None]]


async def _deliver_assigned_mail(settings: Settings, ticket_id: UUID, pool: object) -> None:
    queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
    await notify_ticket_assigned(queue=queue, settings=settings, ticket_id=ticket_id)


def get_assigned_mail_sender() -> AssignedMailSender:
    """Return the injectable mail sender of an assignment that a test can override."""
    return _deliver_assigned_mail


AssignedMails = Annotated[AssignedMailSender, Depends(get_assigned_mail_sender)]

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
    db: DbSession, principal: Principal | None, kind: TicketKind | None
) -> None:
    """Refuse a report without a session while ``tickets.publicEnabled`` is off.

    A barrier report (``kind == "barrier"``) always passes: it is the feedback route
    of the accessibility statement, which the law requires without a login
    (spec 000497).

    Raises:
        ForbiddenError: No session, not a barrier report and public reports are off
            (HTTP 403, ``tickets_public_disabled``).
    """
    if principal is not None or kind == "barrier":
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
    """Report a problem, a question, an idea or an accessibility barrier.

    ALTCHA applies to a report without a session only. Errors: 400 invalid ALTCHA, 403
    public reports off (never for a barrier report), 413 body too large, 422 validation
    (missing email, bad drafts), 429 rate limit.

    With a session the account is the reporter and ``email`` is ignored. Without
    one, ``email`` is required (422). ``attachmentIds`` and ``draftToken`` bind the
    draft uploads of ``POST /apply/attachments``. After the commit the reporter gets
    the confirmation ``ticket_received`` and the team the mail ``ticket_created``.

    A report of a blocked sender gets the same answer with a fresh number, but
    nothing is stored and no mail goes out.

    ``areaId`` sends the report to a Bereich of ``GET /tickets/report-areas``, with
    ``categoryId`` in place of ``kind``. Without a session only ``Plattform`` takes a
    report (403 ``ticket_area_needs_session``); a Bereich without the switch "In der
    App erreichbar" gives 403 ``ticket_area_not_reachable``.
    """
    await require_public_or_session(db, principal, payload.kind)
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
    response_model=TicketNoteOut | TicketFollowUp,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_ticket_messages)],
    responses=_errors(401, 403, 404, 422, 429),
)
async def add_my_ticket_note(
    ticket_id: UUID,
    payload: ReporterNoteCreate,
    service: ServiceDep,
    db: DbSession,
    principal: ReporterWriter,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    send_mail: NoteMails,
    send_ticket_mails: Annotated[TicketMailSender, Depends(get_ticket_mail_sender)],
) -> TicketNoteOut | TicketFollowUp:
    """Write a message on an own ticket. It is public. A block gives 403 ``sender_blocked``.

    After the commit the team gets the mail ``ticket_message``. A message on a ticket
    with the status ``waiting``, ``done`` or ``rejected`` sets ``in_progress``.

    A message on a ticket that is closed for more than 14 days (``replyOpensNew`` of
    the detail) becomes a new ticket in the same Bereich. The answer then is
    ``{ followUp: { id, number } }`` and the mails are those of a new ticket.
    """
    pool = getattr(request.app.state, "arq_pool", None)
    follow_up = await service.reporter_follow_up(
        ticket_id, payload, principal, pepper=settings.magic_link_secret
    )
    if follow_up is not None:
        await db.commit()
        background.add_task(send_ticket_mails, settings, follow_up.id, pool)
        return TicketFollowUp(
            follow_up=TicketRef(id=follow_up.id, number=format_number(follow_up.number))
        )
    note = await service.reporter_add_note(
        ticket_id, payload, principal, pepper=settings.magic_link_secret
    )
    background.add_task(send_mail, settings, note.id, pool)
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
    worker: Worker,
    page: Annotated[PageParams, Depends()],
    statuses: Annotated[list[TicketStatus] | None, Query(alias="status")] = None,
    kinds: Annotated[list[TicketKind] | None, Query(alias="kind")] = None,
    area_ids: Annotated[list[UUID] | None, Query(alias="area")] = None,
    assignee: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[TicketListItem]:
    """List the tickets of the Bereiche of the caller, newest first.

    ``status``, ``kind`` and ``area`` repeat. ``assignee`` is a principal id, ``me``
    or ``none``. ``q`` matches title, body, number, and the reporter name and e-mail.
    """
    wanted = _assignee_filter(assignee)
    me = await principal_id_of(db, worker.principal.sub) if wanted == "me" else None
    return await service.list(
        areas=worker.areas,
        area_ids=area_ids or (),
        statuses=statuses or (),
        kinds=kinds or (),
        assignee=wanted,
        me=me,
        q=q,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/tickets/counts", response_model=TicketCounts, responses=_errors(401, 403))
async def ticket_counts(service: ServiceDep, worker: Worker) -> TicketCounts:
    """Count the tickets of the Bereiche of the caller per status.

    ``new`` feeds the badge of the rail.
    """
    return await service.counts(areas=worker.areas)


@router.get(
    "/tickets/assignees", response_model=list[PersonRef], responses=_errors(401, 403, 404, 422)
)
async def ticket_assignees(
    service: ServiceDep,
    worker: Worker,
    area: Annotated[UUID | None, Query()] = None,
) -> list[PersonRef]:
    """List the active persons with the work right, by name.

    With ``area`` the list holds the possible assignees of that Bereich; a Bereich in
    which the caller does not work gives 404. Without it the list holds the persons
    of every Bereich of the caller, for the assignee filter.
    """
    if area is not None and worker.areas is not None and area not in worker.areas:
        raise NotFoundError(f"ticket area {area} not found")
    return await service.assignees(frozenset({area}) if area is not None else worker.areas)


@router.get("/tickets/areas", response_model=list[TicketAreaOut], responses=_errors(401, 403))
async def ticket_areas(areas: AreaServiceDep, worker: Worker) -> list[TicketAreaOut]:
    """List every Bereich with its Kategorien, ``Plattform`` first, then by name.

    ``mine`` marks the Bereiche in which the caller works. The other Bereiche are in
    the list, because a ticket can move to each Bereich.
    """
    return await areas.listing(worker.areas)


@router.get("/tickets/report-areas", response_model=list[TicketAreaChoice], responses=_errors(401))
async def ticket_report_areas(areas: AreaServiceDep, _principal: Reader) -> list[TicketAreaChoice]:
    """List the Bereiche that a signed-in person can choose in the ticket dialog.

    These are ``Plattform`` and each Bereich with the switch "In der App erreichbar".
    """
    return await areas.choices()


@router.post(
    "/tickets/manual",
    response_model=TicketDetail,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 404, 422),
)
async def create_manual_ticket(
    payload: TicketManualCreate,
    service: ServiceDep,
    db: DbSession,
    worker: Worker,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    send_mail: NoteMails,
) -> TicketDetail:
    """Create a ticket by hand for an account or for an e-mail address.

    The caller needs the work right in the Bereich ``areaId`` (403). Exactly one of
    ``reporterId`` and ``email`` names the person (422 ``ticket_reporter_invalid``).
    ``body`` is the note of the team; the person does not read it. ``message`` is the
    first public message: the account reads it in the tab "Tickets" and gets the mail
    ``ticket_answer``. A ticket for an address needs a Postfach of the Bereich, else
    422 ``ticket_area_without_mailbox``.
    """
    ticket, note = await service.create_manual(payload, worker.principal, areas=worker.areas)
    await db.commit()
    if note is not None:
        pool = getattr(request.app.state, "arq_pool", None)
        background.add_task(send_mail, settings, note.id, pool)
    return await service.detail(ticket.id, worker.principal, areas=worker.areas)


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
async def get_ticket(ticket_id: UUID, service: ServiceDep, worker: Worker) -> TicketDetail:
    """The whole ticket: body, context, attachments, notes and events."""
    return await service.detail(ticket_id, worker.principal, areas=worker.areas)


@router.patch(
    "/tickets/{ticket_id}", response_model=TicketDetail, responses=_errors(401, 403, 404, 422)
)
async def patch_ticket(
    ticket_id: UUID,
    payload: TicketPatch,
    service: ServiceDep,
    worker: Worker,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    send_assigned: AssignedMails,
) -> TicketDetail:
    """Change the status, the assignee (``null`` unassigns), the Kategorie or the Bereich.

    ``duplicateOfId`` goes with ``status: rejected``; ``completeTodos`` with ``done``
    or ``rejected``. An assignee without the work right in the Bereich gives 422
    ``assignee_not_allowed``, a bad duplicate 422 ``duplicate_invalid``.

    ``kind`` is the Kategorie of a ticket of ``Plattform``. ``categoryId`` is the
    Kategorie of a ticket of another Bereich (``null`` clears it); a Kategorie of a
    different Bereich gives 422 ``category_invalid``. ``areaId`` moves the ticket to
    another Bereich (``GET /tickets/areas``), also to one in which the caller does not
    work: the move clears the Kategorie, and the assignee without the work right
    there. An unknown Bereich gives 422 ``area_invalid``.

    A new assignee who did not assign the ticket to the own account gets the mail
    ``ticket_assigned``.
    """
    detail = await service.patch(ticket_id, payload, worker.principal, areas=worker.areas)
    if payload.assignee_id is not None:
        pool = getattr(request.app.state, "arq_pool", None)
        background.add_task(send_assigned, settings, ticket_id, pool)
    return detail


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
    worker: Worker,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    send_mail: NoteMails,
    send_mentions: MentionMails,
) -> TicketNoteOut:
    """Add a note. ``attachmentIds`` and ``draftToken`` bind its files.

    ``visibility`` is ``internal`` (the default) or ``public``: the reporter account
    reads a public note in ``/tickets/mine`` and gets the mail ``ticket_answer``.

    ``mentions`` names persons with the work right in the Bereich of the ticket
    (``GET /tickets/assignees?area=``); another id gives 422 ``mention_not_member``.
    Each mentioned person except the
    author gets the mail ``ticket_mentioned``.

    A draft that is missing, expired, foreign or infected gives 422
    ``draft_attachments_missing``; files on an anonymized ticket 422
    ``ticket_anonymized``.
    """
    note = await service.add_note(
        ticket_id,
        payload,
        worker.principal,
        pepper=settings.magic_link_secret,
        areas=worker.areas,
    )
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
    worker: Worker,
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
        ticket_id,
        note_id,
        payload.body,
        worker.principal,
        mentions=payload.mentions,
        areas=worker.areas,
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
    ticket_id: UUID, note_id: UUID, service: ServiceDep, worker: Worker
) -> Response:
    """Delete an own note and its files. Another author gives 403 ``not_note_author``."""
    await service.delete_note(ticket_id, note_id, worker.principal, areas=worker.areas)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/admin/ticket-areas", response_model=list[TicketAreaOut], responses=_errors(401, 403))
async def admin_ticket_areas(areas: AreaServiceDep, _principal: SiteAdmin) -> list[TicketAreaOut]:
    """List the Bereiche with their settings and Kategorien, ``Plattform`` first."""
    return await areas.listing()


@router.post(
    "/admin/ticket-areas",
    response_model=TicketAreaOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 409, 422),
)
async def create_ticket_area(
    payload: TicketAreaCreate, areas: AreaServiceDep, principal: SiteAdmin
) -> TicketAreaOut:
    """Create a Bereich with at most one Gremium and its Kategorien.

    A used name gives 409 ``ticket_area_name_taken``, an unknown Gremium 422, and a
    blank or duplicate Kategorie 422 ``ticket_categories_invalid``.
    """
    area = await areas.create(payload, principal.sub)
    await areas.session.commit()
    return area


@router.patch(
    "/admin/ticket-areas/{area_id}",
    response_model=TicketAreaOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def patch_ticket_area(
    area_id: UUID, payload: TicketAreaPatch, areas: AreaServiceDep, principal: SiteAdmin
) -> TicketAreaOut:
    """Change the name, the Gremium, the switch ``notifyNew`` or the Kategorien.

    ``categories`` is the whole ordered list: an entry with ``id`` keeps a stored
    Kategorie, an entry without one adds a Kategorie, and a stored Kategorie that the
    list leaves out is deleted. The Bereich ``Plattform`` takes ``notifyNew`` only;
    another field gives 409 ``ticket_area_platform_fixed``.
    """
    area = await areas.patch(area_id, payload, principal.sub)
    await areas.session.commit()
    return area


@router.delete(
    "/admin/ticket-areas/{area_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(401, 403, 404, 409),
)
async def delete_ticket_area(
    area_id: UUID, areas: AreaServiceDep, principal: SiteAdmin
) -> Response:
    """Delete a Bereich without tickets.

    A Bereich with a ticket gives 409 ``ticket_area_has_tickets``, the Bereich
    ``Plattform`` 409 ``ticket_area_platform_fixed``.
    """
    await areas.delete(area_id, principal.sub)
    await areas.session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
