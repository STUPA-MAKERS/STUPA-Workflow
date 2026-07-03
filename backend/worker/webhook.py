"""arq worker task: webhook delivery.

``deliver_webhook`` loads the ``webhook_delivery``, re-checks the SSRF guard at send
time (DNS rebinding), signs HMAC-SHA256 and POSTs without following redirects. Status
and backoff live in :class:`WebhookService`; transient errors (timeout/transport/
non-2xx) -> ``arq.Retry`` with exponential backoff up to ``webhook_max_tries``, then
dead-letter (``status=dead``). An SSRF block is permanent (no retry). Idempotency comes
from the job key (``webhook:<id>``); re-running an already-delivered delivery is harmless.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx
from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.webhooks.service import WebhookService
from app.settings import Settings, load_settings

logger = logging.getLogger("app.webhooks")


async def on_startup(ctx: dict[str, Any]) -> None:
    ctx["settings"] = load_settings()


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """DB sessionmaker (injectable in tests via ``ctx['webhook_sessionmaker']``)."""
    maker = ctx.get("webhook_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


async def deliver_webhook(ctx: dict[str, Any], delivery_id: str) -> str:
    """Deliver one webhook. Retry on transient error, else terminal."""
    settings: Settings = ctx["settings"]
    did = UUID(delivery_id)
    maker = _sessionmaker(ctx)
    client_factory = ctx.get("webhook_client_factory") or _default_client_factory
    async with maker() as session:
        service = WebhookService(session, settings)
        async with client_factory(settings) as client:
            outcome = await service.deliver(did, http_client=client)

    if outcome.kind == "retry":
        defer = outcome.defer or settings.webhook_retry_backoff_seconds
        logger.warning(
            "webhook delivery %s failed (attempt=%s, code=%s) — retry in %ss",
            delivery_id,
            outcome.attempts,
            outcome.response_code,
            defer,
        )
        raise Retry(defer=defer)
    if outcome.kind == "dead":
        logger.error(
            "webhook delivery %s dead after %s attempt(s) (code=%s)",
            delivery_id,
            outcome.attempts,
            outcome.response_code,
        )
    return outcome.kind


def _default_client_factory(settings: Settings) -> httpx.AsyncClient:  # pragma: no cover
    """httpx client that never follows redirects, with a fixed timeout."""
    return httpx.AsyncClient(
        follow_redirects=False, timeout=settings.webhook_timeout_seconds
    )
