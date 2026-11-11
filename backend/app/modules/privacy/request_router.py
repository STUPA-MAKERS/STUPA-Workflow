"""The route that asks for the erasure of an Antrag.

`POST /applications/{application_id}/erasure-request` is in `privacy` and not in
`applications`, because it files the request into the privacy queue, and
`applications` imports no higher module (§S/backend/python/000652). The URL and the
response are those of the application routes.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response

from app.deps import DbSession, SettingsDep
from app.modules.applications.access import Access, require_app_read
from app.modules.applications.erasure_mail import notify_erasure_requested
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.privacy.service import ErasureRequestService
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["applications"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Document problem+json for the given error status codes."""
    return dict.fromkeys(codes, _PROBLEM)


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
    access: Annotated[Access, Depends(require_app_read)],
) -> Response:
    """File an erasure request (GDPR Art. 17) into the ``/admin/privacy`` queue.

    The route notifies the privacy officers.

    Every identity that may read the application may request the erasure of the PII: the
    magic-link applicant, the creator and an authorized principal.
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
