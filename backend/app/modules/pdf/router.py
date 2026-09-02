"""pdf API router.

* ``POST /api/applications/{id}/pdf`` — applicant or principal. Creates a render job
  and enqueues it for the worker, then answers 202 with ``JobOut``
  (``status=pending``). The storage in MinIO happens async.
* ``GET  /api/jobs/{id}``           — applicant or principal. Returns the job status
  and, when the job is ``done``, the app-relative download route. Access goes through a
  principal or through the applicant of the related application.
* ``GET  /api/jobs/{id}/download``  — same access check. Streams the rendered PDF from
  the API, because the browser cannot reach MinIO.

Errors are declared as ``ProblemDetail`` (problem+json). Without Redis the job stays
``pending`` and the API does not block. Without MinIO ``GET`` returns no ``resultUrl``.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from app.deps import DbSession, get_current_applicant, get_current_principal
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
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ProblemDetail,
    ServiceUnavailableError,
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
    """Trigger an application PDF.

    Answers 202 with the job in state ``pending``. The worker renders async.
    """
    job = await service.create_application_job(application_id)
    await session.commit()
    # Enqueue after the commit so the worker always sees the job row. Without Redis the
    # job stays pending and nothing blocks. A later trigger or requeue picks it up.
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
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> JobOut:
    """Return the job status.

    A principal or the applicant of the related application may read the job.
    """
    # Fail-closed before the DB access: no identity → 401 (no existence oracle).
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    job = await service.get_job(job_id)
    # Check applicant and principal access against the application of the job. A
    # cross-tenant read returns 404 on purpose, not 403, so there is no existence
    # oracle. The files module does the same. The view scope is enough.
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
    return service.to_out(job, storage=storage)


@router.get(
    "/jobs/{job_id}/download",
    response_class=StreamingResponse,
    responses=_errors(401, 404, 409, 503),
)
async def download_job_result(
    job_id: UUID,
    service: ServiceDep,
    request: Request,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> StreamingResponse:
    """Stream the rendered PDF.

    NOT a presigned MinIO URL. MinIO runs on the internal Docker network, so such a URL
    binds a host the browser cannot resolve. The attachment download solves it the same
    way, and its comment states the reason.

    The access check is the one from ``get_job``: a principal or the owning applicant,
    and a cross-tenant read gets 404 rather than 403, so the API is no existence oracle.
    """
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    job = await service.get_job(job_id)
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
        raise NotFoundError(f"job {job_id} not found")

    if job.status != "done" or job.storage_key is None:
        raise ConflictError("This render is not finished.", code="render_not_ready")
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    if storage is None:
        raise ServiceUnavailableError("Object storage is not configured.")

    stream = await storage.get_stream(job.storage_key)
    # A job without an application link is a standalone render, so name it after the job.
    filename = f"antrag-{job.application_id or job.id}.pdf"
    return StreamingResponse(
        stream,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
