"""Tests for the audit tools: the live chain check and the stored latest check (Z6)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp.tools import _common, admin


class _FakeApi:
    """Record each GET and answer with a canned body."""

    def __init__(self, body: Any) -> None:
        self.body = body
        self.calls: list[tuple[str, str]] = []

    async def get(self, path: str, **_kw: Any) -> Any:
        self.calls.append(("GET", path))
        return self.body


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi({"valid": True, "checked": 3, "trigger": "cron"})
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_latest_audit_verification_reads_the_stored_check(fake_api: _FakeApi) -> None:
    out = asyncio.run(admin.get_latest_audit_verification())
    assert fake_api.calls == [("GET", "/admin/audit/verify/latest")]
    assert out == {"valid": True, "checked": 3, "trigger": "cron"}


def test_latest_audit_verification_passes_null_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeApi(None)
    monkeypatch.setattr(_common, "_client", fake)
    assert asyncio.run(admin.get_latest_audit_verification()) is None


def test_verify_audit_chain_stays_live(fake_api: _FakeApi) -> None:
    asyncio.run(admin.verify_audit_chain())
    assert fake_api.calls == [("GET", "/admin/audit/verify")]
