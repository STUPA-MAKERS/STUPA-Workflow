"""Tests der Benachrichtigungs-Präferenzen (#4-2): API + Empfänger-Filter."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.notifications.kinds import NOTIFICATION_KINDS
from app.modules.notifications.router import get_notification_service
from app.modules.notifications.service import (
    NotificationService,
    filter_recipients_by_preference,
)
from app.shared.errors import ValidationProblem


class _FakeService:
    def __init__(self) -> None:
        self.set_items: list[tuple[str, bool]] | None = None

    async def get_preferences(self, sub: str) -> list[tuple[str, bool]]:
        return [(k, True) for k in NOTIFICATION_KINDS]

    async def set_preferences(
        self, sub: str, items: list[tuple[str, bool]]
    ) -> list[tuple[str, bool]]:
        self.set_items = items
        return [(k, dict(items).get(k, True)) for k in NOTIFICATION_KINDS]


def _client(service: _FakeService, principal: Principal | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_notification_service] = lambda: service
    app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app)


def test_get_preferences_requires_login() -> None:
    client = _client(_FakeService(), None)
    assert client.get("/api/notifications/preferences").status_code == 401


def test_get_preferences_returns_full_catalogue() -> None:
    client = _client(_FakeService(), Principal(sub="u-1"))
    resp = client.get("/api/notifications/preferences")
    assert resp.status_code == 200
    body = resp.json()
    assert [p["kind"] for p in body] == list(NOTIFICATION_KINDS)
    assert all(p["enabled"] is True for p in body)


def test_put_preferences_passes_items() -> None:
    service = _FakeService()
    client = _client(service, Principal(sub="u-1"))
    resp = client.put(
        "/api/notifications/preferences",
        json={"preferences": [{"kind": "protocol", "enabled": False}]},
    )
    assert resp.status_code == 200
    assert service.set_items == [("protocol", False)]
    body = {p["kind"]: p["enabled"] for p in resp.json()}
    assert body["protocol"] is False
    assert body["status_update"] is True


async def test_set_preferences_rejects_unknown_kind() -> None:
    svc = NotificationService(cast(AsyncSession, object()))
    with pytest.raises(ValidationProblem):
        await svc.set_preferences("u-1", [("nope", False)])


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeFilterSession:
    """Bedient nur ``scalars`` für den Präferenz-Filter."""

    def __init__(self, disabled_emails: list[str]) -> None:
        self.disabled = disabled_emails
        self.queried = False

    async def scalars(self, _stmt: Any) -> _FakeScalars:
        self.queried = True
        return _FakeScalars(self.disabled)


async def test_filter_removes_opted_out_recipients() -> None:
    session = _FakeFilterSession(["Optout@Example.org"])
    out = await filter_recipients_by_preference(
        cast(AsyncSession, session),
        ["optout@example.org", "keep@example.org"],
        "status_update",
    )
    assert out == ["keep@example.org"]


async def test_filter_ignores_unknown_kind_and_empty() -> None:
    session = _FakeFilterSession(["x@example.org"])
    out = await filter_recipients_by_preference(
        cast(AsyncSession, session), ["x@example.org"], "not_a_kind"
    )
    assert out == ["x@example.org"]
    assert session.queried is False
    assert (
        await filter_recipients_by_preference(
            cast(AsyncSession, session), [], "status_update"
        )
        == []
    )
