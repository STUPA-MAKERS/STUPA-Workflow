"""Protokoll-API-Router (T-22, api.md »protocol«, flows §7).

Vier Endpunkte, **alle** ``P(meeting.manage)`` (serverseitige RBAC, fail-closed;
#28-Redesign: ``protocol.write`` in ``meeting.manage`` zusammengeführt):

* ``POST  /api/meetings/{id}/protocol`` — Protokoll anlegen **oder** laden (idempotent).
* ``PATCH /api/protocols/{id}``          — Markdown-Body aktualisieren (Entwurf).
* ``POST  /api/protocols/{id}/votes``    — Abstimmungen als Snippets einbetten.
* ``POST  /api/protocols/{id}/finalize`` — → PDF (pytex) → MinIO/Nextcloud → MAIL_LIST.

Der Service wird mit der **T-20-Render-Infrastruktur** verdrahtet (Object-Storage +
arq-Mail-Pool aus dem App-State; pytex-Client + Nextcloud-Exporter aus den Settings) —
keine Duplikation. Fehler werden als ``ProblemDetail`` (problem+json) deklariert.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.deps import DbSession, SettingsDep, require_principal
from app.modules.auth.principal import Principal
from app.modules.files.storage import ObjectStorage
from app.modules.notifications.queue import ArqMailQueue, MailQueue
from app.modules.pdf.nextcloud import build_nextcloud_exporter
from app.modules.pdf.pytex_client import build_pytex_client
from app.modules.protocol.schemas import ProtocolOut, ProtocolPatch, ProtocolVotesBody
from app.modules.protocol.service import ProtocolService
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["protocol"])

WRITE_PERMISSION = "meeting.manage"
_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def _mail_queue(request: Request) -> MailQueue | None:
    """arq-Mail-Queue aus dem App-State-Pool (oder ``None`` ohne Redis)."""
    pool = getattr(request.app.state, "arq_pool", None)
    return ArqMailQueue(pool) if pool is not None else None


def get_protocol_service(
    session: DbSession, request: Request, settings: SettingsDep
) -> ProtocolService:
    """Service mit T-20-Render-Infra verdrahten (Storage/Mail aus State, pytex/NC aus Settings)."""
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    return ProtocolService(
        session,
        storage=storage,
        pytex=build_pytex_client(settings),
        nextcloud=build_nextcloud_exporter(settings),
        mail_queue=_mail_queue(request),
        settings=settings,
    )


ServiceDep = Annotated[ProtocolService, Depends(get_protocol_service)]
WriterDep = Annotated[Principal, Depends(require_principal(WRITE_PERMISSION))]


@router.post(
    "/meetings/{meeting_id}/protocol",
    response_model=ProtocolOut,
    responses=_errors(401, 403, 404),
)
async def create_or_load_protocol(
    meeting_id: UUID, service: ServiceDep, principal: WriterDep
) -> ProtocolOut:
    """Protokoll der Sitzung anlegen **oder** laden (idempotent, 1:1 zur Sitzung)."""
    return await service.get_or_create(meeting_id, author=principal.sub)


@router.patch(
    "/protocols/{protocol_id}",
    response_model=ProtocolOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def update_protocol(
    protocol_id: UUID,
    payload: ProtocolPatch,
    service: ServiceDep,
    _principal: WriterDep,
) -> ProtocolOut:
    """Editor-Body aktualisieren. 409, wenn das Protokoll bereits final ist."""
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
    _principal: WriterDep,
) -> ProtocolOut:
    """Abstimmungen als Markdown-Snippets einbetten (idempotent)."""
    return await service.embed_votes(protocol_id, payload.vote_ids)


@router.post(
    "/protocols/{protocol_id}/finalize",
    response_model=ProtocolOut,
    responses=_errors(401, 403, 404, 503),
)
async def finalize_protocol(
    protocol_id: UUID, service: ServiceDep, _principal: WriterDep
) -> ProtocolOut:
    """→ PDF (pytex) → MinIO/Nextcloud → Mail an MAIL_LIST(gremium); ``status=final``."""
    return await service.finalize(protocol_id, now=datetime.now(UTC))
