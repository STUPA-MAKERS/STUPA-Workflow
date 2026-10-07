"""Protocol API router.

The server authorizes every endpoint per gremium and fails closed. Each
endpoint gates authentication with `require_principal()` and delegates the
authorization to `MeetingService`, through the helpers of `ProtocolService`.
These are the same scope rules as the live stack under `/api/meetings/…`.

A gate on global permissions alone would lock out a secretary who holds the
permission through a gremium role. `resolve_principal` deliberately does NOT
merge gremium-role permissions into `principal.permissions`, so the router
delegates to the service.

The router wires the service with the shared render infrastructure. Object
storage and the arq mail pool come from the app state. The typst client comes
from the settings. The endpoints declare their errors as `ProblemDetail`
(problem+json).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import (
    DbSession,
    SettingsDep,
    require_principal,
)
from app.modules.auth.principal import Principal
from app.modules.files.storage import ObjectStorage
from app.modules.livevote.service import BrokerPublisher, MeetingService
from app.modules.notifications.queue import ArqMailQueue, MailQueue
from app.modules.pdf.typst_client import build_typst_client
from app.modules.protocol.queue import enqueue_public_backfill, protocol_render_queue_from_pool
from app.modules.protocol.schemas import (
    ProtocolFinalizeBody,
    ProtocolOut,
    ProtocolPatch,
    ProtocolVotesBody,
)
from app.modules.protocol.service import ProtocolService
from app.settings import Settings
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["protocol"])
logger = logging.getLogger("app.protocol")

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def _mail_queue(request: Request) -> MailQueue | None:
    """Build the arq mail queue from the app-state pool, or `None` without Redis."""
    pool = getattr(request.app.state, "arq_pool", None)
    return ArqMailQueue(pool) if pool is not None else None


def get_protocol_service(
    session: DbSession, request: Request, settings: SettingsDep
) -> ProtocolService:
    """Wire the service: storage and mail from the app state, typst from settings."""
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    return ProtocolService(
        session,
        storage=storage,
        typst=build_typst_client(settings),
        mail_queue=_mail_queue(request),
        settings=settings,
    )


ServiceDep = Annotated[ProtocolService, Depends(get_protocol_service)]


async def schedule_public_backfill(
    request: Request, session: AsyncSession, settings: Settings, gremium_id: UUID
) -> None:
    """Start the build of the missing public versions after a gremium went public.

    With Redis the arq worker runs the job. Without Redis (development, contract
    CI) the request runs it inline. The gremium change is already committed, so an
    error here only logs: the protocols without a public version stay hidden.
    """
    pool = getattr(request.app.state, "arq_pool", None)
    if pool is not None:
        await enqueue_public_backfill(pool, gremium_id)
        return
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    service = ProtocolService(
        session, storage=storage, typst=build_typst_client(settings), settings=settings
    )
    try:
        await service.backfill_public(gremium_id)
    except Exception:  # noqa: BLE001 - the gremium save already succeeded
        logger.exception("inline public backfill failed (gremium=%s)", gremium_id)


# This dependency only requires authentication. Each endpoint checks the
# per-gremium authorization through ProtocolService and MeetingService.
PrincipalDep = Annotated[Principal, Depends(require_principal())]


@router.post(
    "/meetings/{meeting_id}/protocol",
    response_model=ProtocolOut,
    responses=_errors(401, 403, 404),
)
async def create_or_load_protocol(
    meeting_id: UUID, service: ServiceDep, principal: PrincipalDep
) -> ProtocolOut:
    """Create or load the protocol of the meeting, one per meeting and idempotent."""
    await service.authorize_write_meeting(meeting_id, principal)
    return await service.get_or_create(meeting_id, author=principal.sub)


@router.get(
    "/meetings/{meeting_id}/protocol",
    response_model=ProtocolOut,
    responses=_errors(401, 403, 404),
)
async def get_protocol(
    meeting_id: UUID, service: ServiceDep, principal: PrincipalDep
) -> ProtocolOut:
    """Read the protocol of the meeting, or 404 when none exists.

    This is the reload and poll path. The read scope is the meeting view
    (`assert_can_read`): gremium members, pool substitutes, delegation
    recipients, plus the global `meeting.view_all` and admin.
    """
    await service.authorize_read_meeting(meeting_id, principal)
    return await service.get_by_meeting(meeting_id)


@router.patch(
    "/protocols/{protocol_id}",
    response_model=ProtocolOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def update_protocol(
    protocol_id: UUID,
    payload: ProtocolPatch,
    service: ServiceDep,
    principal: PrincipalDep,
) -> ProtocolOut:
    """Update the editor body or the publication of the protocol.

    `markdown` needs write access and a draft (409 when the protocol is final or
    under render). `publicWithheld` holds back the protocol from the public
    protocols page or releases it. It needs the right to finalize (the publishing
    right) and works in every status. It writes `protocol_publication`.
    """
    if payload.public_withheld is not None:
        await service.authorize_finalize(protocol_id, principal)
    if payload.markdown is not None:
        await service.authorize_write(protocol_id, principal)
        out = await service.update_markdown(protocol_id, payload.markdown)
        if payload.public_withheld is None:
            return out
    # The schema requires one of the two fields, so `publicWithheld` is set here.
    return await service.set_public_withheld(
        protocol_id, bool(payload.public_withheld), actor=principal.sub
    )


@router.delete(
    "/protocols/{protocol_id}",
    status_code=204,
    responses=_errors(401, 403, 404, 409),
)
async def delete_protocol(
    protocol_id: UUID,
    service: ServiceDep,
    principal: PrincipalDep,
) -> None:
    """Delete a protocol while it is still a draft.

    A finalized protocol is a signed record that already went out, so it
    answers 409. A protocol under render is frozen and answers 409 too.

    The gate is `authorize_write`, the same scope as the PATCH, and NOT
    `protocol.finalize`. That permission gates publishing, not discarding: the
    same caller can already empty the body through the PATCH, so a stricter
    gate here would protect nothing.
    """
    await service.authorize_write(protocol_id, principal)
    await service.delete_protocol(protocol_id, actor=principal.sub)


@router.post(
    "/protocols/{protocol_id}/votes",
    response_model=ProtocolOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def embed_votes(
    protocol_id: UUID,
    payload: ProtocolVotesBody,
    service: ServiceDep,
    principal: PrincipalDep,
) -> ProtocolOut:
    """Embed votes as Markdown snippets. The operation is idempotent."""
    await service.authorize_write(protocol_id, principal)
    return await service.embed_votes(protocol_id, payload.vote_ids)


@router.post(
    "/protocols/{protocol_id}/finalize",
    response_model=ProtocolOut,
    responses=_errors(400, 401, 403, 404, 409, 503),
)
async def finalize_protocol(
    protocol_id: UUID,
    service: ServiceDep,
    request: Request,
    principal: PrincipalDep,
    payload: ProtocolFinalizeBody | None = None,
) -> ProtocolOut:
    """Start the finalization: set `status=rendering` and enqueue `render_protocol`.

    The caller needs write access AND the gremium permission `protocol.finalize`
    in the gremium of the meeting (or the admin role). This is stricter than a
    write to the draft.

    The meeting must be closed (409 `meeting_not_closed`, F8, O13), and the
    protocol must be a draft (409 `protocol_not_draft`): a protocol is finalized
    once, also when several members kept the minutes (O2). The start writes
    `protocol_finalize`. The optional body `{publicWithheld}` holds back the
    protocol from the public protocols page.

    The call does not block, because the typst render runs in the arq worker.
    The worker sets `final` and sends the mail. A permanent failure falls back
    to `draft`, and a new call starts again. Without Redis the request renders
    synchronously as a fallback, so a protocol never stays stuck in `rendering`.
    """
    await service.authorize_finalize(protocol_id, principal)
    withheld = payload.public_withheld if payload is not None else False
    out = await service.start_finalize(protocol_id, actor=principal.sub, public_withheld=withheld)
    pool = getattr(request.app.state, "arq_pool", None)
    queue = protocol_render_queue_from_pool(pool)
    if queue is None:
        # Sync fallback without Redis: on an error roll back to `draft`, which
        # allows a new finalize, then re-raise unchanged as problem+json.
        try:
            return await service.finalize(protocol_id, now=datetime.now(UTC))
        except Exception:
            await service.session.rollback()
            await service.revert_to_draft(protocol_id)
            raise
    await queue.enqueue(protocol_id)
    # Tell the followers at once through the meeting_state broadcast, with the
    # "rendering" tag. The worker broadcasts again after final or a rollback.
    broker = getattr(request.app.state, "broker", None)
    if broker is not None:
        await MeetingService(service.session, BrokerPublisher(broker)).broadcast_state(
            out.meeting_id, principal
        )
    return out


@router.get(
    "/protocols/{protocol_id}/pdf",
    responses=_errors(401, 403, 404, 503),
    response_class=Response,
)
async def get_protocol_pdf(
    protocol_id: UUID, service: ServiceDep, principal: PrincipalDep
) -> Response:
    """Stream the protocol PDF inline, because MinIO has no browser access.

    The endpoint fetches from storage server-side instead of a presigned URL.
    MinIO is reachable only on the internal Docker network. An S3v4-signed URL
    would bind the internal host and stay unreachable from the browser.

    The read scope is the meeting view (`assert_can_read`), like the protocol
    GET.
    """
    await service.authorize_read(protocol_id, principal)
    data = await service.get_pdf_bytes(protocol_id)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=protokoll.pdf"},
    )


@router.get(
    "/protocols/{protocol_id}/pdf/public",
    responses=_errors(401, 403, 404, 503),
    response_class=Response,
)
async def get_protocol_public_pdf(
    protocol_id: UUID, service: ServiceDep, principal: PrincipalDep
) -> Response:
    """Stream the redacted public variant of the protocol.

    The variant exists only when the meeting had at least one non-public agenda
    item. Otherwise the endpoint returns 404. The read authorization is the
    same as for the internal PDF.
    """
    await service.authorize_read(protocol_id, principal)
    data = await service.get_public_pdf_bytes(protocol_id)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=protokoll-oeffentlich.pdf"},
    )
