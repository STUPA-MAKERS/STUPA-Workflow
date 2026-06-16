"""Worker-Task `deliver_webhook` (T-19): ok/retry/dead/gone — Netz via respx."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import respx
from arq import Retry

from app.modules.admin.models import Webhook, WebhookDelivery
from app.settings import load_settings
from tests._support.webhooks_fakes import FakeSession
from worker.webhook import _sessionmaker, deliver_webhook, on_startup

SETTINGS = load_settings()
_URL = "https://93.184.216.34/h"  # IP-Literal → kein DNS im SSRF-Guard


class _SessionCM:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *_a: Any) -> bool:
        return False


def _client_factory(_settings: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=False)


def _ctx(session: FakeSession) -> dict[str, Any]:
    return {
        "settings": SETTINGS,
        "webhook_sessionmaker": lambda: _SessionCM(session),
        "webhook_client_factory": _client_factory,
    }


def _setup(session: FakeSession, *, attempts: int = 0) -> WebhookDelivery:
    hook = Webhook(name="h", url=_URL, events=["status_changed"], active=True, secret=b"k")
    hook.id = uuid.uuid4()
    delivery = WebhookDelivery(
        webhook_id=hook.id,
        event="status_changed",
        payload={"event": "status_changed"},
        status="pending",
        attempts=attempts,
    )
    delivery.id = uuid.uuid4()
    session.store.update({hook.id: hook, delivery.id: delivery})
    return delivery


@respx.mock
async def test_deliver_ok() -> None:
    session = FakeSession()
    delivery = _setup(session)
    respx.post(_URL).mock(return_value=httpx.Response(200))
    assert await deliver_webhook(_ctx(session), str(delivery.id)) == "ok"


@respx.mock
async def test_deliver_retry_raises() -> None:
    session = FakeSession()
    delivery = _setup(session, attempts=0)
    respx.post(_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(Retry):
        await deliver_webhook(_ctx(session), str(delivery.id))


@respx.mock
async def test_deliver_dead() -> None:
    session = FakeSession()
    delivery = _setup(session, attempts=SETTINGS.webhook_max_tries - 1)
    respx.post(_URL).mock(return_value=httpx.Response(500))
    assert await deliver_webhook(_ctx(session), str(delivery.id)) == "dead"


async def test_deliver_gone() -> None:
    session = FakeSession()
    assert await deliver_webhook(_ctx(session), str(uuid.uuid4())) == "gone"


async def test_on_startup_sets_settings() -> None:
    ctx: dict[str, Any] = {}
    await on_startup(ctx)
    assert "settings" in ctx


def test_sessionmaker_default() -> None:
    # Ohne Injection fällt _sessionmaker auf den globalen Sessionmaker zurück.
    assert _sessionmaker({}) is not None
