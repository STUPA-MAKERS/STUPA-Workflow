"""Protocol API router.

Endpoints are authorized server-side per gremium (fail-closed). Every endpoint
gates authentication via ``require_principal()`` and delegates authorization to
:class:`MeetingService` (through ``ProtocolService`` helpers) — the same scope
rules as the live stack (``/api/meetings/…``). Global-permission gating alone
would lock out per-gremium protokollants; ``resolve_principal`` deliberately
does NOT merge gremium-role permissions into ``principal.permissions``, hence
the delegation to the service.

The service is wired with the shared render infrastructure (object storage +
arq mail pool from app state; pytex client from settings). Errors are declared
as ``ProblemDetail`` (problem+json).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.deps import (
    DbSession,
    SettingsDep,
    require_principal,
)
from app.modules.auth.principal import Principal
from app.modules.files.storage import ObjectStorage
from app.modules.livevote.service import BrokerPublisher, MeetingService
from app.modules.notifications.queue import ArqMailQueue, MailQueue
from app.modules.pdf.pytex_client import build_pytex_client
from app.modules.protocol.queue import protocol_render_queue_from_pool
from app.modules.protocol.schemas import ProtocolOut, ProtocolPatch, ProtocolVotesBody
from app.modules.protocol.service import ProtocolService
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["protocol"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def _mail_queue(request: Request) -> MailQueue | None:
    """Build the arq mail queue from the app-state pool (``None`` without Redis)."""
    pool = getattr(request.app.state, "arq_pool", None)
    return ArqMailQueue(pool) if pool is not None else None


def get_protocol_service(
    session: DbSession, request: Request, settings: SettingsDep
) -> ProtocolService:
    """Wire the service with render infra (storage/mail from state, pytex from settings)."""
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    return ProtocolService(
        session,
        storage=storage,
        pytex=build_pytex_client(settings),
        mail_queue=_mail_queue(request),
        settings=settings,
    )


ServiceDep = Annotated[ProtocolService, Depends(get_protocol_service)]
# Endpoints only require authentication here; fine-grained per-gremium
# authorization is checked per endpoint via ProtocolService → MeetingService.
PrincipalDep = Annotated[Principal, Depends(require_principal())]


@router.post(
    "/meetings/{meeting_id}/protocol",
    response_model=ProtocolOut,
    responses=_errors(401, 403, 404),
)
async def create_or_load_protocol(
    meeting_id: UUID, service: ServiceDep, principal: PrincipalDep
) -> ProtocolOut:
    """Create or load the meeting's protocol (idempotent, 1:1 to the meeting)."""
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
    """Read the meeting's protocol (404 without one) — reload/poll path.

    Read scope = meeting view (``assert_can_read``): gremium members/pool
    substitutes, delegation recipients, plus global
    ``meeting.view_all``/``meeting.manage``/admin."""
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
    """Update the editor body. 409 if the protocol is already final."""
    await service.authorize_write(protocol_id, principal)
    return await service.update_markdown(protocol_id, payload.markdown)


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
    """Embed votes as Markdown snippets (idempotent)."""
    await service.authorize_write(protocol_id, principal)
    return await service.embed_votes(protocol_id, payload.vote_ids)


@router.post(
    "/protocols/{protocol_id}/finalize",
    response_model=ProtocolOut,
    responses=_errors(401, 403, 404, 503),
)
async def finalize_protocol(
    protocol_id: UUID, service: ServiceDep, request: Request, principal: PrincipalDep
) -> ProtocolOut:
    """Start finalization: ``status=rendering`` + a ``render_protocol`` worker job.

    Requires write access AND ``protocol.finalize`` (global or as gremium role) —
    stricter than draft writing.

    Non-blocking (pytex render runs in the arq worker); the worker sets
    ``final`` and sends the mail, a permanent failure falls back to ``draft``.
    Without Redis the request renders synchronously as fallback — never stuck
    in ``rendering``. Idempotent: ``rendering``/``final`` is returned unchanged
    (no double render/send)."""
    await service.authorize_finalize(protocol_id, principal)
    out, needs_render = await service.start_finalize(protocol_id)
    if not needs_render:
        return out
    pool = getattr(request.app.state, "arq_pool", None)
    queue = protocol_render_queue_from_pool(pool)
    if queue is None:
        # Sync fallback without Redis: on error roll back to ``draft``
        # (re-finalizable), then re-raise unchanged as problem+json.
        try:
            return await service.finalize(protocol_id, now=datetime.now(UTC))
        except Exception:
            await service.session.rollback()
            await service.revert_to_draft(protocol_id)
            raise
    await queue.enqueue(protocol_id)
    # Inform followers immediately ("rendering" tag) via meeting_state broadcast;
    # the worker broadcasts again once final/rolled back.
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
    """Stream the protocol PDF inline (MinIO is internal, no browser access).

    Server-side storage fetch instead of a presigned URL: MinIO is only
    reachable on the internal Docker network, so an S3v4-signed URL would bind
    the internal host and be unreachable from the browser.

    Read scope = meeting view (``assert_can_read``), like the protocol GET."""
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
    """Stream the redacted public protocol variant.

    Only exists when the meeting had at least one non-public agenda item;
    otherwise 404. Same read authorization as the internal PDF."""
    await service.authorize_read(protocol_id, principal)
    data = await service.get_public_pdf_bytes(protocol_id)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=protokoll-oeffentlich.pdf"},
    )
