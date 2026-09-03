"""arq worker task: finalize a protocol asynchronously, so `finalize` never blocks.

`render_protocol` builds the `ProtocolService` from the `ctx` dependencies (pytex, MinIO
and the mail queue). It runs the render and the send after the router set the protocol
to `rendering` and enqueued the job. A transient error (pytex 5xx, transport, storage)
raises `arq.Retry` with a linear backoff up to `pdf_max_tries`. A permanent error resets
the protocol to `draft`. The protocol is then finalizable again and never stays stuck in
`rendering`. The send belongs to the atomic finalization, so a failure rolls back
everything. After a success and after a rollback the task broadcasts `meeting_state` on
`meeting:{id}`, so live followers see the status change.
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
from app.modules.files.storage import build_object_storage
from app.modules.livevote.broker import RedisBroker
from app.modules.livevote.events import MeetingStateEvent
from app.modules.livevote.models import Meeting
from app.modules.livevote.service import meeting_channel
from app.modules.notifications.queue import ArqMailQueue, MailQueue
from app.modules.pdf.pytex_client import build_pytex_client
from app.modules.protocol.models import Protocol
from app.modules.protocol.service import ProtocolService
from app.settings import Settings, load_settings
from app.shared.errors import ServiceUnavailableError

logger = logging.getLogger("app.protocol")


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via `ctx['protocol_sessionmaker']`)."""
    maker = ctx.get("protocol_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _mail_queue(ctx: dict[str, Any]) -> MailQueue | None:
    """Return the mail queue over the same Redis pool that arq uses in the worker."""
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
    """Set the protocol from `rendering` back to `draft`.

    The function opens a fresh session, because the job session already rolled back.
    """
    maker = _sessionmaker(ctx)
    async with maker() as session:
        await ProtocolService(session).revert_to_draft(protocol_id)


async def _broadcast_meeting_state(ctx: dict[str, Any], protocol_id: UUID) -> None:
    """Publish the `meeting_state` event of the meeting, so the frontend sees the status.

    The call is best effort. A broadcast error must not fail a render or a rollback that
    already completed.
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
        # Text column. The service constrains the values to the allowed literals.
        status=cast("Any", meeting.status),
    )
    try:
        await RedisBroker(redis).publish(meeting_channel(meeting.id), event.dump())
    except Exception as exc:  # noqa: BLE001 - broadcast is not render-critical
        logger.warning(
            "meeting_state broadcast failed (protocol=%s): %s", protocol_id, exc
        )


async def render_protocol(ctx: dict[str, Any], protocol_id: str) -> str:
    """Finalize a protocol in the `rendering` status: render the PDF and send it.

    A transient error retries up to `pdf_max_tries`. A permanent error rolls the protocol
    back to `draft`.

    Returns:
        `"final"` after the send, `"dead"` after the last failed try, or `"failed"` after
        a permanent error.
    """
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


async def on_startup(ctx: dict[str, Any]) -> None:
    """Build the render dependencies once per worker.

    The pytex client and the object storage were set up by the application-PDF task,
    which no longer exists. Protocols render through the same two, so the setup moved
    here rather than going with it.
    """
    settings = load_settings()
    ctx["settings"] = settings
    ctx["pytex_client"] = build_pytex_client(settings)
    ctx["object_storage"] = build_object_storage(settings)
