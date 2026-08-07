"""Applications API router.

The create route is public and ALTCHA-guarded. The other routes accept an
applicant or a principal. They cover the detail view, the patch that writes a
new version, the timeline, the versions, the comments and the erasure request.
Only a principal reads the PII and the internal comments.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status

from app.db import get_sessionmaker
from app.deps import (
    DbSession,
    Principal,
    SettingsDep,
    get_current_principal,
    require_principal,
)
from app.modules.applications.access import (
    DELETE_PERMISSION,
    EDIT_ANY_PERMISSION,
    MANAGE_PERMISSION,
    READ_ALL_PERMISSION,
    Access,
    require_app_edit,
    require_app_read,
)
from app.modules.applications.schemas import (
    ApplicationCreate,
    ApplicationCreated,
    ApplicationListItem,
    ApplicationOut,
    ApplicationPatch,
    CommentCreate,
    CommentOut,
    CommentPatch,
    TimelineEventOut,
    VersionOut,
)
from app.modules.applications.service import ApplicationsService
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth import service as auth_service
from app.modules.forms.schemas import EffectiveFormOut
from app.modules.notifications.privacy import notify_erasure_requested
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.notifications.service import NotificationService
from app.modules.privacy.service import ErasureRequestService
from app.settings import Settings
from app.shared.antiabuse import (
    enforce_application_payload_limit,
    rate_limit_applications,
    verify_altcha_unless_authenticated,
)
from app.shared.errors import (
    ForbiddenError,
    PayloadTooLargeError,
    ProblemDetail,
    ValidationProblem,
)
from app.shared.paging import Page, PageParams

router = APIRouter(tags=["applications"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

# Anti-DoS cap for the synchronous XLSX export. The request builds the whole
# workbook in memory. A larger result set answers 413, and the user must narrow
# the filter.
EXPORT_MAX_ROWS = 10_000


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_applications_service(session: DbSession) -> ApplicationsService:
    return ApplicationsService(session)


ServiceDep = Annotated[ApplicationsService, Depends(get_applications_service)]


async def _deliver_magic_link(
    settings: Settings, email: str, application_id: UUID, pool: object
) -> None:
    """Issue and send the magic link for a new application in its own session.

    This runs as a background task after the 201 response. The scope follows the
    initial state and is ``edit``. The mail queue delivers the message. Without
    an arq pool, `NotificationService` logs the mail and drops it.
    """
    queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:

        async def deliver(recipient: str, link: str) -> None:
            await NotificationService(db, queue=queue, settings=settings).send_magic_link(
                email=recipient, link=link
            )

        await auth_service.request_magic_link(
            db, settings, email=email, application_id=application_id, deliver=deliver
        )
        await db.commit()


MagicLinkSender = Callable[[Settings, str, UUID, object], Awaitable[None]]


def get_magic_link_sender() -> MagicLinkSender:
    """Return the injectable magic-link sender that a test can override."""
    return _deliver_magic_link


@router.post(
    "/applications",
    response_model=ApplicationCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        # Body cap that answers 413. It bounds Content-Length and reads the body
        # under a cap, also for a chunked body. The authoritative check on the
        # serialized field values runs after parsing.
        Depends(enforce_application_payload_limit),
        Depends(rate_limit_applications),
        # ALTCHA applies to an anonymous submission only. A logged-in user is exempt.
        Depends(verify_altcha_unless_authenticated),
    ],
    # 400 malformed JSON or invalid ALTCHA, 413 body too large, 422 form or
    # schema validation, 429 rate limit.
    responses=_errors(400, 404, 413, 422, 429),
)
async def create_application(
    payload: ApplicationCreate,
    service: ServiceDep,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    send_magic_link: Annotated[MagicLinkSender, Depends(get_magic_link_sender)],
) -> ApplicationCreated:
    """Create an application.

    The route splits out the PII, writes version 1 and enqueues the magic-link
    mail. A logged-in user needs no ALTCHA. The route derives a missing
    ``applicantEmail`` or ``applicantName`` from the account and audits the
    ``sub`` of that account as the actor. An anonymous submission requires
    ALTCHA and ``applicantEmail``.
    """
    # Authoritative bound on the serialized field values, free of Content-Length.
    if len(json.dumps(payload.data)) > settings.max_application_payload_bytes:
        raise PayloadTooLargeError(
            f"Application data exceeds {settings.max_application_payload_bytes} bytes."
        )
    # Derive the identity. An explicit value wins over the logged-in account.
    email = (
        str(payload.applicant_email)
        if payload.applicant_email
        else (principal.email if principal else None)
    )
    if not email:
        raise ValidationProblem(
            "Applicant email required.",
            errors=[{"field": "applicantEmail", "msg": "required for anonymous submissions"}],
        )
    payload.applicant_email = email
    if not payload.applicant_name and principal:
        payload.applicant_name = principal.display_name
    actor = principal.sub if principal else "applicant"

    app, email = await service.create(payload, actor=actor)
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(send_magic_link, settings, email, app.id, pool)
    return ApplicationCreated(applicationId=app.id)


@router.get(
    "/applications/tasks",
    response_model=list[ApplicationListItem],
    responses=_errors(401, 403),
)
async def list_tasks(
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> list[ApplicationListItem]:
    """List the open tasks of the principal.

    The list holds the applications in a vote state, the applications with a
    firable transition, and the own applications in an editable state. The last
    group appears even without ``application.read``.
    """
    return await service.list_tasks(principal)


@router.get(
    "/applications",
    response_model=Page[ApplicationListItem],
    responses=_errors(401, 403),
)
async def list_applications(
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
    page: Annotated[PageParams, Depends()],
    state_id: Annotated[UUID | None, Query(alias="state")] = None,
    gremium_id: Annotated[UUID | None, Query(alias="gremium")] = None,
    type_id: Annotated[UUID | None, Query(alias="type")] = None,
    budget_pot_id: Annotated[UUID | None, Query(alias="topf")] = None,
    budget_id: Annotated[UUID | None, Query(alias="budget")] = None,
    q: Annotated[str | None, Query()] = None,
    amount_min: Annotated[Decimal | None, Query(alias="amountMin", ge=0)] = None,
    amount_max: Annotated[Decimal | None, Query(alias="amountMax", ge=0)] = None,
    created_from: Annotated[date | None, Query(alias="createdFrom")] = None,
    created_to: Annotated[date | None, Query(alias="createdTo")] = None,
    sort: Annotated[Literal["createdAt", "amount"], Query()] = "createdAt",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
    # "My applications" forces the owner filter even for a principal that holds
    # application.read. Without it, that principal would see every application.
    mine: Annotated[bool, Query()] = False,
) -> Page[ApplicationListItem]:
    """List applications with filters, sorting and paging.

    A principal without ``application.read`` and without the admin role sees the
    own applications (``created_by``) plus the committee read scope.
    ``mine=true`` forces the pure owner filter, also for an authorized reader.
    """
    can_read = (
        "admin" in principal.roles
        or principal.has("application.read")
        or principal.has(READ_ALL_PERMISSION)
    )
    restricted = not can_read and not mine
    return await service.list_applications(
        state_id=state_id,
        gremium_id=gremium_id,
        type_id=type_id,
        budget_pot_id=budget_pot_id,
        budget_id=budget_id,
        q=q,
        amount_min=amount_min,
        amount_max=amount_max,
        created_from=created_from,
        created_to=created_to,
        sort=sort,
        order=order,
        owner_sub=principal.sub if (mine or not can_read) else None,
        # The committee read scope applies to a restricted principal only.
        # "mine" stays owner-only on purpose.
        committee_sub=principal.sub if restricted else None,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/applications/export.xlsx",
    responses=_errors(401, 403, 413),
)
async def export_applications_xlsx(
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("application.export"))],
    state_id: Annotated[UUID | None, Query(alias="state")] = None,
    gremium_id: Annotated[UUID | None, Query(alias="gremium")] = None,
    type_id: Annotated[UUID | None, Query(alias="type")] = None,
    budget_pot_id: Annotated[UUID | None, Query(alias="topf")] = None,
    budget_id: Annotated[UUID | None, Query(alias="budget")] = None,
    q: Annotated[str | None, Query()] = None,
    amount_min: Annotated[Decimal | None, Query(alias="amountMin", ge=0)] = None,
    amount_max: Annotated[Decimal | None, Query(alias="amountMax", ge=0)] = None,
    created_from: Annotated[date | None, Query(alias="createdFrom")] = None,
    created_to: Annotated[date | None, Query(alias="createdTo")] = None,
    sort: Annotated[Literal["createdAt", "amount"], Query()] = "createdAt",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> Response:
    """Export the application list as ``.xlsx``.

    The filters work as in ``GET /applications``.
    """
    from app.shared.xlsx import XLSX_MEDIA_TYPE, build_applications_workbook

    page = await service.list_applications(
        state_id=state_id,
        gremium_id=gremium_id,
        type_id=type_id,
        budget_pot_id=budget_pot_id,
        budget_id=budget_id,
        q=q,
        amount_min=amount_min,
        amount_max=amount_max,
        created_from=created_from,
        created_to=created_to,
        sort=sort,
        order=order,
        # One row over the cap. This detects "more than EXPORT_MAX_ROWS" even
        # when the query does not count ``total``.
        limit=EXPORT_MAX_ROWS + 1,
        offset=0,
    )
    # A result set over the cap answers 413 instead of building a huge workbook
    # in the request. The check reads ``total`` when counted and the returned rows.
    if page.total > EXPORT_MAX_ROWS or len(page.items) > EXPORT_MAX_ROWS:
        raise PayloadTooLargeError(
            f"Export exceeds {EXPORT_MAX_ROWS} rows; please narrow the filter."
        )
    type_names, gremium_names = await service.name_maps()
    data = build_applications_workbook(
        page.items, type_names=type_names, gremium_names=gremium_names
    )
    await audit_record(
        service.session,
        actor=principal.sub,
        action=AuditAction.EXPORT,
        target_type="export",
        target_id="applications.xlsx",
        data={"rows": len(page.items)},
    )
    await service.session.commit()
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="applications.xlsx"'},
    )


@router.get(
    "/applications/{application_id}",
    response_model=ApplicationOut,
    responses=_errors(401, 403, 404),
)
async def get_application(
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_read)],
) -> ApplicationOut:
    """Read an application.

    Only a principal gets the PII and the internal view.
    """
    principal = access.principal
    return await service.get(
        access.application_id,
        include_pii=access.can_see_internal,
        requester_sub=principal.sub if principal is not None else None,
        requester_can_manage=principal.has("application.manage")
        if principal is not None
        else False,
        allow_unconfirmed=access.is_owning_applicant,
    )


@router.get(
    "/applications/{application_id}/form",
    response_model=EffectiveFormOut,
    responses=_errors(401, 403, 404),
)
async def get_application_form(
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_read)],
) -> EffectiveFormOut:
    """Return the effective form of the pinned version of the application.

    The detail view shows and edits the same field set that validates the
    answers. This holds after a later form change.
    """
    return await service.effective_form(
        access.application_id, allow_unconfirmed=access.is_owning_applicant
    )


@router.patch(
    "/applications/{application_id}",
    response_model=ApplicationOut,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def patch_application(
    payload: ApplicationPatch,
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_edit)],
) -> ApplicationOut:
    """Update the application data as a new version.

    A locked state answers 409, unless the caller holds ``application.edit_any``.
    """
    bypass = access.principal is not None and access.principal.has(EDIT_ANY_PERMISSION)
    return await service.patch(
        access.application_id,
        payload.data,
        changed_by=access.actor,
        bypass_state_lock=bypass,
        allow_unconfirmed=access.is_owning_applicant,
    )


@router.delete(
    "/applications/{application_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_application(
    application_id: UUID,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal(DELETE_PERMISSION))],
) -> None:
    """Delete an application.

    The route gates on ``application.delete``. An admin holds that permission
    through the role bypass, and any other role holds it through an explicit
    grant. ``application.manage`` alone is not enough, and the creator may not
    delete either. The delete is irreversible.
    """
    await service.delete(application_id, actor=principal.sub)


@router.get(
    "/applications/{application_id}/timeline",
    response_model=list[TimelineEventOut],
    responses=_errors(401, 403, 404),
)
async def get_timeline(
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_read)],
) -> list[TimelineEventOut]:
    """Status timeline of the application."""
    return await service.timeline(
        access.application_id, allow_unconfirmed=access.is_owning_applicant
    )


@router.get(
    "/applications/{application_id}/versions",
    response_model=list[VersionOut],
    dependencies=[Depends(require_principal("application.read"))],
    responses=_errors(401, 403, 404),
)
async def get_versions(
    application_id: UUID,
    service: ServiceDep,
) -> list[VersionOut]:
    """Return the version history and the diff.

    Only a principal may read this route.
    """
    # This route serves a principal only. An unconfirmed guest submission stays
    # invisible and answers 404, like the list.
    return await service.versions(application_id, allow_unconfirmed=False)


async def _deliver_comment_mails(
    settings: Settings,
    application_id: UUID,
    comment_id: UUID,
    author_kind: str,
    visibility: str,
    body: str,
    author_name: str | None,
    pool: object,
) -> None:
    """Send the comment mails in an own session, in the background after the 201."""
    from app.modules.notifications.comments import send_comment_notifications

    queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        await send_comment_notifications(
            db,
            queue=queue,
            settings=settings,
            application_id=application_id,
            comment_id=comment_id,
            author_kind=author_kind,
            visibility=visibility,
            body=body,
            author_name=author_name,
        )


CommentMailSender = Callable[
    [Settings, UUID, UUID, str, str, str, str | None, object], Awaitable[None]
]


def get_comment_mail_sender() -> CommentMailSender:
    """Return the injectable comment-mail sender that a test can override."""
    return _deliver_comment_mails


@router.post(
    "/applications/{application_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(400, 401, 403, 404, 422),
)
async def add_comment(
    payload: CommentCreate,
    service: ServiceDep,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    send_comment_mails: Annotated[CommentMailSender, Depends(get_comment_mail_sender)],
    # ``require_app_read`` on purpose, because the view scope is enough. A
    # comment is communication, not a data change. An applicant still posts
    # a public question while the state is locked to view-only.
    access: Annotated[Access, Depends(require_app_read)],
) -> CommentOut:
    """Add a comment.

    An applicant may post a ``public`` comment only. An internal comment from an
    applicant answers 403.

    The route triggers comment mails. A public principal comment goes to the
    applicant. An applicant comment goes to everybody who can act on the current
    state.
    """
    if payload.visibility == "internal" and not access.can_see_internal:
        raise ForbiddenError("Applicants may only post public comments.")
    author = access.principal.sub if access.principal is not None else None
    comment = await service.add_comment(
        access.application_id,
        author=author,
        author_kind=access.author_kind,
        body=payload.body,
        visibility=payload.visibility,
        allow_unconfirmed=access.is_owning_applicant,
    )
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(
        send_comment_mails,
        settings,
        access.application_id,
        comment.id,
        access.author_kind,
        payload.visibility,
        payload.body,
        comment.author,  # resolved display name for the mail bubble
        pool,
    )
    return comment


@router.get(
    "/applications/{application_id}/comments",
    response_model=list[CommentOut],
    responses=_errors(401, 403, 404),
)
async def list_comments(
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_read)],
) -> list[CommentOut]:
    """List the comments.

    An applicant sees the ``public`` comments only.
    """
    return await service.list_comments(
        access.application_id,
        include_internal=access.can_see_internal,
        allow_unconfirmed=access.is_owning_applicant,
        viewer_sub=access.principal.sub if access.principal is not None else None,
        viewer_is_applicant=access.is_owning_applicant,
    )


@router.patch(
    "/applications/{application_id}/comments/{comment_id}",
    response_model=CommentOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_comment(
    comment_id: UUID,
    payload: CommentPatch,
    service: ServiceDep,
    # ``require_app_read`` like the create: a comment is communication, not a
    # data change. The per-comment author check runs in the service.
    access: Annotated[Access, Depends(require_app_read)],
) -> CommentOut:
    """Replace the body of a comment.

    Only the AUTHOR of the comment or a principal with ``application.manage``
    may do this. The author comes from the session, never from the body. A
    comment keeps no version history, so the new text replaces the old one and
    the audit log records the change.
    """
    return await service.update_comment(
        access.application_id,
        comment_id,
        body=payload.body,
        actor=access.actor,
        viewer_sub=access.principal.sub if access.principal is not None else None,
        viewer_is_applicant=access.is_owning_applicant,
        can_manage=access.principal is not None
        and access.principal.has(MANAGE_PERMISSION),
        allow_unconfirmed=access.is_owning_applicant,
    )


@router.delete(
    "/applications/{application_id}/comments/{comment_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_comment(
    comment_id: UUID,
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_read)],
) -> None:
    """Delete a comment.

    Only the AUTHOR of the comment or a principal with ``application.manage``
    may do this. The delete is final and the audit log records it. Before this
    route existed, a comment posted with the wrong visibility could only be
    removed by anonymizing the whole application.
    """
    await service.delete_comment(
        access.application_id,
        comment_id,
        actor=access.actor,
        viewer_sub=access.principal.sub if access.principal is not None else None,
        viewer_is_applicant=access.is_owning_applicant,
        can_manage=access.principal is not None
        and access.principal.has(MANAGE_PERMISSION),
        allow_unconfirmed=access.is_owning_applicant,
    )


@router.post(
    "/applications/{application_id}/erasure-request",
    status_code=202,
    responses=_errors(401, 403, 404),
)
async def request_erasure(
    application_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    # GDPR Art. 17: every identity that may read the application may request the
    # erasure of the PII. This covers the magic-link applicant, the creator and
    # an authorized principal.
    access: Annotated[Access, Depends(require_app_read)],
) -> Response:
    """File an erasure request (GDPR Art. 17) into the ``/admin/privacy`` queue.

    The route notifies the privacy officers.
    """
    result = await ErasureRequestService(session).create(
        subject_type="applicant",
        application_id=access.application_id,
        requested_by=access.actor,
    )
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(
        notify_erasure_requested,
        queue=mail_queue_from_pool(pool),
        settings=settings,
        request_id=result.id,
        subject_type="applicant",
    )
    return Response(status_code=202)
