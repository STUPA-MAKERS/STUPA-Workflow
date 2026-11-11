"""The WebSocket handshake after the session lookup: the principal row and the renewal."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.auth import ws


class _Result:
    def __init__(self, row: object) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class _Db:
    def __init__(self, row: object) -> None:
        self._row = row

    async def execute(self, _statement: object) -> _Result:
        return _Result(self._row)


def _socket() -> Any:
    return SimpleNamespace(headers={"origin": "https://app.test"}, cookies={"sid": "cookie"})


def _settings() -> Any:
    return SimpleNamespace(
        session_cookie_name="sid",
        session_secret="secret",
        ws_allowed_origins="",
        cors_allowed_origins="",
        public_base_url="",
    )


@pytest.fixture
def renew(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the session lookup, the renewal and the RBAC resolve; return the switches."""
    state: dict[str, Any] = {"renewed": True, "deactivate": False, "session": True}

    async def _load(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(principal_id=uuid4()) if state["session"] else None

    async def _renew(*_args: object, principal: Any, **_kwargs: object) -> bool:
        if state["deactivate"]:
            principal.active = False
        return bool(state["renewed"])

    async def _resolve(_db: object, row: object, _now: object) -> object:
        return ("principal", row)

    monkeypatch.setattr(ws, "origin_allowed", lambda _origin, _settings: True)
    monkeypatch.setattr(ws.sessions, "load_principal_session", _load)
    monkeypatch.setattr(ws, "renew_principal_session", _renew)
    monkeypatch.setattr(ws.rbac, "resolve_principal", _resolve)
    return state


async def test_unknown_session_gives_no_principal(renew: dict[str, Any]) -> None:
    renew["session"] = False
    row = SimpleNamespace(active=True)
    assert await ws.resolve_ws_principal(_socket(), _Db(row), _settings()) is None  # type: ignore[arg-type]


async def test_missing_or_inactive_row_gives_no_principal(renew: dict[str, Any]) -> None:
    assert await ws.resolve_ws_principal(_socket(), _Db(None), _settings()) is None  # type: ignore[arg-type]
    inactive = SimpleNamespace(active=False)
    assert await ws.resolve_ws_principal(_socket(), _Db(inactive), _settings()) is None  # type: ignore[arg-type]


async def test_failed_renewal_gives_no_principal(renew: dict[str, Any]) -> None:
    renew["renewed"] = False
    row = SimpleNamespace(active=True)
    assert await ws.resolve_ws_principal(_socket(), _Db(row), _settings()) is None  # type: ignore[arg-type]


async def test_row_deactivated_by_the_renewal_gives_no_principal(renew: dict[str, Any]) -> None:
    renew["deactivate"] = True
    row = SimpleNamespace(active=True)
    assert await ws.resolve_ws_principal(_socket(), _Db(row), _settings()) is None  # type: ignore[arg-type]


async def test_active_row_resolves_to_the_principal(renew: dict[str, Any]) -> None:
    row = SimpleNamespace(active=True)
    assert await ws.resolve_ws_principal(_socket(), _Db(row), _settings()) == ("principal", row)  # type: ignore[arg-type]
