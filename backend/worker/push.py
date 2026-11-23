"""arq worker task: web push dispatch (§F/collaboration/notifications/002506, 002510).

`send_push` delivers one push job to one device through `PushDelivery`. A device that
the push service reports as gone (404/410) is deleted and never retried. 429, a 5xx or
a network error retries with a linear backoff up to `mail_max_tries`; after that the
job is dead and the worker logs it. A push is a hint next to the mail, so a dead push
loses nothing that the mail does not carry.
"""

from __future__ import annotations

import logging
from typing import Any

from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.notifications.push_sender import HttpPushPoster, PushDelivery, PushPoster
from app.modules.notifications.push_service import PushJob
from app.settings import Settings

logger = logging.getLogger("app.push")


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via `ctx['push_sessionmaker']`)."""
    maker = ctx.get("push_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _poster(ctx: dict[str, Any]) -> PushPoster:
    """Return the poster (tests inject one via `ctx['push_poster']`)."""
    poster = ctx.get("push_poster")
    return poster if poster is not None else HttpPushPoster()


async def send_push(ctx: dict[str, Any], payload: dict[str, object]) -> str:
    """Send one push to one device.

    Returns:
        The outcome: ``sent``, ``gone``, ``refused`` or ``dead`` after the last try.

    Raises:
        Retry: The push service asked to wait (429), failed (5xx) or was unreachable.
    """
    settings: Settings = ctx["settings"]
    job = PushJob.from_payload(payload)
    async with _sessionmaker(ctx)() as session:
        result = await PushDelivery(session, settings, _poster(ctx)).deliver(job)
        await session.commit()
    if result.outcome != "retry":
        return result.outcome
    job_try = int(ctx.get("job_try", 1))
    if job_try >= settings.mail_max_tries:
        logger.error("push failed permanently after %s tries (status=%s)", job_try, result.status)
        return "dead"
    raise Retry(defer=settings.mail_retry_backoff_seconds * job_try)
