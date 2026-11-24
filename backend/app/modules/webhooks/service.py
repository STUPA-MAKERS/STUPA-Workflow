"""Webhook delivery service.

`emit_event` (module `events`) creates the `pending` deliveries in the transaction of a
domain event. This service has the two jobs after that.

* `enqueue_pending` runs in the worker cron. It hands each `pending` delivery without an
  attempt to the queue. The job key `webhook:<id>` coalesces a second enqueue of a
  delivery whose job is still queued or running, so a sweep is harmless.
* `deliver` runs in the worker job. It sends one delivery: SSRF guard at send time,
  HMAC signature, POST without redirects, and a write-back of status, attempts and
  backoff. It returns a `DeliveryOutcome`. The worker translates `retry` into
  `arq.Retry`. A delivery that is already `ok` or `dead` gives `gone`, so a late
  second job sends nothing twice (§F/integrations/webhooks/000299).

The service never logs the per-webhook `secret`.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy import select

from app.modules.webhooks.models import Webhook, WebhookDelivery
from app.modules.webhooks.signing import build_headers, canonical_body
from app.shared.ssrf import (
    Resolver,
    SsrfError,
    assert_allowed_url,
    default_resolver,
    pin_url,
)

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.webhooks.queue import WebhookQueue
    from app.settings import Settings

logger = logging.getLogger("app.webhooks")

OutcomeKind = Literal["ok", "retry", "dead", "gone"]

#: Cap of a read response body. Only the status code matters, and a malicious receiver
#: could OOM-kill the shared worker with a multi-GB body, so the reader stops here.
_MAX_RESPONSE_BYTES = 64 * 1024

#: The most deliveries that one sweep enqueues. The next sweep takes the rest.
_SWEEP_LIMIT = 500

#: The states that end a delivery. A job for such a row sends nothing.
_FINAL = frozenset({"ok", "dead"})


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """Result of a delivery attempt.

    Attributes:
        defer: The backoff in seconds. Set only on a `retry` outcome.
    """

    kind: OutcomeKind
    attempts: int = 0
    response_code: int | None = None
    defer: int | None = None


@dataclass(frozen=True, slots=True)
class WebhookService:
    """Deliver outgoing webhooks: create the delivery rows and send them from the worker."""

    session: AsyncSession
    settings: Settings
    queue: WebhookQueue | None = None

    async def enqueue_pending(self, *, older_than: dt.datetime) -> int:
        """Enqueue every `pending` delivery without an attempt created before `older_than`.

        The grace time keeps the sweep away from a row whose transaction is still open.

        Returns:
            The number of enqueued deliveries; 0 without a queue.
        """
        if self.queue is None:
            return 0
        ids = (
            await self.session.scalars(
                select(WebhookDelivery.id)
                .where(
                    WebhookDelivery.status == "pending",
                    WebhookDelivery.attempts == 0,
                    WebhookDelivery.created_at < older_than,
                )
                .order_by(WebhookDelivery.created_at)
                .limit(_SWEEP_LIMIT)
            )
        ).all()
        for delivery_id in ids:
            await self.queue.enqueue(delivery_id)
        return len(ids)

    async def deliver(
        self,
        delivery_id: UUID,
        *,
        http_client: httpx.AsyncClient,
        resolver: Resolver = default_resolver,
        now: dt.datetime | None = None,
    ) -> DeliveryOutcome:
        """Send one delivery from the worker and persist the resulting status.

        A security block of the target is permanent, so it is not retried. Its log line
        drops the error detail, because the detail holds the host and the resolved IP
        and would leak the internal network topology. The connection is pinned to the
        validated IP against DNS rebinding, so the client does no second resolution; the
        Host header and the TLS SNI keep the original host.
        """
        import httpx

        moment = now or dt.datetime.now(tz=dt.UTC)
        delivery = await self.session.get(WebhookDelivery, delivery_id)
        if delivery is None or delivery.status in _FINAL:
            logger.info("webhook delivery %s gone or final — skipped", delivery_id)
            return DeliveryOutcome(kind="gone")

        hook = await self.session.get(Webhook, delivery.webhook_id)
        if hook is None or not hook.active or hook.secret is None:
            return await self._finish(delivery, "dead", moment, response_code=None)

        try:
            ips = assert_allowed_url(
                hook.url,
                allowlist=self.settings.webhook_host_allowlist,
                resolver=resolver,
            )
        except SsrfError:
            logger.warning(
                "webhook delivery %s (webhook=%s) blocked by ssrf guard",
                delivery_id,
                delivery.webhook_id,
            )
            return await self._finish(delivery, "dead", moment, response_code=None)

        ip_url, host_header = pin_url(hook.url, ips[0])
        body = canonical_body(delivery.payload)
        signed = build_headers(
            hook.secret, body, event=delivery.event, timestamp=int(moment.timestamp())
        )
        request = http_client.build_request(
            "POST",
            ip_url,
            content=body,
            headers={**signed, "Host": host_header},
            extensions={"sni_hostname": host_header.rsplit(":", 1)[0]},
        )
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

    async def _send_capped(self, http_client: httpx.AsyncClient, request: httpx.Request) -> int:
        """POST the request and return only the status code.

        The method streams the response body and stops at `_MAX_RESPONSE_BYTES`. That
        cap protects the worker against an out-of-memory kill. The body content stays
        unused. The clean `aclose` keeps connection reuse intact.

        `aiter_bytes` with a chunk size of `_MAX_RESPONSE_BYTES` buffers the stream until
        it holds the cap or the stream ends, so reading its first chunk reads up to the
        cap. A body without content gives no chunk at all, hence the default `b""`.

        The httpx timeout counts per read and restarts on every chunk. A malicious
        receiver could drip one byte per interval, hold the stream open without end and
        block the shared arq worker slot. That is a denial of service. Therefore
        `asyncio.timeout` puts one hard total deadline over all reads.

        Raises:
            httpx.TimeoutException: The total deadline expired. `deliver` handles this
                like a transient transport error and retries.
        """
        import httpx

        try:
            async with asyncio.timeout(self.settings.webhook_timeout_seconds):
                response = await http_client.send(request, stream=True)
                try:
                    await anext(response.aiter_bytes(_MAX_RESPONSE_BYTES), b"")
                    return response.status_code
                finally:
                    await response.aclose()
        except TimeoutError as exc:
            raise httpx.TimeoutException("webhook delivery exceeded total deadline") from exc

    async def _classify(
        self,
        delivery: WebhookDelivery,
        moment: dt.datetime,
        status_code: int,
        delivery_id: UUID,
    ) -> DeliveryOutcome:
        """Map the status code to a final state or to a retry.

        A 3xx or 4xx goes to the dead-letter state at once, because a retry does not
        change it: the client follows no redirect, and a 4xx is a client or config
        error. A 5xx and a 1xx retry (§F/integrations/webhooks/000298).
        """
        match status_code // 100:
            case 2:
                return await self._finish(delivery, "ok", moment, response_code=status_code)
            case 3 | 4:
                logger.warning(
                    "webhook delivery %s dead — non-retryable %s",
                    delivery_id,
                    status_code,
                )
                return await self._finish(
                    delivery,
                    "dead",
                    moment,
                    response_code=status_code,
                    attempts=delivery.attempts + 1,
                )
            case _:
                return await self._fail(delivery, moment, response_code=status_code)

    async def _fail(
        self, delivery: WebhookDelivery, moment: dt.datetime, *, response_code: int | None
    ) -> DeliveryOutcome:
        """Record a failed attempt and retry with backoff until the tries run out.

        The last failed attempt moves the delivery to the dead-letter state.
        """
        attempts = delivery.attempts + 1
        if attempts >= self.settings.webhook_max_tries:
            return await self._finish(
                delivery, "dead", moment, response_code=response_code, attempts=attempts
            )
        defer = self.settings.webhook_retry_backoff_seconds * (2 ** (attempts - 1))
        await self._record(
            delivery, "failed", moment, response_code=response_code, attempts=attempts
        )
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
        """Write the final state `ok` or `dead` and stop any further attempt."""
        final_attempts = delivery.attempts if attempts is None else attempts
        await self._record(
            delivery, kind, moment, response_code=response_code, attempts=final_attempts
        )
        return DeliveryOutcome(kind=kind, attempts=final_attempts, response_code=response_code)

    async def _record(
        self,
        delivery: WebhookDelivery,
        status: Literal["ok", "dead", "failed"],
        moment: dt.datetime,
        *,
        response_code: int | None,
        attempts: int,
    ) -> None:
        """Write the attempt result onto the delivery row and commit it."""
        delivery.attempts = attempts
        delivery.status = status
        delivery.last_at = moment
        delivery.response_code = response_code
        await self.session.commit()
