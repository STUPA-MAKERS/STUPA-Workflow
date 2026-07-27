"""Webhook dispatch service.

The service has two strictly separated jobs.

* `dispatch_event` runs on the API and flow side. It finds the active webhooks that
  subscribe to a domain event. It creates one `webhook_delivery` row in state `pending`
  per webhook and enqueues a `deliver_webhook` job. It is idempotent over
  `(webhook_id, idempotency_key)`. A flow retry of the same status event creates no
  duplicate delivery.
* `deliver` runs on the worker side. It sends one delivery: SSRF guard at send time,
  HMAC signature, POST without redirects, and a write-back of status, attempts and
  backoff. It returns a `DeliveryOutcome`. The worker translates `retry` into
  `arq.Retry`.

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

# Only the HTTP status code matters. The code never reads the response body for content.
# A malicious or compromised receiver could OOM-kill the shared arq worker with a
# multi-GB body, so the reader streams the body and stops at this hard limit.
_MAX_RESPONSE_BYTES = 64 * 1024


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


@dataclass(slots=True)
class WebhookService:
    session: AsyncSession
    settings: Settings
    queue: WebhookQueue | None = None

    async def dispatch_event(
        self,
        event: str,
        *,
        payload: dict[str, object] | None = None,
        idempotency_base: str | None = None,
    ) -> int:
        """Create one delivery and one job per active webhook that subscribes to `event`.

        Returns:
            The number of new deliveries. A delivery that the dedup skips does not count.
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
            # One savepoint per delivery. A concurrent insert violates the
            # `unique(webhook_id, idempotency_key)` constraint. Another run then already
            # created and enqueued the delivery, so skip it instead of losing the batch.
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
        """Create and enqueue a delivery for exactly one active webhook.

        The flow action `webhook` references a webhook by id. An admin maintains that
        webhook under `/admin/webhooks`. The dedup runs over
        `(webhook_id, idempotency_key)`.

        Returns:
            The number of new deliveries. A missing or inactive webhook gives `0`, and
            the service skips it without an error.
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
        """Return the idempotency keys of this event that exist already.

        The query uses an `IN` over the concrete candidate keys. It does not scan every
        delivery ever created for the event. The cost therefore stays at the order of the
        number of webhooks and does not grow with the delivery history. The constraint
        `unique(webhook_id, idempotency_key)` and the savepoint give correctness on their
        own. This pre-check is only an optimization.
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

    async def deliver(
        self,
        delivery_id: UUID,
        *,
        http_client: httpx.AsyncClient,
        resolver: Resolver = default_resolver,
        now: dt.datetime | None = None,
    ) -> DeliveryOutcome:
        """Send one delivery from the worker and persist the resulting status."""
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
            # A security block is permanent, so do not retry. The target does not change.
            # The log line drops the error detail on purpose. That detail holds the host
            # and the resolved IP and would leak the internal network topology.
            logger.warning(
                "webhook delivery %s (webhook=%s) blocked by ssrf guard",
                delivery_id,
                delivery.webhook_id,
            )
            return await self._finish(delivery, "dead", moment, response_code=None)

        # Pin against DNS rebinding. Connect to the validated IP and let the client do no
        # second resolution. The Host header and the TLS SNI keep the original host.
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
        """POST the request and return only the status code.

        The method streams the response body and stops at `_MAX_RESPONSE_BYTES`. That
        cap protects the worker against an out-of-memory kill. The body content stays
        unused. The clean `aclose` keeps connection reuse intact.

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
                    read = 0
                    async for chunk in response.aiter_bytes():
                        read += len(chunk)
                        if read >= _MAX_RESPONSE_BYTES:
                            # The body is too large. Stop, the status code is known.
                            break
                    return response.status_code
                finally:
                    await response.aclose()
        except TimeoutError as exc:
            # The total deadline expired. Treat it like a transport timeout and retry.
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
        """Map the status code to a final state or to a retry."""
        if 200 <= status_code < 300:
            return await self._finish(
                delivery, "ok", moment, response_code=status_code
            )
        if 400 <= status_code < 500:
            # A 4xx is a client error or a config error. A retry changes nothing, so go
            # to the dead-letter state at once.
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
        """Record a failed attempt and retry with backoff until the tries run out.

        The last failed attempt moves the delivery to the dead-letter state.
        """
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
        """Write the final state `ok` or `dead` and stop any further attempt."""
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
