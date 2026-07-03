"""pdf API router.

* ``POST /api/applications/{id}/pdf`` — applicant/principal; creates a render job and
  enqueues it (the worker renders) → 202 + ``JobOut`` (``status=pending``). Storage in
  MinIO happens async.
* ``GET  /api/jobs/{id}``           — applicant/principal; job status + (when ``done``)
  a signed result URL. Access via a principal or the applicant of the related
  application.

Errors are declared as ``ProblemDetail`` (problem+json). Without Redis the job stays
``pending`` (no API block); without MinIO ``GET`` returns no ``resultUrl``.
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
    """Trigger an application PDF. 202 + job (``pending``); the worker renders async."""
    job = await service.create_application_job(application_id)
    await session.commit()
    # Enqueue after commit so the worker is guaranteed to see the job row. Without Redis
    # the job stays pending (no block); a later trigger/requeue picks it up.
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
    """Job status. Access via a principal or the applicant of the related application."""
    # Fail-closed before the DB access: no identity → 401 (no existence oracle).
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    job = await service.get_job(job_id)
    # Check applicant/principal access against the job's application. Cross-tenant →
    # deliberately 404 not 403 (no existence oracle, like files). view scope suffices.
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
        # Job without an application link: only principals may see it.
        raise NotFoundError(f"job {job_id} not found")
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    return service.to_out(job, storage=storage, settings=settings)
