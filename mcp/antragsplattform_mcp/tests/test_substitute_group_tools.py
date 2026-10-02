"""Tests for the substitute-group tools (Z5) and the lead entry of a delegation (O6)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tools import _common, meetings


class _FakeApi:
    """Record each call with its path, body and query."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def _record(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append((method, path, kw.get("json", kw.get("params"))))
        return {}

    async def get(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("GET", path, **kw)

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("POST", path, **kw)

    async def patch(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("PATCH", path, **kw)

    async def delete(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("DELETE", path, **kw)


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_group_tools_hit_the_routes(fake_api: _FakeApi) -> None:
    base = "/delegations/substitute-groups"
    asyncio.run(meetings.list_substitute_groups("g1"))
    asyncio.run(
        meetings.create_substitute_group(
            S.SubstituteGroupCreate(gremiumId="g1", nameI18n={"de": "Info"})
        )
    )
    asyncio.run(meetings.update_substitute_group("x", S.SubstituteGroupUpdate(position=2)))
    asyncio.run(meetings.add_substitute_group_member("x", "p1", "substitute"))
    asyncio.run(meetings.remove_substitute_group_member("x", "p1"))
    asyncio.run(meetings.delete_substitute_group("x"))
    assert fake_api.calls == [
        ("GET", base, {"gremiumId": "g1"}),
        ("POST", base, {"gremiumId": "g1", "nameI18n": {"de": "Info"}, "position": 0}),
        ("PATCH", f"{base}/x", {"position": 2}),
        ("POST", f"{base}/x/members", {"principalId": "p1", "kind": "substitute"}),
        ("DELETE", f"{base}/x/members/p1", None),
        ("DELETE", f"{base}/x", None),
    ]


def test_list_substitutes_sends_the_gremium(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.list_substitutes("g1"))
    assert fake_api.calls == [("GET", "/delegations/substitutes", {"gremiumId": "g1"})]


def test_create_delegation_by_the_lead(fake_api: _FakeApi) -> None:
    body = S.DelegationCreate(meetingId="m1", delegateId="b", delegatorId="a")
    asyncio.run(meetings.create_delegation(body))
    asyncio.run(meetings.create_delegation(S.DelegationCreate(meetingId="m1", delegateId="b")))
    assert fake_api.calls == [
        (
            "POST",
            "/delegations",
            {"meetingId": "m1", "delegateId": "b", "delegateVoting": False, "delegatorId": "a"},
        ),
        ("POST", "/delegations", {"meetingId": "m1", "delegateId": "b", "delegateVoting": False}),
    ]
