"""Tests for the Gremium group-mapping tools and the removed membership tools.

The IdP is the only source of Gremium memberships and global roles. The server thus
has no tool that writes a membership or a role assignment. The group-mapping tools
must call the correct backend routes with camelCase bodies.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tools import _common, admin, register_all


class _FakeApi:
    """Record each call and answer with a fixed body."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def _call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append((method, path, kw.get("json")))
        return {"status": "ok"}

    async def get(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("GET", path, **kw)

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("POST", path, **kw)

    async def patch(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("PATCH", path, **kw)

    async def delete(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("DELETE", path, **kw)


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def _tool_names() -> set[str]:
    server = FastMCP("test")
    register_all(server)
    return {tool.name for tool in asyncio.run(server.list_tools())}


def test_removed_tools_are_not_registered() -> None:
    names = _tool_names()
    for removed in (
        "create_gremium_membership",
        "update_gremium_membership",
        "delete_gremium_membership",
        "create_role_assignment",
        "update_role_assignment",
        "delete_role_assignment",
    ):
        assert removed not in names


def test_read_and_mapping_tools_are_registered() -> None:
    names = _tool_names()
    for present in (
        "list_gremium_memberships",
        "list_role_assignments",
        "list_principals",
        "list_gremium_group_mappings",
        "create_gremium_group_mapping",
        "update_gremium_group_mapping",
        "delete_gremium_group_mapping",
    ):
        assert present in names


def test_removed_wire_schemas_are_gone() -> None:
    for removed in ("GremiumMembershipCreate", "RoleAssignmentCreate", "RoleAssignmentUpdate"):
        assert not hasattr(S, removed)


def test_list_gremium_group_mappings(fake_api: _FakeApi) -> None:
    asyncio.run(admin.list_gremium_group_mappings("g1"))
    assert fake_api.calls == [("GET", "/admin/gremien/g1/group-mappings", None)]


def test_create_gremium_group_mapping(fake_api: _FakeApi) -> None:
    body = S.GremiumGroupMappingCreate(oidcGroup="stupa-members", gremiumRoleId="r1")
    asyncio.run(admin.create_gremium_group_mapping("g1", body))
    assert fake_api.calls == [
        (
            "POST",
            "/admin/gremien/g1/group-mappings",
            {"oidcGroup": "stupa-members", "gremiumRoleId": "r1"},
        )
    ]


def test_update_gremium_group_mapping_sends_only_set_keys(fake_api: _FakeApi) -> None:
    patch = S.GremiumGroupMappingUpdate(gremiumRoleId="r2")
    asyncio.run(admin.update_gremium_group_mapping("m1", patch))
    assert fake_api.calls == [
        ("PATCH", "/admin/gremium-group-mappings/m1", {"gremiumRoleId": "r2"})
    ]


def test_delete_gremium_group_mapping(fake_api: _FakeApi) -> None:
    asyncio.run(admin.delete_gremium_group_mapping("m1"))
    assert fake_api.calls == [("DELETE", "/admin/gremium-group-mappings/m1", None)]


def test_list_gremium_memberships_stays_read_only(fake_api: _FakeApi) -> None:
    asyncio.run(admin.list_gremium_memberships("g1"))
    assert fake_api.calls == [("GET", "/admin/gremien/g1/memberships", None)]
