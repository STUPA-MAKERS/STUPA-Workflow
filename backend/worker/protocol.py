"""arq worker task: finalize a protocol (async — ``finalize`` never blocks).

``render_protocol`` builds the :class:`ProtocolService` from the ``ctx`` deps (pytex
+ MinIO + mail queue) and runs the render+send after the router set the protocol to
``rendering`` and enqueued the job. Transient errors (pytex 5xx/transport, storage)
-> ``arq.Retry`` with linear backoff up to ``pdf_max_tries``; any permanent error
resets the protocol to ``draft`` (re-finalizable, never stuck in ``rendering`` — the
send is part of the atomic finalization, a failure rolls everything back). After both
success and rollback, ``meeting_state`` is broadcast on ``meeting:{id}`` so live
followers see the status flip.
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
    """DB sessionmaker (injectable in tests via ``ctx['protocol_sessionmaker']``)."""
    maker = ctx.get("protocol_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _mail_queue(ctx: dict[str, Any]) -> MailQueue | None:
    """Mail queue over the same Redis (the worker's arq pool)."""
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
    """``rendering -> draft`` in a fresh session (the job session is rolled back)."""
    maker = _sessionmaker(ctx)
    async with maker() as session:
        await ProtocolService(session).revert_to_draft(protocol_id)


async def _broadcast_meeting_state(ctx: dict[str, Any], protocol_id: UUID) -> None:
    """Publish the meeting's ``meeting_state`` (status flip for the FE).

    Best effort: a broadcast error must not retroactively fail the already-completed
    render/rollback.
    """
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
        # Text column; the service constrains values to the allowed literals.
        status=cast("Any", meeting.status),
    )
    try:
        await RedisBroker(redis).publish(meeting_channel(meeting.id), event.dump())
    except Exception as exc:  # noqa: BLE001 - broadcast is not render-critical
        logger.warning(
            "meeting_state broadcast failed (protocol=%s): %s", protocol_id, exc
        )


async def render_protocol(ctx: dict[str, Any], protocol_id: str) -> str:
    """Finalize a ``rendering`` protocol (PDF + mail). Retry on transient error up to
    ``pdf_max_tries``; permanent error -> rollback to ``draft``."""
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
    except Exception as exc:  # noqa: BLE001 - permanent (e.g. pytex compile error)
        logger.error(
            "protocol render failed permanently (protocol=%s): %s", protocol_id, exc
        )
        await _revert_to_draft(ctx, pid)
        await _broadcast_meeting_state(ctx, pid)
        return "failed"
    await _broadcast_meeting_state(ctx, pid)
    return "final"
