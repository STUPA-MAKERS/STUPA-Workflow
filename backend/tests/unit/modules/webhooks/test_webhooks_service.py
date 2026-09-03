"""WebhookService (T-19): dispatch_event dedup and deliver (ok/retry/dead/ssrf)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from app.modules.admin.models import Webhook, WebhookDelivery
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
    hook = Webhook(
        name="h", url=url, events=["status_changed"], active=active, secret=secret
    )
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
_IP_URL = f"https://{_IP}/h"  # target after pinning, the Host header stays hook.test


def _public_resolver(_host: str) -> list[str]:
    return [_IP]


async def test_dispatch_no_matching_webhooks() -> None:
    session = FakeSession(scalars=[[]])
    assert await _svc(session, FakeWebhookQueue()).dispatch_event("status_changed") == 0
    assert session.committed == 0


async def test_dispatch_creates_and_enqueues() -> None:
    h1, h2 = _hook(), _hook()
    queue = FakeWebhookQueue()
    session = FakeSession(scalars=[[h1, h2]])
    n = await _svc(session, queue).dispatch_event("status_changed", payload={"x": 1})
    assert n == 2
    assert session.committed == 1
    assert len(queue.enqueued) == 2
    assert all(d.idempotency_key is None for d in session.added)


async def test_dispatch_dedup_skips_existing() -> None:
    h1 = _hook()
    base = "app:evt:0:webhook"
    existing = f"{base}:{h1.id}"
    session = FakeSession(scalars=[[h1], [existing]])
    n = await _svc(session, FakeWebhookQueue()).dispatch_event(
        "status_changed", idempotency_base=base
    )
    assert n == 0
    assert session.committed == 0


async def test_dispatch_dedup_partial() -> None:
    h1, h2 = _hook(), _hook()
    base = "app:evt:0:webhook"
    session = FakeSession(scalars=[[h1, h2], [f"{base}:{h1.id}"]])
    queue = FakeWebhookQueue()
    n = await _svc(session, queue).dispatch_event(
        "status_changed", idempotency_base=base
    )
    assert n == 1
    assert len(queue.enqueued) == 1


async def test_dispatch_without_queue_stays_pending() -> None:
    session = FakeSession(scalars=[[_hook()]])
    assert await _svc(session, None).dispatch_event("status_changed") == 1
    assert session.committed == 1


async def test_dispatch_race_integrity_error_is_deduped() -> None:
    # A concurrent insert violates unique(webhook_id, idempotency_key). The delivery
    # already exists and is enqueued, so the service skips it. It neither counts nor
    # enqueues the delivery again.
    from sqlalchemy.exc import IntegrityError

    h1 = _hook()
    base = "app:evt:0:webhook"
    err = IntegrityError("INSERT", {}, Exception("duplicate key"))
    session = FakeSession(scalars=[[h1], []], flush_errors=[err])
    queue = FakeWebhookQueue()
    n = await _svc(session, queue).dispatch_event(
        "status_changed", idempotency_base=base
    )
    assert n == 0
    assert queue.enqueued == []
    assert session.added == []  # the savepoint rollback discarded the delivery


# Tests for dispatch_to_webhook.
async def test_dispatch_to_webhook_dedup_skips_existing() -> None:
    hook = _hook()
    base = "app:evt:0:webhook"
    session = FakeSession(scalars=[[f"{base}:{hook.id}"]])
    session.store[hook.id] = hook
    n = await _svc(session, FakeWebhookQueue()).dispatch_to_webhook(
        hook.id, event="status_changed", idempotency_base=base
    )
    assert n == 0
    assert session.committed == 0


async def test_dispatch_to_webhook_race_integrity_error_is_deduped() -> None:
    from sqlalchemy.exc import IntegrityError

    hook = _hook()
    base = "app:evt:0:webhook"
    err = IntegrityError("INSERT", {}, Exception("duplicate key"))
    session = FakeSession(scalars=[[]], flush_errors=[err])
    session.store[hook.id] = hook
    queue = FakeWebhookQueue()
    n = await _svc(session, queue).dispatch_to_webhook(
        hook.id, event="status_changed", idempotency_base=base
    )
    assert n == 0
    assert queue.enqueued == []
    assert session.added == []  # the savepoint rollback discarded the delivery


async def test_dispatch_to_webhook_without_queue_returns_one() -> None:
    # The insert succeeds but no queue exists. The delivery stays pending, and the
    # call returns 1 without an enqueue.
    hook = _hook()
    session = FakeSession()
    session.store[hook.id] = hook
    n = await _svc(session, None).dispatch_to_webhook(hook.id, event="status_changed")
    assert n == 1
    assert session.committed == 1


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
    # Pinning: the client connects to the validated IP and keeps the original host.
    assert sent.url.host == _IP
    assert sent.headers["Host"] == "hook.test"
    assert sent.headers["X-Signature"].startswith("sha256=")
    assert "X-Timestamp" in sent.headers


@respx.mock
async def test_deliver_pins_validated_ip_no_rebind() -> None:
    # DNS rebinding: the first resolution gives a public IP, the second an internal one.
    # The service pins the validated IP and never resolves again, so the client never
    # reaches the internal address.
    calls: list[str] = []

    def _rebinding(host: str) -> list[str]:
        calls.append(host)
        return [_IP] if len(calls) == 1 else ["10.0.0.5"]

    hook = _hook(url="https://hook.test/h")
    route = respx.post(_IP_URL).mock(return_value=httpx.Response(200))
    # The client must NEVER request the internal IP.
    internal = respx.post("https://10.0.0.5/h").mock(return_value=httpx.Response(200))
    session = FakeSession()
    delivery = _delivery(hook.id)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(
            delivery.id, http_client=client, resolver=_rebinding
        )
    assert outcome.kind == "ok"
    assert calls == ["hook.test"]  # resolved exactly once, no re-resolve
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
    assert delivery.next_at is None


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
    assert outcome.defer == SETTINGS.webhook_retry_backoff_seconds  # 30 * 2**0
    assert delivery.status == "failed"
    assert delivery.attempts == 1
    assert delivery.next_at is not None


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
    assert delivery.next_at is None


@respx.mock
async def test_deliver_caps_oversized_response_body() -> None:
    # A malicious receiver answers 2xx with a huge body of more than 64 KiB. The service
    # streams the body and discards it after the limit. The status code still decides
    # the outcome. This guards against an out-of-memory crash (security.md §5).
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
    # A small body below the limit ends the read loop without a break. The status
    # code stays.
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
    total run time stays unbounded (slow drip, AUD-011).
    """

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            await asyncio.sleep(0.01)
            yield b"x"

    async def aclose(self) -> None:  # pragma: no cover - trivial
        return None


async def test_deliver_slow_drip_response_hits_total_deadline() -> None:
    # A slow-drip receiver answers 2xx and then drips the body forever. Without a total
    # deadline the shared worker slot would hang. The service caps the total time with
    # a call to asyncio.timeout(webhook_timeout_seconds). The TimeoutException counts
    # as a transport error, so the delivery retries (AUD-011).
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
    # The total deadline fired, so the service retries the transient transport error
    # instead of hanging.
    assert outcome.kind == "retry"
    assert delivery.response_code is None
