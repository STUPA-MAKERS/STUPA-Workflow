"""WebhookService: the sweep of the pending deliveries and deliver (ok/retry/dead/ssrf)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from app.modules.webhooks.models import Webhook, WebhookDelivery
from app.modules.webhooks.queue import WebhookQueue
from app.modules.webhooks.service import WebhookService
from app.settings import load_settings
from tests._support.webhooks_fakes import FakeSession, FakeWebhookQueue

SETTINGS = load_settings()


def _svc(session: FakeSession, queue: WebhookQueue | None = None) -> WebhookService:
    return WebhookService(session, SETTINGS, queue=queue)  # type: ignore[arg-type]


def _hook(
    *, url: str = "https://hook.test/h", active: bool = True, secret: bytes | None = b"k"
) -> Webhook:
    hook = Webhook(name="h", url=url, active=active, secret=secret)
    hook.id = uuid.uuid4()
    return hook


def _delivery(
    hook_id: uuid.UUID,
    *,
    attempts: int = 0,
    idempotency_key: str | None = None,
    payload: dict[str, object] | None = None,
) -> WebhookDelivery:
    d = WebhookDelivery(
        webhook_id=hook_id,
        event="status_changed",
        payload=payload if payload is not None else {"event": "status_changed"},
        status="pending",
        attempts=attempts,
        idempotency_key=idempotency_key,
    )
    d.id = uuid.uuid4()
    return d


_IP = "93.184.216.34"
#: Target after pinning; the Host header stays hook.test.
_IP_URL = f"https://{_IP}/h"


def _public_resolver(_host: str) -> list[str]:
    return [_IP]


async def test_enqueue_pending_without_queue_is_zero() -> None:
    """Without Redis the sweep enqueues nothing and reads nothing."""
    import datetime as dt

    session = FakeSession()
    assert await _svc(session, None).enqueue_pending(older_than=dt.datetime.now(dt.UTC)) == 0


async def test_enqueue_pending_enqueues_each_row() -> None:
    """The sweep hands each pending delivery to the queue. §F/integrations/webhooks/002417."""
    import datetime as dt

    ids = [uuid.uuid4(), uuid.uuid4()]
    session = FakeSession(scalars=[ids])
    queue = FakeWebhookQueue()
    n = await _svc(session, queue).enqueue_pending(older_than=dt.datetime.now(dt.UTC))
    assert n == 2
    assert queue.enqueued == ids


@pytest.mark.parametrize("status", ["ok", "dead"])
async def test_deliver_final_row_is_gone(status: str) -> None:
    """A second job for a final delivery sends nothing. §F/integrations/webhooks/000299."""
    hook = _hook()
    d = _delivery(hook.id)
    d.status = status
    session = FakeSession()
    session.store[hook.id] = hook
    session.store[d.id] = d
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(d.id, http_client=client)
    assert outcome.kind == "gone"


async def test_deliver_gone() -> None:
    async with httpx.AsyncClient() as client:
        outcome = await _svc(FakeSession()).deliver(uuid.uuid4(), http_client=client)
    assert outcome.kind == "gone"


@pytest.mark.parametrize("hook", [None, _hook(active=False), _hook(secret=None)])
async def test_deliver_dead_when_undeliverable(hook: Webhook | None) -> None:
    wid = hook.id if hook is not None else uuid.uuid4()
    session = FakeSession()
    delivery = _delivery(wid)
    session.store[delivery.id] = delivery
    if hook is not None:
        session.store[hook.id] = hook
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(delivery.id, http_client=client)
    assert outcome.kind == "dead"
    assert delivery.status == "dead"


async def test_deliver_ssrf_block_is_permanent_dead() -> None:
    hook = _hook(url="http://127.0.0.1/h")
    session = FakeSession()
    delivery = _delivery(hook.id)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(delivery.id, http_client=client)
    assert outcome.kind == "dead"
    assert delivery.status == "dead"


@respx.mock
async def test_deliver_ok_pins_ip_and_signs() -> None:
    """Connect to the validated IP, keep the original host and sign the body."""
    hook = _hook(url="https://hook.test/h")
    route = respx.post(_IP_URL).mock(return_value=httpx.Response(204))
    session = FakeSession()
    delivery = _delivery(hook.id)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(
            delivery.id, http_client=client, resolver=_public_resolver
        )
    assert outcome.kind == "ok"
    assert delivery.status == "ok"
    assert delivery.response_code == 204
    sent = route.calls.last.request
    assert sent.url.host == _IP
    assert sent.headers["Host"] == "hook.test"
    assert sent.headers["X-Signature"].startswith("sha256=")
    assert "X-Timestamp" in sent.headers


@respx.mock
async def test_deliver_pins_validated_ip_no_rebind() -> None:
    """Pin the validated IP against DNS rebinding.

    The first resolution gives a public IP, the second an internal one. The service resolves
    once and never reaches the internal address.
    """
    calls: list[str] = []

    def _rebinding(host: str) -> list[str]:
        calls.append(host)
        return [_IP] if len(calls) == 1 else ["10.0.0.5"]

    hook = _hook(url="https://hook.test/h")
    route = respx.post(_IP_URL).mock(return_value=httpx.Response(200))
    internal = respx.post("https://10.0.0.5/h").mock(return_value=httpx.Response(200))
    session = FakeSession()
    delivery = _delivery(hook.id)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(delivery.id, http_client=client, resolver=_rebinding)
    assert outcome.kind == "ok"
    assert calls == ["hook.test"]
    assert route.called
    assert not internal.called


@respx.mock
async def test_deliver_4xx_is_dead_no_retry() -> None:
    hook = _hook(url="https://hook.test/h")
    respx.post(_IP_URL).mock(return_value=httpx.Response(404))
    session = FakeSession()
    delivery = _delivery(hook.id, attempts=0)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(
            delivery.id, http_client=client, resolver=_public_resolver
        )
    assert outcome.kind == "dead"
    assert delivery.status == "dead"
    assert delivery.response_code == 404


@pytest.mark.parametrize("status", [301, 302, 307, 308])
@respx.mock
async def test_deliver_3xx_is_dead_no_retry(status: int) -> None:
    """The client follows no redirect, so a retry cannot change a 3xx.

    §F/integrations/webhooks/000298
    """
    hook = _hook(url="https://hook.test/h")
    respx.post(_IP_URL).mock(
        return_value=httpx.Response(status, headers={"Location": "https://other.test/"})
    )
    session = FakeSession()
    delivery = _delivery(hook.id, attempts=0)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(
            delivery.id, http_client=client, resolver=_public_resolver
        )
    assert outcome.kind == "dead"
    assert delivery.status == "dead"
    assert delivery.response_code == status


@respx.mock
async def test_deliver_5xx_retries_with_backoff() -> None:
    hook = _hook(url="https://hook.test/h")
    respx.post(_IP_URL).mock(return_value=httpx.Response(500))
    session = FakeSession()
    delivery = _delivery(hook.id, attempts=0)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(
            delivery.id, http_client=client, resolver=_public_resolver
        )
    assert outcome.kind == "retry"
    assert outcome.defer == SETTINGS.webhook_retry_backoff_seconds
    assert delivery.status == "failed"
    assert delivery.attempts == 1


@respx.mock
async def test_deliver_dead_after_max_tries() -> None:
    hook = _hook(url="https://hook.test/h")
    respx.post(_IP_URL).mock(return_value=httpx.Response(503))
    session = FakeSession()
    delivery = _delivery(hook.id, attempts=SETTINGS.webhook_max_tries - 1)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(
            delivery.id, http_client=client, resolver=_public_resolver
        )
    assert outcome.kind == "dead"
    assert delivery.status == "dead"


@respx.mock
async def test_deliver_caps_oversized_response_body() -> None:
    """Discard a huge 2xx body after the cap; the status code still decides.

    This guards the worker against an out-of-memory crash.
    """
    from app.modules.webhooks.service import _MAX_RESPONSE_BYTES

    big_body = b"x" * (_MAX_RESPONSE_BYTES * 4)
    hook = _hook(url="https://hook.test/h")
    respx.post(_IP_URL).mock(return_value=httpx.Response(200, content=big_body))
    session = FakeSession()
    delivery = _delivery(hook.id, attempts=0)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(
            delivery.id, http_client=client, resolver=_public_resolver
        )
    assert outcome.kind == "ok"
    assert delivery.status == "ok"
    assert delivery.response_code == 200


@respx.mock
async def test_deliver_small_response_body_read_fully() -> None:
    """Read a small body to its end without a break; the status code stays."""
    hook = _hook(url="https://hook.test/h")
    respx.post(_IP_URL).mock(return_value=httpx.Response(200, content=b"ok"))
    session = FakeSession()
    delivery = _delivery(hook.id, attempts=0)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(
            delivery.id, http_client=client, resolver=_public_resolver
        )
    assert outcome.kind == "ok"
    assert delivery.response_code == 200


@respx.mock
async def test_deliver_transport_error_retries() -> None:
    hook = _hook(url="https://hook.test/h")
    respx.post(_IP_URL).mock(side_effect=httpx.ConnectError("down"))
    session = FakeSession()
    delivery = _delivery(hook.id, attempts=0)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(
            delivery.id, http_client=client, resolver=_public_resolver
        )
    assert outcome.kind == "retry"
    assert delivery.response_code is None


class _DripStream(httpx.AsyncByteStream):
    """Stream one byte at a time forever, with a short pause between the bytes.

    Every single read is fast, so the per-read timeout of httpx never fires. The
    total run time stays unbounded (slow drip).
    """

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            await asyncio.sleep(0.01)
            yield b"x"

    async def aclose(self) -> None:  # pragma: no cover - trivial
        return None


async def test_deliver_slow_drip_response_hits_total_deadline() -> None:
    """Retry a slow-drip receiver after the total deadline.

    Without a total deadline the shared worker slot would hang.
    ``asyncio.timeout(webhook_timeout_seconds)`` caps the time, and the TimeoutException
    counts as a transient transport error.
    """
    settings = load_settings(webhook_timeout_seconds=0.05)

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_DripStream())

    transport = httpx.MockTransport(_handler)
    hook = _hook(url="https://hook.test/h")
    session = FakeSession()
    delivery = _delivery(hook.id, attempts=0)
    session.store.update({delivery.id: delivery, hook.id: hook})
    svc = WebhookService(session, settings)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport) as client:
        outcome = await asyncio.wait_for(
            svc.deliver(delivery.id, http_client=client, resolver=_public_resolver),
            timeout=5.0,
        )
    assert outcome.kind == "retry"
    assert delivery.response_code is None
