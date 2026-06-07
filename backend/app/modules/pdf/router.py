"""pdf-API-Router (T-20, api.md »pdf«).

* ``POST /api/applications/{id}/pdf`` — A/P; legt einen Render-Job an, enqueued ihn
  (Worker rendert) → **202** + ``JobOut`` (``status=pending``). Ablage MinIO + optional
  Nextcloud erfolgt async (flows §6).
* ``GET  /api/jobs/{id}``           — A/P; Job-Status + (bei ``done``) signierte
  Ergebnis-URL. Zugriff via Principal **oder** Antragsteller des zugehörigen Antrags.

Fehler werden als ``ProblemDetail`` deklariert (problem+json). Fehlt Redis, bleibt der
Job ``pending`` (kein API-Block); fehlt MinIO, liefert ``GET`` keine ``resultUrl``.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.deps import DbSession, SettingsDep, get_current_applicant, get_current_principal
from app.modules.applications.access import (
    READ_PERMISSION,
    Access,
    require_app_read,
    resolve_access,
)
from app.modules.auth.principal import Applicant, Principal
from app.modules.files.storage import ObjectStorage
from app.modules.pdf.queue import render_queue_from_pool
from app.modules.pdf.schemas import JobOut
from app.modules.pdf.service import PdfService
from app.shared.errors import (
    ForbiddenError,
    NotFoundError,
    ProblemDetail,
    UnauthorizedError,
)

router = APIRouter(tags=["pdf"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_pdf_service(session: DbSession) -> PdfService:
    return PdfService(session)


ServiceDep = Annotated[PdfService, Depends(get_pdf_service)]


@router.post(
    "/applications/{application_id}/pdf",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_errors(401, 403, 404),
)
async def create_application_pdf(
    application_id: UUID,
    service: ServiceDep,
    request: Request,
    session: DbSession,
    _access: Annotated[Access, Depends(require_app_read)],
) -> JobOut:
    """Antrags-PDF anstoßen. 202 + Job (``pending``); der Worker rendert async."""
    job = await service.create_application_job(application_id)
    await session.commit()
    # Nach Commit enqueuen, damit der Worker die Job-Zeile garantiert sieht. Ohne Redis
    # bleibt der Job pending (kein Block); ein späterer Anstoß/Requeue holt ihn ab.
    pool = getattr(request.app.state, "arq_pool", None)
    queue = render_queue_from_pool(pool)
    if queue is not None:
        await queue.enqueue(job.id)
    return service.to_out(job)


@router.get(
    "/jobs/{job_id}",
    response_model=JobOut,
    responses=_errors(401, 404),
)
async def get_job(
    job_id: UUID,
    service: ServiceDep,
    request: Request,
    settings: SettingsDep,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> JobOut:
    """Job-Status. Zugriff via Principal **oder** Antragsteller des zugehörigen Antrags."""
    # Fail-closed **vor** dem DB-Zugriff: ohne Identität 401 (kein Existenz-Orakel).
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    job = await service.get_job(job_id)
    # A/P-Zugriff gegen den Antrag des Jobs prüfen. Cross-Tenant → bewusst 404 statt 403
    # (kein Existenz-Orakel, analog files/T-13). view-Scope genügt.
    if job.application_id is not None:
        try:
            resolve_access(
                job.application_id,
                principal,
                applicant,
                perm=READ_PERMISSION,
                scope="view",
            )
        except ForbiddenError as exc:
            raise NotFoundError(f"job {job_id} not found") from exc
    elif principal is None:
        # Job ohne Antrags-Bezug: nur Principals dürfen ihn sehen.
        raise NotFoundError(f"job {job_id} not found")
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    return service.to_out(job, storage=storage, settings=settings)
