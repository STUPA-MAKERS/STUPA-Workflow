"""Webhook dispatch service.

Two strictly separated jobs:
* ``dispatch_event`` (API/flow side) - find the active, subscribed webhooks for a domain
  event, create one ``webhook_delivery`` (``pending``) per webhook and enqueue a
  ``deliver_webhook`` job. Idempotent over ``(webhook_id, idempotency_key)``: a flow
  retry of the same status event creates no duplicate delivery.
* ``deliver`` (worker side) - deliver one delivery: SSRF guard at send time, HMAC
  signature, POST without redirects, write back status/attempts/backoff. Returns a
  ``DeliveryOutcome``; the worker translates ``retry`` into ``arq.Retry``.

The per-webhook ``secret`` is never logged.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.admin.models import Webhook, WebhookDelivery
from app.modules.webhooks.signing import build_headers, canonical_body
from app.modules.webhooks.ssrf import (
    Resolver,
    SsrfError,
    assert_allowed_url,
    default_resolver,
    pin_url,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.webhooks.queue import WebhookQueue
    from app.settings import Settings

logger = logging.getLogger("app.webhooks")

OutcomeKind = Literal["ok", "retry", "dead", "gone"]

# We only use the HTTP status code; the response body is never used. A malicious/
# compromised receiver could OOM-kill the (shared) arq worker with a multi-GB body, so
# read the body streamed and stop at this hard limit.
_MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """Result of a delivery attempt. ``defer`` = backoff seconds on ``retry``."""

    kind: OutcomeKind
    attempts: int = 0
    response_code: int | None = None
    defer: int | None = None


@dataclass(slots=True)
class WebhookService:
    session: AsyncSession
    settings: Settings
    queue: WebhookQueue | None = None

    # --- dispatch ---
    async def dispatch_event(
        self,
        event: str,
        *,
        payload: dict[str, object] | None = None,
        idempotency_base: str | None = None,
    ) -> int:
        """Active webhooks subscribed to ``event`` -> one delivery + job each.

        Returns the number of newly created deliveries (dedup-skipped ones don't count).
        """
        webhooks = (
            await self.session.scalars(
                select(Webhook).where(
                    Webhook.active.is_(True), Webhook.events.contains([event])
                )
            )
        ).all()
        if not webhooks:
            return 0

        candidate_keys = (
            [f"{idempotency_base}:{hook.id}" for hook in webhooks]
            if idempotency_base
            else []
        )
        existing = await self._existing_keys(event, candidate_keys)
        body = dict(payload or {})
        created: list[WebhookDelivery] = []
        for hook in webhooks:
            key = f"{idempotency_base}:{hook.id}" if idempotency_base else None
            if key is not None and key in existing:
                logger.info("webhook delivery deduped (event=%s hook=%s)", event, hook.id)
                continue
            delivery = WebhookDelivery(
                webhook_id=hook.id,
                event=event,
                payload=body,
                status="pending",
                attempts=0,
                idempotency_key=key,
            )
            # Savepoint per delivery: a concurrent insert violates
            # unique(webhook_id, idempotency_key) - the delivery is then already created
            # by another run (= already enqueued), so skip it instead of losing the batch.
            try:
                async with self.session.begin_nested():
                    self.session.add(delivery)
                    await self.session.flush()
            except IntegrityError:
                logger.info(
                    "webhook delivery race-deduped (event=%s hook=%s)", event, hook.id
                )
                continue
            created.append(delivery)

        if not created:
            return 0
        await self.session.commit()

        if self.queue is None:
            logger.info(
                "webhook queue unavailable — %d delivery(ies) stay pending (event=%s)",
                len(created),
                event,
            )
        else:
            for delivery in created:
                await self.queue.enqueue(delivery.id)
        return len(created)

    async def dispatch_to_webhook(
        self,
        webhook_id: UUID,
        *,
        event: str,
        payload: dict[str, object] | None = None,
        idempotency_base: str | None = None,
    ) -> int:
        """Create + enqueue a delivery for exactly one (active) webhook.

        The flow action ``webhook`` references a webhook maintained under
        ``/admin/webhooks`` by id. Missing/inactive -> ``0`` (silently skipped). Dedup
        over ``(webhook_id, idempotency_key)``.
        """
        hook = await self.session.get(Webhook, webhook_id)
        if hook is None or not hook.active:
            logger.warning(
                "webhook %s missing/inactive — flow action skipped", webhook_id
            )
            return 0
        key = f"{idempotency_base}:{hook.id}" if idempotency_base else None
        if key is not None and key in await self._existing_keys(event, [key]):
            logger.info("webhook delivery deduped (event=%s hook=%s)", event, hook.id)
            return 0
        delivery = WebhookDelivery(
            webhook_id=hook.id,
            event=event,
            payload=dict(payload or {}),
            status="pending",
            attempts=0,
            idempotency_key=key,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(delivery)
                await self.session.flush()
        except IntegrityError:
            logger.info("webhook delivery race-deduped (event=%s hook=%s)", event, hook.id)
            return 0
        await self.session.commit()
        if self.queue is not None:
            await self.queue.enqueue(delivery.id)
        return 1

    async def _existing_keys(
        self, event: str, candidate_keys: Sequence[str]
    ) -> set[str]:
        """Already-used idempotency keys for this event (dedup pre-check).

        Scoped to the concrete candidate keys (``IN``), not all deliveries ever created
        for the event, so the query stays O(#webhooks) instead of growing with delivery
        history. Correctness is guaranteed by ``unique(webhook_id, idempotency_key)`` +
        savepoint anyway; this pre-check is only an optimization.
        """
        if not candidate_keys:
            return set()
        rows = (
            await self.session.scalars(
                select(WebhookDelivery.idempotency_key).where(
                    WebhookDelivery.event == event,
                    WebhookDelivery.idempotency_key.in_(candidate_keys),
                )
            )
        ).all()
        return {k for k in rows if k is not None}

    # --- deliver ---
    async def deliver(
        self,
        delivery_id: UUID,
        *,
        http_client: httpx.AsyncClient,
        resolver: Resolver = default_resolver,
        now: dt.datetime | None = None,
    ) -> DeliveryOutcome:
        """Deliver one delivery and persist the status (worker)."""
        import httpx

        moment = now or dt.datetime.now(tz=dt.UTC)
        delivery = await self.session.get(WebhookDelivery, delivery_id)
        if delivery is None:
            logger.info("webhook delivery %s gone — skipped", delivery_id)
            return DeliveryOutcome(kind="gone")

        hook = await self.session.get(Webhook, delivery.webhook_id)
        if hook is None or not hook.active or hook.secret is None:
            return await self._finish(
                delivery, "dead", moment, response_code=None
            )

        try:
            ips = assert_allowed_url(
                hook.url,
                allowlist=self.settings.webhook_host_allowlist,
                resolver=resolver,
            )
        except SsrfError:
            # Security block is permanent - no retry (the target does not change).
            # Deliberately without error detail: it contains host/resolved IP and would
            # leak internal network topology into the logs.
            logger.warning(
                "webhook delivery %s (webhook=%s) blocked by ssrf guard",
                delivery_id,
                delivery.webhook_id,
            )
            return await self._finish(delivery, "dead", moment, response_code=None)

        # DNS-rebinding pinning: connect to the validated IP (no client re-resolution);
        # Host/TLS SNI stays the original host.
        ip_url, host_header = pin_url(hook.url, ips[0])
        body = canonical_body(delivery.payload)
        headers = build_headers(
            hook.secret, body, event=delivery.event, timestamp=int(moment.timestamp())
        )
        headers["Host"] = host_header
        request = http_client.build_request("POST", ip_url, content=body, headers=headers)
        request.extensions["sni_hostname"] = host_header.rsplit(":", 1)[0]
        try:
            status_code = await self._send_capped(http_client, request)
        except httpx.HTTPError as exc:
            logger.warning(
                "webhook delivery %s transport error: %s",
                delivery_id,
                type(exc).__name__,
            )
            return await self._fail(delivery, moment, response_code=None)
        return await self._classify(delivery, moment, status_code, delivery_id)

    async def _send_capped(
        self, http_client: httpx.AsyncClient, request: httpx.Request
    ) -> int:
        """POST and return only the status code - read the body streamed and capped at
        ``_MAX_RESPONSE_BYTES`` (OOM protection).

        The body is never used; we read only until the limit and then close the stream.
        Connection reuse stays intact via the clean ``aclose`` (context manager).

        The httpx timeout is per read and resets on each chunk; a malicious slow-drip
        receiver (1 byte per interval) would otherwise hold the stream open indefinitely
        and block the shared arq worker slot (DoS). Hence a hard total deadline over all
        reads via ``asyncio.timeout``. Exceeding it is signalled as a transient transport
        error (``httpx.TimeoutException``) -> retry path in ``deliver``.
        """
        import httpx

        try:
            async with asyncio.timeout(self.settings.webhook_timeout_seconds):
                response = await http_client.send(request, stream=True)
                try:
                    read = 0
                    async for chunk in response.aiter_bytes():
                        read += len(chunk)
                        if read >= _MAX_RESPONSE_BYTES:
                            # Body too large: stop reading - the status code is known.
                            break
                    return response.status_code
                finally:
                    await response.aclose()
        except TimeoutError as exc:
            # Total deadline hit -> treat like a transport timeout (retry).
            raise httpx.TimeoutException(
                "webhook delivery exceeded total deadline"
            ) from exc

    async def _classify(
        self,
        delivery: WebhookDelivery,
        moment: dt.datetime,
        status_code: int,
        delivery_id: UUID,
    ) -> DeliveryOutcome:
        """Status code -> final state/retry."""
        if 200 <= status_code < 300:
            return await self._finish(
                delivery, "ok", moment, response_code=status_code
            )
        if 400 <= status_code < 500:
            # 4xx is a client/config error - a retry changes nothing -> immediate
            # dead-letter, no retry.
            logger.warning(
                "webhook delivery %s dead — non-retryable %s",
                delivery_id,
                status_code,
            )
            return await self._finish(
                delivery, "dead", moment, response_code=status_code,
                attempts=delivery.attempts + 1,
            )
        return await self._fail(delivery, moment, response_code=status_code)

    async def _fail(
        self, delivery: WebhookDelivery, moment: dt.datetime, *, response_code: int | None
    ) -> DeliveryOutcome:
        """Record a failed attempt: retry with backoff, or dead-letter on exhaustion."""
        attempts = delivery.attempts + 1
        if attempts >= self.settings.webhook_max_tries:
            return await self._finish(
                delivery, "dead", moment, response_code=response_code, attempts=attempts
            )
        defer = self.settings.webhook_retry_backoff_seconds * (2 ** (attempts - 1))
        next_at = moment + dt.timedelta(seconds=defer)
        delivery.attempts = attempts
        delivery.status = "failed"
        delivery.last_at = moment
        delivery.next_at = next_at
        delivery.response_code = response_code
        await self.session.commit()
        return DeliveryOutcome(
            kind="retry", attempts=attempts, response_code=response_code, defer=defer
        )

    async def _finish(
        self,
        delivery: WebhookDelivery,
        kind: Literal["ok", "dead"],
        moment: dt.datetime,
        *,
        response_code: int | None,
        attempts: int | None = None,
    ) -> DeliveryOutcome:
        """Write the final state (``ok``/``dead``) - no further attempt."""
        final_attempts = attempts if attempts is not None else delivery.attempts
        delivery.attempts = final_attempts
        delivery.status = kind
        delivery.last_at = moment
        delivery.next_at = None
        delivery.response_code = response_code
        await self.session.commit()
        return DeliveryOutcome(
            kind=kind, attempts=final_attempts, response_code=response_code
        )
