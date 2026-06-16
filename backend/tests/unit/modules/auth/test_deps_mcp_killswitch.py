"""Unit: ``mcp.use``-Kill-Switch im OAuth-Access-Token-Pfad (``app.deps``).

Access-Tokens entstehen ausschließlich aus dem OAuth-Grant-Flow, der am Consent auf
``mcp.use`` gegated ist. Wird die Permission später entzogen, müssen bereits
ausgestellte Tokens sofort wirkungslos werden — geprüft gegen die UNGESCOPTE
Permission-Menge (vor der Scope-Kappung). DB-frei über Fakes.
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
    """Minimaler ``AsyncSession``-Stub: liefert eine aktive Principal-Zeile."""

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
    # Principal hält `mcp.use` NICHT (Permission entzogen) → Token wirkungslos.
    _patch(monkeypatch, Principal(sub="agent", permissions={"application.read"}))
    out = await deps._principal_from_access_token(
        _DB(), "apat_x", NOW  # type: ignore[arg-type]
    )
    assert out is None


async def test_killswitch_allows_principal_with_mcp_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Principal hält `mcp.use` explizit → Token bleibt gültig, Scope wird gekappt.
    _patch(
        monkeypatch,
        Principal(sub="agent", permissions={"mcp.use", "application.read"}),
    )
    out = await deps._principal_from_access_token(
        _DB(), "apat_x", NOW  # type: ignore[arg-type]
    )
    assert out is not None
    # Recheck lief gegen die UNGESCOPTE Menge; danach ist der Scope gesetzt.
    assert out.scope_permissions is not None


async def test_killswitch_admin_passes_via_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Admin hat `mcp.use` über den Admin-Bypass (ungescopt) → Token gültig.
    _patch(monkeypatch, Principal(sub="root", roles=["admin"]))
    out = await deps._principal_from_access_token(
        _DB(), "apat_x", NOW  # type: ignore[arg-type]
    )
    assert out is not None
