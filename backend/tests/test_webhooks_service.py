"""WebhookService (T-19): dispatch_event (Dedup) + deliver (ok/retry/dead/ssrf)."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from app.modules.admin.models import Webhook, WebhookDelivery
from app.modules.webhooks.queue import WebhookQueue
from app.modules.webhooks.service import WebhookService
from app.settings import load_settings
from tests.webhooks_fakes import FakeSession, FakeWebhookQueue

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
_IP_URL = f"https://{_IP}/h"  # Ziel nach Pinning (Host bleibt hook.test)


def _public_resolver(_host: str) -> list[str]:
    return [_IP]


# ----------------------------------------------------------------- dispatch #
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
    # Nebenläufiger Insert verletzt unique(webhook_id, idempotency_key): die
    # Delivery existiert bereits (= enqueued) → überspringen, nicht zählen/enqueuen.
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
    assert session.added == []  # Savepoint-Rollback hat die Delivery verworfen


# ------------------------------------------------------------------ deliver #
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
    # Pinning: verbunden zur validierten IP, Host bleibt der Original-Host.
    assert sent.url.host == _IP
    assert sent.headers["Host"] == "hook.test"
    assert sent.headers["X-Signature"].startswith("sha256=")
    assert "X-Timestamp" in sent.headers


@respx.mock
async def test_deliver_pins_validated_ip_no_rebind() -> None:
    # DNS-Rebinding: erste Auflösung public, zweite intern. Da wir an die validierte
    # IP pinnen (kein erneutes Auflösen), erreicht die interne Adresse den Client nie.
    calls: list[str] = []

    def _rebinding(host: str) -> list[str]:
        calls.append(host)
        return [_IP] if len(calls) == 1 else ["10.0.0.5"]

    hook = _hook(url="https://hook.test/h")
    route = respx.post(_IP_URL).mock(return_value=httpx.Response(200))
    # Die interne IP darf NIE angefragt werden:
    internal = respx.post("https://10.0.0.5/h").mock(return_value=httpx.Response(200))
    session = FakeSession()
    delivery = _delivery(hook.id)
    session.store.update({delivery.id: delivery, hook.id: hook})
    async with httpx.AsyncClient() as client:
        outcome = await _svc(session).deliver(
            delivery.id, http_client=client, resolver=_rebinding
        )
    assert outcome.kind == "ok"
    assert calls == ["hook.test"]  # genau einmal aufgelöst (kein Re-Resolve)
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
