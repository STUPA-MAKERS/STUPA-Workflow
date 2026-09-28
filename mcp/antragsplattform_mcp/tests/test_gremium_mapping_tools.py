"""Tests for the OIDC group-mapping tools and the removed membership tools.

The IdP is the only source of Gremium memberships and global roles. The server thus
has no tool that writes a membership or a role assignment. There are three separate
mappings: group to Gremium membership, group to Gremium role and group to global role.
The mapping tools must call the correct backend routes with camelCase bodies.
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
        "list_gremium_group_mappings",
        "create_gremium_group_mapping",
        "update_gremium_group_mapping",
        "delete_gremium_group_mapping",
    ):
        assert removed not in names


def test_read_and_mapping_tools_are_registered() -> None:
    names = _tool_names()
    for present in (
        "list_gremium_memberships",
        "list_role_assignments",
        "list_principals",
        "list_group_mappings",
        "create_group_mapping",
        "update_group_mapping",
        "list_gremium_membership_mappings",
        "create_gremium_membership_mapping",
        "update_gremium_membership_mapping",
        "delete_gremium_membership_mapping",
        "list_gremium_role_mappings",
        "create_gremium_role_mapping",
        "update_gremium_role_mapping",
        "delete_gremium_role_mapping",
    ):
        assert present in names


def test_removed_wire_schemas_are_gone() -> None:
    for removed in (
        "GremiumMembershipCreate",
        "RoleAssignmentCreate",
        "RoleAssignmentUpdate",
        "GremiumGroupMappingCreate",
        "GremiumGroupMappingUpdate",
    ):
        assert not hasattr(S, removed)


# Global group mappings: OIDC group to a global role, no Gremium scope.


def test_group_mapping_schemas_have_no_gremium_id() -> None:
    assert "gremiumId" not in S.GroupMappingCreate.model_fields
    assert "gremiumId" not in S.GroupMappingUpdate.model_fields


def test_create_group_mapping(fake_api: _FakeApi) -> None:
    body = S.GroupMappingCreate(oidcGroup="admins", roleId="r1")
    asyncio.run(admin.create_group_mapping(body))
    assert fake_api.calls == [
        ("POST", "/admin/group-mappings", {"oidcGroup": "admins", "roleId": "r1"})
    ]


def test_update_group_mapping_sends_only_set_keys(fake_api: _FakeApi) -> None:
    asyncio.run(admin.update_group_mapping("m1", S.GroupMappingUpdate(roleId="r2")))
    assert fake_api.calls == [("PATCH", "/admin/group-mappings/m1", {"roleId": "r2"})]


# Membership mappings: OIDC group to the membership in a Gremium.


def test_list_gremium_membership_mappings(fake_api: _FakeApi) -> None:
    asyncio.run(admin.list_gremium_membership_mappings())
    assert fake_api.calls == [("GET", "/admin/gremium-membership-mappings", None)]


def test_create_gremium_membership_mapping(fake_api: _FakeApi) -> None:
    body = S.GremiumMembershipMappingCreate(oidcGroup="stupa-members", gremiumId="g1")
    asyncio.run(admin.create_gremium_membership_mapping(body))
    assert fake_api.calls == [
        (
            "POST",
            "/admin/gremium-membership-mappings",
            {"oidcGroup": "stupa-members", "gremiumId": "g1"},
        )
    ]


def test_update_gremium_membership_mapping_sends_only_set_keys(fake_api: _FakeApi) -> None:
    patch = S.GremiumMembershipMappingUpdate(gremiumId="g2")
    asyncio.run(admin.update_gremium_membership_mapping("m1", patch))
    assert fake_api.calls == [
        ("PATCH", "/admin/gremium-membership-mappings/m1", {"gremiumId": "g2"})
    ]


def test_delete_gremium_membership_mapping(fake_api: _FakeApi) -> None:
    asyncio.run(admin.delete_gremium_membership_mapping("m1"))
    assert fake_api.calls == [("DELETE", "/admin/gremium-membership-mappings/m1", None)]


# Role mappings: OIDC group to a role in a Gremium.


def test_list_gremium_role_mappings(fake_api: _FakeApi) -> None:
    asyncio.run(admin.list_gremium_role_mappings())
    assert fake_api.calls == [("GET", "/admin/gremium-role-mappings", None)]


def test_create_gremium_role_mapping(fake_api: _FakeApi) -> None:
    body = S.GremiumRoleMappingCreate(oidcGroup="stupa-vorstand", gremiumRoleId="r1")
    asyncio.run(admin.create_gremium_role_mapping(body))
    assert fake_api.calls == [
        (
            "POST",
            "/admin/gremium-role-mappings",
            {"oidcGroup": "stupa-vorstand", "gremiumRoleId": "r1"},
        )
    ]


def test_update_gremium_role_mapping_sends_only_set_keys(fake_api: _FakeApi) -> None:
    patch = S.GremiumRoleMappingUpdate(oidcGroup="stupa-board")
    asyncio.run(admin.update_gremium_role_mapping("m1", patch))
    assert fake_api.calls == [
        ("PATCH", "/admin/gremium-role-mappings/m1", {"oidcGroup": "stupa-board"})
    ]


def test_delete_gremium_role_mapping(fake_api: _FakeApi) -> None:
    asyncio.run(admin.delete_gremium_role_mapping("m1"))
    assert fake_api.calls == [("DELETE", "/admin/gremium-role-mappings/m1", None)]


def test_list_gremium_memberships_stays_read_only(fake_api: _FakeApi) -> None:
    asyncio.run(admin.list_gremium_memberships("g1"))
    assert fake_api.calls == [("GET", "/admin/gremien/g1/memberships", None)]
