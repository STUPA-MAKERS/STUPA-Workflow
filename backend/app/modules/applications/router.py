"""applications-API-Router (T-12, api.md §3 »applications«).

Endpunkte:

* ``POST   /api/applications``                  — öffentlich (+Altcha-Reserve); Antrag
  anlegen → Magic-Link-Mail (Hintergrund, scope=edit).
* ``GET    /api/applications``                  — Principal (``application.read``);
  gefilterte, gepagte Liste.
* ``GET    /api/applications/{id}``             — A/P; Antrag (PII/interne Kommentare
  nur für Principals).
* ``PATCH  /api/applications/{id}``             — A(edit)/P; ``data`` → neue Version
  (gesperrter State → 409).
* ``GET    /api/applications/{id}/timeline``    — A/P; Status-Verlauf.
* ``GET    /api/applications/{id}/versions``    — Principal; Versionshistorie + Diff.
* ``POST   /api/applications/{id}/comments``    — A(public)/P; Kommentar.
* ``GET    /api/applications/{id}/comments``    — A/P; Kommentare (Applicant: nur public).

Fehler werden als ``ProblemDetail`` deklariert (T-10-Hook → problem+json).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from app.db import get_sessionmaker
from app.deps import (
    DbSession,
    Principal,
    SettingsDep,
    get_current_principal,
    require_principal,
)
from app.modules.applications.access import Access, require_app_edit, require_app_read
from app.modules.applications.schemas import (
    ApplicationCreate,
    ApplicationCreated,
    ApplicationListItem,
    ApplicationOut,
    ApplicationPatch,
    CommentCreate,
    CommentOut,
    TimelineEventOut,
    VersionOut,
)
from app.modules.applications.service import ApplicationsService
from app.modules.auth import service as auth_service
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


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_applications_service(session: DbSession) -> ApplicationsService:
    return ApplicationsService(session)


ServiceDep = Annotated[ApplicationsService, Depends(get_applications_service)]


async def _deliver_magic_link(
    settings: Settings, email: str, application_id: UUID
) -> None:
    """Magic-Link für den neuen Antrag in eigener Session ausstellen + versenden.

    Läuft als Background-Task **nach** der 201-Antwort (flows §1: ``enqueue Mail``).
    Nutzt die getestete T-10-Logik; Scope folgt dem Initial-State (edit)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        await auth_service.request_magic_link(
            db, settings, email=email, application_id=application_id
        )
        await db.commit()


MagicLinkSender = Callable[[Settings, str, UUID], Awaitable[None]]


def get_magic_link_sender() -> MagicLinkSender:
    """Injizierbarer Magic-Link-Versender (in Tests überschreibbar)."""
    return _deliver_magic_link


@router.post(
    "/applications",
    response_model=ApplicationCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        # Body-Cap (413): Content-Length-Schranke + gekapptes Lesen (auch chunked,
        # Review #3). Die maßgebliche Prüfung der serialisierten Feldwerte erfolgt
        # zusätzlich nach dem Parsen.
        Depends(enforce_application_payload_limit),
        Depends(rate_limit_applications),
        # Altcha nur für anonyme Einreichung; eingeloggte Nutzer:innen sind befreit (#24).
        Depends(verify_altcha_unless_authenticated),
    ],
    # 400 = malformed JSON / Altcha ungültig, 413 = Body zu groß, 422 = Form-/Schema-
    # Validierung, 429 = Rate-Limit (api.md §7).
    responses=_errors(400, 404, 413, 422, 429),
)
async def create_application(
    payload: ApplicationCreate,
    service: ServiceDep,
    settings: SettingsDep,
    background: BackgroundTasks,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    send_magic_link: Annotated[MagicLinkSender, Depends(get_magic_link_sender)],
) -> ApplicationCreated:
    """Antrag anlegen. PII getrennt, v1-Version, Magic-Link-Mail enqueued.

    Eingeloggte Nutzer:innen (#24) brauchen **kein** Altcha; fehlende
    ``applicantEmail``/``applicantName`` werden aus dem Account abgeleitet und der
    Audit-Akteur ist ihr Principal-``sub``. Anonyme Einreichung wie bisher (Altcha +
    Pflicht-``applicantEmail``)."""
    # Maßgebliche Schranke: serialisierte Feldwerte (unabhängig von Content-Length).
    if len(json.dumps(payload.data)) > settings.max_application_payload_bytes:
        raise PayloadTooLargeError(
            f"Application data exceeds {settings.max_application_payload_bytes} bytes."
        )
    # Identität ableiten: explizite Angabe gewinnt, sonst der eingeloggte Account.
    email = (
        str(payload.applicant_email)
        if payload.applicant_email
        else (principal.email if principal else None)
    )
    if not email:
        raise ValidationProblem(
            "Applicant email required.",
            errors=[
                {"field": "applicantEmail", "msg": "required for anonymous submissions"}
            ],
        )
    payload.applicant_email = email
    if not payload.applicant_name and principal:
        payload.applicant_name = principal.display_name
    actor = principal.sub if principal else "applicant"

    app, email = await service.create(payload, actor=actor)
    background.add_task(send_magic_link, settings, email, app.id)
    return ApplicationCreated(applicationId=app.id)


@router.get(
    "/applications/tasks",
    response_model=list[ApplicationListItem],
    responses=_errors(401, 403),
)
async def list_tasks(
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("application.read"))],
) -> list[ApplicationListItem]:
    """Offene Entscheidungen für die eigene Rolle (#64): Anträge in vote/approval-
    States, in denen der Principal handeln darf."""
    return await service.list_tasks(principal)


@router.get(
    "/applications",
    response_model=Page[ApplicationListItem],
    dependencies=[Depends(require_principal("application.read"))],
    responses=_errors(401, 403),
)
async def list_applications(
    service: ServiceDep,
    page: Annotated[PageParams, Depends()],
    state_id: Annotated[UUID | None, Query(alias="state")] = None,
    gremium_id: Annotated[UUID | None, Query(alias="gremium")] = None,
    type_id: Annotated[UUID | None, Query(alias="type")] = None,
    budget_pot_id: Annotated[UUID | None, Query(alias="topf")] = None,
    q: Annotated[str | None, Query()] = None,
) -> Page[ApplicationListItem]:
    """Antragsliste (Filter: state/gremium/type/topf/q; Offset-Paging)."""
    return await service.list_applications(
        state_id=state_id,
        gremium_id=gremium_id,
        type_id=type_id,
        budget_pot_id=budget_pot_id,
        q=q,
        limit=page.limit,
        offset=page.offset,
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
    """Antrag lesen. PII/interne Sicht nur für Principals."""
    principal = access.principal
    return await service.get(
        access.application_id,
        include_pii=access.can_see_internal,
        requester_sub=principal.sub if principal is not None else None,
        requester_can_manage=principal.has("application.manage")
        if principal is not None
        else False,
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
    """Antragsdaten ändern → neue Version (gesperrter State → 409)."""
    return await service.patch(
        access.application_id, payload.data, changed_by=access.actor
    )


@router.delete(
    "/applications/{application_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_application(
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_edit)],
) -> None:
    """Antrag löschen — Verwalter:in (``application.manage``) oder Ersteller:in (#24)."""
    await service.delete(access.application_id)


@router.get(
    "/applications/{application_id}/timeline",
    response_model=list[TimelineEventOut],
    responses=_errors(401, 403, 404),
)
async def get_timeline(
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_read)],
) -> list[TimelineEventOut]:
    """Status-Timeline des Antrags."""
    return await service.timeline(access.application_id)


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
    """Versionshistorie + Diff (Principal-only)."""
    return await service.versions(application_id)


@router.post(
    "/applications/{application_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(400, 401, 403, 404, 422),
)
async def add_comment(
    payload: CommentCreate,
    service: ServiceDep,
    # Bewusst ``require_app_read`` (view-Scope genügt): Kommentieren ist Kommunikation,
    # keine Antrags-Datenmutation — ein Antragsteller darf auch im gesperrten (view-only)
    # Status noch öffentlich nachfragen. Entspricht api.md (POST comments = A(public)/P).
    access: Annotated[Access, Depends(require_app_read)],
) -> CommentOut:
    """Kommentar anlegen. Antragsteller dürfen nur ``public`` schreiben (sonst 403)."""
    if payload.visibility == "internal" and not access.can_see_internal:
        raise ForbiddenError("Applicants may only post public comments.")
    author = access.principal.sub if access.principal is not None else None
    return await service.add_comment(
        access.application_id,
        author=author,
        author_kind=access.author_kind,
        body=payload.body,
        visibility=payload.visibility,
    )


@router.get(
    "/applications/{application_id}/comments",
    response_model=list[CommentOut],
    responses=_errors(401, 403, 404),
)
async def list_comments(
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_read)],
) -> list[CommentOut]:
    """Kommentare lesen. Antragsteller sehen nur ``public`` (api.md §3)."""
    return await service.list_comments(
        access.application_id, include_internal=access.can_see_internal
    )
