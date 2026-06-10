"""arq-Worker-Task: Protokoll finalisieren (T-22, async — ``finalize`` blockiert nie).

``render_protocol`` baut den :class:`ProtocolService` aus den in ``ctx`` hinterlegten
T-20-Deps (pytex + MinIO + Mail-Queue) und führt den eigentlichen Render+Versand
aus, nachdem der Router das Protokoll auf ``rendering`` gesetzt und den Job enqueued
hat. Transiente Fehler (pytex 5xx/Transport, Storage) → ``arq.Retry`` mit linearem
Backoff bis ``pdf_max_tries``; **jeder dauerhafte Fehler setzt das Protokoll auf
``draft`` zurück** (re-finalisierbar, nie in ``rendering`` hängen — der Versand
gehört zur atomaren Finalisierung, ein Fehlschlag rollt alles zurück). Nach Erfolg
**und** Rollback wird ``meeting_state`` auf ``meeting:{id}`` gebroadcastet, damit
Live-Follower den Status-Flip sehen (das FE lädt das Protokoll daraufhin nach).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from arq import Retry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.livevote.broker import RedisBroker
from app.modules.livevote.events import MeetingStateEvent
from app.modules.livevote.models import Meeting
from app.modules.livevote.service import meeting_channel
from app.modules.notifications.queue import ArqMailQueue, MailQueue
from app.modules.protocol.models import Protocol
from app.modules.protocol.service import ProtocolService
from app.settings import Settings
from app.shared.errors import ServiceUnavailableError

logger = logging.getLogger("app.protocol")


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """DB-Sessionmaker (in Tests via ``ctx['protocol_sessionmaker']`` injizierbar)."""
    maker = ctx.get("protocol_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _mail_queue(ctx: dict[str, Any]) -> MailQueue | None:
    """Mail-Queue über denselben Redis (arq-Pool des Workers)."""
    redis = ctx.get("redis")
    return ArqMailQueue(redis) if redis is not None else None


def _service(ctx: dict[str, Any], session: AsyncSession) -> ProtocolService:
    return ProtocolService(
        session,
        storage=ctx.get("object_storage"),
        pytex=ctx.get("pytex_client"),
        mail_queue=_mail_queue(ctx),
        settings=ctx.get("settings"),
    )


async def _revert_to_draft(ctx: dict[str, Any], protocol_id: UUID) -> None:
    """``rendering → draft`` in frischer Session (die Job-Session ist gerollbackt)."""
    maker = _sessionmaker(ctx)
    async with maker() as session:
        await ProtocolService(session).revert_to_draft(protocol_id)


async def _broadcast_meeting_state(ctx: dict[str, Any], protocol_id: UUID) -> None:
    """``meeting_state`` der zugehörigen Sitzung publizieren (Status-Flip fürs FE).

    Best effort: ein Broadcast-Fehler darf den (bereits abgeschlossenen)
    Render/Rollback nicht rückwirkend als fehlgeschlagen markieren."""
    redis = ctx.get("redis")
    if redis is None:
        return
    maker = _sessionmaker(ctx)
    async with maker() as session:
        meeting = (
            await session.execute(
                select(Meeting)
                .join(Protocol, Protocol.meeting_id == Meeting.id)
                .where(Protocol.id == protocol_id)
            )
        ).scalar_one_or_none()
    if meeting is None:
        return
    event = MeetingStateEvent(
        activeApplicationId=meeting.active_application_id,
        # Text-Spalte; Werte sind durch den Service auf die Literale beschränkt.
        status=cast("Any", meeting.status),
    )
    try:
        await RedisBroker(redis).publish(meeting_channel(meeting.id), event.dump())
    except Exception as exc:  # noqa: BLE001 — Broadcast ist nicht render-kritisch
        logger.warning(
            "meeting_state broadcast failed (protocol=%s): %s", protocol_id, exc
        )


async def render_protocol(ctx: dict[str, Any], protocol_id: str) -> str:
    """Ein ``rendering``-Protokoll finalisieren (PDF + Mail). Retry bei transientem
    Fehler bis ``pdf_max_tries``; dauerhafter Fehler → Rollback auf ``draft``."""
    settings: Settings = ctx["settings"]
    pid = UUID(protocol_id)
    try:
        maker = _sessionmaker(ctx)
        async with maker() as session:
            await _service(ctx, session).finalize(pid, now=datetime.now(UTC))
    except ServiceUnavailableError as exc:
        job_try = int(ctx.get("job_try", 1))
        if job_try < settings.pdf_max_tries:
            defer = settings.pdf_retry_backoff_seconds * job_try
            logger.warning(
                "protocol render failed (try=%s, retry in %ss, protocol=%s): %s",
                job_try,
                defer,
                protocol_id,
                exc,
            )
            raise Retry(defer=defer) from exc
        logger.error(
            "protocol render failed permanently after %s tries (protocol=%s): %s",
            job_try,
            protocol_id,
            exc,
        )
        await _revert_to_draft(ctx, pid)
        await _broadcast_meeting_state(ctx, pid)
        return "dead"
    except Exception as exc:  # noqa: BLE001 — dauerhaft (z. B. pytex-Compile-Fehler)
        logger.error(
            "protocol render failed permanently (protocol=%s): %s", protocol_id, exc
        )
        await _revert_to_draft(ctx, pid)
        await _broadcast_meeting_state(ctx, pid)
        return "failed"
    await _broadcast_meeting_state(ctx, pid)
    return "final"
