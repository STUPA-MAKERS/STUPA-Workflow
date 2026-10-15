"""Tickets API router.

``POST /tickets`` is the report. It is open to a session and, while
``tickets.publicEnabled`` is on, to a person without one behind ALTCHA. The body cap,
the rate limit and ALTCHA run as dependencies in the order of ``POST /applications``.
The answer is the ticket number only: a reporter never reads the ticket again.

Every other route needs ``ticket.manage`` (401/403 on a collection route). An
unknown ticket or note gives 404.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status

from app.deps import DbSession, Principal, SettingsDep, get_current_principal, require_principal
from app.modules.admin.site_config_service import active_branding
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.notifications.tickets import notify_ticket_created, notify_ticket_received
from app.modules.tickets.access import TICKET_MANAGE
from app.modules.tickets.schemas import (
    NoteBody,
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
    TicketService,
    format_number,
    principal_id_of,
)
from app.settings import Settings
from app.shared.antiabuse import (
    enforce_ticket_payload_limit,
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


def get_ticket_service(session: DbSession) -> TicketService:
    """Wire the service. The todos module adds its hooks here."""
    return TicketService(session)


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
        # ALTCHA applies to a report without a session only.
        Depends(verify_altcha_unless_authenticated),
    ],
    # 400 invalid ALTCHA, 403 public reports off, 413 body too large, 422 validation
    # (missing email, bad drafts), 429 rate limit.
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

    With a session the account is the reporter and ``email`` is ignored. Without
    one, ``email`` is required (422). ``attachmentIds`` and ``draftToken`` bind the
    draft uploads of ``POST /apply/attachments``. After the commit the reporter gets
    the confirmation ``ticket_received`` and the team the mail ``ticket_created``.
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
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(send_mails, settings, ticket.id, pool)
    return TicketCreated(number=format_number(ticket.number))


def _assignee_filter(raw: str | None) -> AssigneeFilter | None:
    if raw is None or raw in ("me", "none"):
        return raw  # pyright: ignore[reportReturnType]
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
    "/tickets/{ticket_id}/notes",
    response_model=TicketNoteOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 404, 422),
)
async def add_ticket_note(
    ticket_id: UUID, payload: NoteBody, service: ServiceDep, principal: Manager
) -> TicketNoteOut:
    """Add an internal note."""
    return await service.add_note(ticket_id, payload.body, principal)


@router.patch(
    "/tickets/{ticket_id}/notes/{note_id}",
    response_model=TicketNoteOut,
    responses=_errors(401, 403, 404, 422),
)
async def edit_ticket_note(
    ticket_id: UUID,
    note_id: UUID,
    payload: NoteBody,
    service: ServiceDep,
    principal: Manager,
) -> TicketNoteOut:
    """Change an own note. Another author gives 403 ``not_note_author``."""
    return await service.edit_note(ticket_id, note_id, payload.body, principal)


@router.delete(
    "/tickets/{ticket_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(401, 403, 404),
)
async def delete_ticket_note(
    ticket_id: UUID, note_id: UUID, service: ServiceDep, principal: Manager
) -> Response:
    """Delete an own note. Another author gives 403 ``not_note_author``."""
    await service.delete_note(ticket_id, note_id, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
