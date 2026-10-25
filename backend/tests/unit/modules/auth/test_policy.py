"""The shared gremium policy: the admin bypass, the own role and the scope cap."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.admin import gremium_roles
from app.modules.auth import oauth, policy
from app.modules.auth.policy import (
    ALL_GREMIEN,
    expand,
    gremium_ids_with,
    has_gremium_permission,
    held_gremium_ids,
    holds_gremium_permission,
)
from app.modules.auth.principal import Principal
from tests._support.flow_fakes import fake_session

GID = uuid4()
OTHER = uuid4()
DB = fake_session()


@pytest.fixture(autouse=True)
def roles(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every principal holds ``session.manage`` in GID; the list records the reads."""
    reads: list[str] = []

    async def _ids(_s: Any, _sub: str, perm: str, _now: object = None) -> set[UUID]:
        reads.append(perm)
        return {GID} if perm == "session.manage" else set()

    monkeypatch.setattr(gremium_roles, "gremium_ids_with_permission", _ids)
    return reads


def _token(*scopes: str, roles: list[str] | None = None) -> Principal:
    return Principal(
        sub="t", roles=roles or [], scope_permissions=oauth.scope_permissions(list(scopes))
    )


def test_all_gremien_holds_every_id() -> None:
    assert GID in ALL_GREMIEN
    assert None in ALL_GREMIEN
    assert repr(ALL_GREMIEN) == "ALL_GREMIEN"


def test_expand_turns_the_bypass_into_the_given_ids() -> None:
    assert expand(ALL_GREMIEN, [GID, OTHER]) == {GID, OTHER}
    assert expand({GID}, [GID, OTHER]) == {GID}


async def test_held_gremium_ids_reads_the_own_role(roles: list[str]) -> None:
    assert await held_gremium_ids(DB, Principal(sub="m"), "session.manage") == {GID}
    assert roles == ["session.manage"]


async def test_held_gremium_ids_caps_by_scope_without_a_read(roles: list[str]) -> None:
    assert await held_gremium_ids(DB, _token("read"), "session.manage") == set()
    assert roles == []


async def test_held_gremium_ids_skips_the_admin_bypass() -> None:
    admin = Principal(sub="a", roles=["admin"])
    assert await held_gremium_ids(DB, admin, "vote.manage") == set()
    assert not await holds_gremium_permission(DB, admin, "vote.manage", GID)


async def test_gremium_ids_with_gives_all_gremien_to_the_admin(roles: list[str]) -> None:
    admin = Principal(sub="a", roles=["admin"])
    assert await gremium_ids_with(DB, admin, "vote.manage") is ALL_GREMIEN
    assert roles == []


async def test_gremium_ids_with_caps_the_admin_token() -> None:
    token = _token("read", roles=["admin"])
    assert await gremium_ids_with(DB, token, "session.manage") == set()
    meetings = _token("meetings:write", roles=["admin"])
    assert await gremium_ids_with(DB, meetings, "session.manage") is ALL_GREMIEN


async def test_has_gremium_permission_per_gremium() -> None:
    member = Principal(sub="m")
    assert await has_gremium_permission(DB, member, "session.manage", GID)
    assert not await has_gremium_permission(DB, member, "session.manage", OTHER)
    assert await holds_gremium_permission(DB, member, "session.manage", GID)
    admin = Principal(sub="a", roles=["admin"])
    assert await has_gremium_permission(DB, admin, "vote.manage", OTHER)


def test_admin_bypass_needs_the_role_and_the_scope() -> None:
    assert policy.admin_bypass(Principal(sub="a", roles=["admin"]), "vote.manage")
    assert not policy.admin_bypass(_token("read", roles=["admin"]), "vote.manage")
    assert not policy.admin_bypass(Principal(sub="m"), "vote.manage")


async def test_gremium_view_scope_per_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _members(_s: Any, _sub: str, _now: object = None) -> set[UUID]:
        return {GID}

    monkeypatch.setattr(gremium_roles, "gremium_member_ids", _members)
    view_all = Principal(sub="v", permissions={policy.GREMIUM_VIEW_ALL})
    assert await policy.gremium_view_scope(DB, view_all) is None
    assert await policy.gremium_view_scope(DB, Principal(sub="m")) == {GID}
    assert await policy.gremium_view_scope(DB, _token("budget:write")) == set()
    assert await policy.can_view_gremium(DB, view_all, OTHER)
    assert await policy.can_view_gremium(DB, Principal(sub="m"), GID)
    assert not await policy.can_view_gremium(DB, Principal(sub="m"), OTHER)
