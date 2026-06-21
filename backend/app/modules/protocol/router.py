"""Protokoll-API-Router (T-22, api.md »protocol«, flows §7).

Endpunkte, **serverseitig per Gremium** autorisiert (fail-closed). Die Authentifizierung
gatet jeder Endpunkt über ``require_principal()``; die Berechtigung delegiert er an den
:class:`MeetingService` (über ``ProtocolService``-Helfer) — **identische** Scope-Regeln
wie der Live-Stack (``/api/meetings/…``):

* ``POST  /api/meetings/{id}/protocol`` — anlegen/laden; ``can_write`` (Verwalter,
  zugewiesener Protokollant ODER Gremium-Rolle mit ``protocol.write``).
* ``GET   /api/meetings/{id}/protocol`` — lesen; ``assert_can_read`` (Sitzungs-Sicht).
* ``PATCH /api/protocols/{id}``          — Markdown-Body aktualisieren; ``can_write``.
* ``POST  /api/protocols/{id}/votes``    — Abstimmungen einbetten; ``can_write``.
* ``POST  /api/protocols/{id}/finalize`` — → PDF → MinIO → MAIL_LIST; ``can_write`` UND
  ``protocol.finalize`` (global ODER als Gremium-Rolle).
* ``GET   /api/protocols/{id}/pdf[/public]`` — PDF streamen; ``assert_can_read``.

Vorher gateten alle Endpunkte auf GLOBALE ``meeting.manage``/``protocol.finalize``/
``meeting.view_all`` — das sperrte per-Gremium-Protokollanten ohne org-weite Permission
aus (AUD-016: die TOP-Bodies waren per Gremium editierbar, das montierende Protokoll
nicht). ``resolve_principal`` führt Gremium-Rollen-Permissions bewusst NICHT in
``principal.permissions``, daher die Delegation an den Service.

Der Service wird mit der **T-20-Render-Infrastruktur** verdrahtet (Object-Storage +
arq-Mail-Pool aus dem App-State; pytex-Client aus den Settings) —
keine Duplikation. Fehler werden als ``ProblemDetail`` (problem+json) deklariert.
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
    """arq-Mail-Queue aus dem App-State-Pool (oder ``None`` ohne Redis)."""
    pool = getattr(request.app.state, "arq_pool", None)
    return ArqMailQueue(pool) if pool is not None else None


def get_protocol_service(
    session: DbSession, request: Request, settings: SettingsDep
) -> ProtocolService:
    """Service mit T-20-Render-Infra verdrahten (Storage/Mail aus State, pytex aus Settings)."""
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    return ProtocolService(
        session,
        storage=storage,
        pytex=build_pytex_client(settings),
        mail_queue=_mail_queue(request),
        settings=settings,
    )


ServiceDep = Annotated[ProtocolService, Depends(get_protocol_service)]
# Alle Endpunkte verlangen nur Authentifizierung; die feingranulare (per-Gremium)
# Berechtigung prüft jeder Endpunkt selbst über ``ProtocolService``→``MeetingService``.
PrincipalDep = Annotated[Principal, Depends(require_principal())]


@router.post(
    "/meetings/{meeting_id}/protocol",
    response_model=ProtocolOut,
    responses=_errors(401, 403, 404),
)
async def create_or_load_protocol(
    meeting_id: UUID, service: ServiceDep, principal: PrincipalDep
) -> ProtocolOut:
    """Protokoll der Sitzung anlegen **oder** laden (idempotent, 1:1 zur Sitzung)."""
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
    """Protokoll der Sitzung **lesen** (404 ohne Protokoll) — Reload-/Poll-Pfad.

    Der Status-Poll während des Hintergrund-Renders lief vorher über den POST und
    schlug nach kurzer Zeit am Default-Write-Rate-Limit auf (429, #async-finalize).

    Lese-Scope = Sitzungs-Sicht (``assert_can_read``): Mitglieder/Pool-Vertreter des
    Gremiums, Delegations-Empfänger, sowie global ``meeting.view_all``/``meeting.manage``/
    Admin. AUD-016: vorher global-permission-gegatet, was per-Gremium-Protokollanten
    aussperrte."""
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
    """Editor-Body aktualisieren. 409, wenn das Protokoll bereits final ist."""
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
    """Abstimmungen als Markdown-Snippets einbetten (idempotent)."""
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
    """Finalisierung anstoßen: ``status=rendering`` + ``render_protocol``-Worker-Job.

    Schreibrecht UND ``protocol.finalize`` (global ODER als Gremium-Rolle) — strenger
    als das Entwurf-Schreiben (#6).

    Nicht-blockierend (der pytex-Render läuft im arq-Worker); der Worker setzt
    ``final`` + versendet die Mail, bei dauerhaftem Fehler fällt das Protokoll auf
    ``draft`` zurück. Ohne Redis (DEV/Contract-CI) rendert der Request synchron als
    Fallback — nie in ``rendering`` hängen. Idempotent: ``rendering``/``final``
    wird unverändert zurückgegeben (kein Doppel-Render/-Versand)."""
    await service.authorize_finalize(protocol_id, principal)
    out, needs_render = await service.start_finalize(protocol_id)
    if not needs_render:
        return out
    pool = getattr(request.app.state, "arq_pool", None)
    queue = protocol_render_queue_from_pool(pool)
    if queue is None:
        # Sync-Fallback ohne Redis: Fehler → Rollback auf ``draft`` (re-finalisierbar),
        # dann den Fehler unverändert als problem+json durchreichen (Alt-Verhalten).
        try:
            return await service.finalize(protocol_id, now=datetime.now(UTC))
        except Exception:
            await service.session.rollback()
            await service.revert_to_draft(protocol_id)
            raise
    await queue.enqueue(protocol_id)
    # Follower sofort informieren (»Wird gerendert«-Tag): meeting_state-Broadcast;
    # der Worker broadcastet erneut, wenn final/zurückgerollt.
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
    """PDF des Protokolls inline streamen (MinIO liegt intern, kein Browser-Zugriff).

    Server-seitiger Storage-Fetch statt presigned URL: MinIO ist nur im ``internal``-
    Docker-Netz erreichbar, eine S3v4-signierte URL bindet den internen Host → vom
    Browser unerreichbar. Über nginx ``/api/`` ist dieser Endpunkt erreichbar.

    Lese-Scope = Sitzungs-Sicht (``assert_can_read``) — wie der Protokoll-GET (AUD-016)."""
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
    """Redigierte öffentliche Protokoll-Variante streamen (#PII-Re-Add).

    Nur vorhanden, wenn die Sitzung mind. einen nicht-öffentlichen TOP hatte; sonst 404.
    Gleiche Lese-Berechtigung wie das interne PDF (``assert_can_read``)."""
    await service.authorize_read(protocol_id, principal)
    data = await service.get_public_pdf_bytes(protocol_id)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=protokoll-oeffentlich.pdf"},
    )
