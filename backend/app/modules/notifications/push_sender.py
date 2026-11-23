"""Send one encrypted push to its push service (§F/collaboration/notifications/002510).

`PushDelivery.deliver` loads the device, encrypts the payload for it (RFC 8291), signs
the VAPID header and posts the body. The endpoint comes from the browser, so the post
goes through the SSRF guard to a pinned, checked IP, follows no redirect and keeps the
host for TLS. The outcome tells the worker what to do:

- ``sent``: the push service took the push.
- ``gone``: the push service answered 404 or 410, or the device is unknown; the device
  row is deleted (002506) and nothing retries.
- ``refused``: the endpoint is not a known push service, the guard blocked it, or the
  push service refused the request (another 4xx); nothing retries.
- ``retry``: 429, a 5xx or a network error; the worker retries with a backoff.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.push_models import PushSubscription
from app.modules.notifications.push_service import PushJob, PushService, endpoint_allowed
from app.modules.notifications.webpush import encrypt, now_seconds, vapid_authorization
from app.settings import Settings
from app.shared.ssrf import Resolver, SsrfError, assert_allowed_url, default_resolver, pin_url

logger = logging.getLogger("app.push")

#: The deadline of one post, DNS lookup included.
PUSH_TIMEOUT_SECONDS = 10.0

Outcome = Literal["sent", "gone", "refused", "retry"]


class PushPoster(Protocol):
    """Post one encrypted body to an endpoint and return the HTTP status."""

    async def post(self, endpoint: str, headers: dict[str, str], body: bytes) -> int:
        """Post ``body`` and return the status code."""
        ...


def _prefer_ipv4(ips: list[str]) -> str:
    """Pick the first IPv4 address, because a container often has no IPv6 route."""
    return next(
        (ip for ip in ips if isinstance(ipaddress.ip_address(ip), ipaddress.IPv4Address)),
        ips[0],
    )


@dataclass(frozen=True, slots=True)
class HttpPushPoster:
    """Post through the SSRF guard to the checked IP, without redirects.

    ``client_factory`` defaults to a client that follows no redirect, under the deadline.
    """

    timeout_seconds: float = PUSH_TIMEOUT_SECONDS
    resolver: Resolver = default_resolver
    client_factory: Callable[[], httpx.AsyncClient] | None = None

    def _client(self) -> httpx.AsyncClient:
        return (
            self.client_factory()
            if self.client_factory is not None
            else httpx.AsyncClient(
                follow_redirects=False, timeout=httpx.Timeout(self.timeout_seconds)
            )
        )

    async def post(self, endpoint: str, headers: dict[str, str], body: bytes) -> int:
        """Post ``body`` to ``endpoint``; raise `SsrfError` when the guard blocks it."""
        async with asyncio.timeout(self.timeout_seconds):
            ips = await asyncio.to_thread(assert_allowed_url, endpoint, resolver=self.resolver)
            ip_url, host_header = pin_url(endpoint, _prefer_ipv4(ips))
            async with self._client() as client:
                request = client.build_request(
                    "POST",
                    ip_url,
                    headers={**headers, "Host": host_header},
                    content=body,
                    extensions={"sni_hostname": urlsplit(endpoint).hostname or ""},
                )
                response = await client.send(request)
                return response.status_code


@dataclass(frozen=True, slots=True)
class PushResult:
    """The outcome of one delivery."""

    outcome: Outcome
    status: int | None = None


def vapid_subject(settings: Settings) -> str:
    """Return the VAPID contact: the public URL when it is https, else the sender address.

    A push service may refuse a request whose subject is neither ``https:`` nor
    ``mailto:``.
    """
    base = settings.public_base_url.rstrip("/")
    return base if base.startswith("https://") else f"mailto:{settings.mail_from}"


def outcome_of(status: int) -> Outcome:
    """Map the status of the push service to the outcome."""
    match status:
        case _ if 200 <= status < 300:
            return "sent"
        case 404 | 410:
            return "gone"
        case 429:
            return "retry"
        case _ if status >= 500:
            return "retry"
        case _:
            return "refused"


@dataclass(frozen=True, slots=True)
class PushDelivery:
    """Deliver push jobs with a session; the worker commits."""

    session: AsyncSession
    settings: Settings
    poster: PushPoster

    async def deliver(self, job: PushJob) -> PushResult:
        """Encrypt and post one job to its device; delete a gone or forged device."""
        row = await self.session.get(PushSubscription, uuid.UUID(job.subscription_id))
        if row is None:
            return PushResult("gone")
        if not endpoint_allowed(row.endpoint):
            await self.session.delete(row)
            return PushResult("refused")
        keys = await PushService(self.session, self.settings).vapid_keys()
        headers = {
            "TTL": str(job.ttl),
            "Urgency": job.urgency,
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "Authorization": vapid_authorization(
                row.endpoint, keys, vapid_subject(self.settings), now=now_seconds()
            ),
        }
        body = encrypt(job.payload.encode("utf-8"), p256dh=row.p256dh, auth=row.auth)
        try:
            status = await self.poster.post(row.endpoint, headers, body)
        except SsrfError:
            logger.warning("push blocked by the ssrf guard")
            return PushResult("refused")
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("push post failed: %s", type(exc).__name__)
            return PushResult("retry")
        outcome = outcome_of(status)
        match outcome:
            case "sent":
                await self.session.execute(
                    update(PushSubscription)
                    .where(PushSubscription.id == row.id)
                    .values(last_success_at=datetime.now(UTC))
                )
            case "gone":
                await self.session.delete(row)
            case "refused" | "retry":
                logger.warning("push service answered %s", status)
        return PushResult(outcome, status)
