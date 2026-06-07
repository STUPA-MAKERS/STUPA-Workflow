"""arq-Worker-Task: Webhook-Zustellung (T-19, security.md §5 / flows §8).

``deliver_webhook`` lädt die ``webhook_delivery``, prüft den SSRF-Guard **zur Sende-
Zeit** (DNS-Rebinding), signiert HMAC-SHA256 und stellt per HTTP-POST **ohne Redirects**
zu. Das Status-/Backoff-Handling liegt im :class:`WebhookService`; transiente Fehler
(Timeout/Transport/Non-2xx) → ``arq.Retry`` mit exponentiellem Backoff bis
``webhook_max_tries``, danach Dead-Letter (``status=dead``). Der SSRF-Block ist
permanent (kein Retry). Idempotenz trägt der Job-Key (``webhook:<id>``); ein erneuter
Lauf auf bereits zugestellter Delivery ist harmlos (Status terminal).
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
    """DB-Sessionmaker (in Tests via ``ctx['webhook_sessionmaker']`` injizierbar)."""
    maker = ctx.get("webhook_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


async def deliver_webhook(ctx: dict[str, Any], delivery_id: str) -> str:
    """Eine Webhook-Delivery zustellen. Retry bei transientem Fehler, sonst terminal."""
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
    """httpx-Client ohne Redirect-Folgen + festem Timeout (security.md §5)."""
    return httpx.AsyncClient(
        follow_redirects=False, timeout=settings.webhook_timeout_seconds
    )
