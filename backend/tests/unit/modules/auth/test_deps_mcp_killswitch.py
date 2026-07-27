"""Unit: the `mcp.use` kill switch in the OAuth access-token path (`app.deps`).

Access tokens come only from the OAuth grant flow. That flow gates the consent step on
`mcp.use`. If the permission goes away later, every token that is already issued must
stop working at once. The check runs against the UNSCOPED permission set, before the
scope narrows it. The suite uses fakes and needs no database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app import deps
from app.modules.auth.principal import Principal

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


class _DB:
    """Minimal `AsyncSession` stub that returns an active principal row."""

    async def execute(self, _stmt: object) -> Any:
        return SimpleNamespace(
            scalar_one_or_none=lambda: SimpleNamespace(active=True)
        )


def _patch(monkeypatch: pytest.MonkeyPatch, principal: Principal) -> None:
    async def _resolve(*_a: object, **_k: object) -> tuple[Any, str]:
        return (uuid4(), "read")

    async def _rbac(*_a: object, **_k: object) -> Principal:
        return principal

    monkeypatch.setattr(deps.oauth_service, "resolve_access_token", _resolve)
    monkeypatch.setattr(deps.rbac, "resolve_principal", _rbac)


async def test_killswitch_rejects_principal_without_mcp_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The principal does NOT hold `mcp.use`, so the token has no effect.
    _patch(monkeypatch, Principal(sub="agent", permissions={"application.read"}))
    out = await deps._principal_from_access_token(
        _DB(), "apat_x", NOW  # type: ignore[arg-type]
    )
    assert out is None


async def test_killswitch_allows_principal_with_mcp_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The principal holds `mcp.use` explicitly. The token stays valid and the scope caps it.
    _patch(
        monkeypatch,
        Principal(sub="agent", permissions={"mcp.use", "application.read"}),
    )
    out = await deps._principal_from_access_token(
        _DB(), "apat_x", NOW  # type: ignore[arg-type]
    )
    assert out is not None
    # The recheck ran against the UNSCOPED set. The scope is set afterwards.
    assert out.scope_permissions is not None


async def test_killswitch_admin_passes_via_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The admin holds `mcp.use` through the unscoped admin bypass, so the token is valid.
    _patch(monkeypatch, Principal(sub="root", roles=["admin"]))
    out = await deps._principal_from_access_token(
        _DB(), "apat_x", NOW  # type: ignore[arg-type]
    )
    assert out is not None
