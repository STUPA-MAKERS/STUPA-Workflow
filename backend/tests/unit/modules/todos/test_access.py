"""Board rules: read, configure, the read scope and the members, per board kind."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.auth.principal import Principal
from app.modules.todos import access as access_mod
from app.modules.todos.access import BoardAccess, ReadScope
from tests.unit.modules.todos.fakes import ME, OTHER, ScriptedSession, board

G1 = uuid.UUID(int=11)
G2 = uuid.UUID(int=12)


@pytest.fixture
def grants(monkeypatch: pytest.MonkeyPatch) -> dict[str, set[uuid.UUID]]:
    """The gremien per permission that ``gremium_ids_for`` answers."""
    table: dict[str, set[uuid.UUID]] = {"todo.write": {G1}, "todo.configure": set()}
    calls: list[str] = []

    async def _ids(_session: Any, _principal: Principal, perm: str) -> set[uuid.UUID]:
        calls.append(perm)
        return set(table.get(perm, set()))

    monkeypatch.setattr(access_mod, "gremium_ids_for", _ids)
    table["_calls"] = calls  # type: ignore[assignment]
    return table


def _p(**kw: Any) -> Principal:
    return Principal(sub=kw.pop("sub", "me-sub"), **kw)


def test_read_scope_condition_and_allows() -> None:
    empty = ReadScope()
    assert str(empty.condition()) == "false"
    full = ReadScope(all_gremien=True, owner_id=ME, team_permissions={"platform.manage"})
    sql = str(full.condition())
    assert "todo_board.kind" in sql and "owner_id" in sql and "permission" in sql
    some = ReadScope(gremium_ids={G1})
    assert "gremium_id IN" in str(some.condition())
    assert some.allows(board(gremium_id=G1))
    assert not some.allows(board(gremium_id=G2))
    assert full.allows(board(gremium_id=G2))
    assert full.allows(board(kind="personal", gremium_id=None, owner_id=ME))
    assert not some.allows(board(kind="personal", gremium_id=None, owner_id=ME))
    assert full.allows(board(kind="team", gremium_id=None, permission="platform.manage"))
    assert not some.allows(board(kind="team", gremium_id=None, permission="platform.manage"))


async def test_me_is_cached_per_sub() -> None:
    session = ScriptedSession(scalar=[ME])
    access = BoardAccess(session)  # type: ignore[arg-type]
    assert await access.me(_p()) == ME
    assert await access.me(_p()) == ME
    assert len(session.statements) == 1


async def test_can_read_per_kind(grants: dict[str, Any]) -> None:
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    user = _p(permissions={"platform.manage"})
    assert await access.can_read(board(gremium_id=G1), user)
    assert not await access.can_read(board(gremium_id=G2), user)
    assert await access.can_read(board(kind="personal", gremium_id=None, owner_id=ME), user)
    assert not await access.can_read(board(kind="personal", gremium_id=None, owner_id=OTHER), user)
    assert not await access.can_read(board(kind="personal", gremium_id=None, owner_id=None), user)
    team = board(kind="team", gremium_id=None, permission="platform.manage")
    assert await access.can_read(team, user)
    assert not await access.can_read(board(kind="team", gremium_id=None, permission=None), user)
    assert not await access.can_read(team, _p())
    # The gremium lookup runs once per permission.
    assert grants["_calls"] == ["todo.write"]


async def test_the_admin_reads_every_gremium_board_but_no_foreign_personal_one(
    grants: dict[str, Any],
) -> None:
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    admin = _p(roles=["admin"])
    assert await access.can_read(board(gremium_id=G2), admin)
    assert await access.can_configure(board(gremium_id=G2), admin)
    assert not await access.can_read(board(kind="personal", gremium_id=None, owner_id=OTHER), admin)


async def test_a_token_without_the_scope_reads_nothing(grants: dict[str, Any]) -> None:
    access = BoardAccess(ScriptedSession())  # type: ignore[arg-type]
    token = _p(roles=["admin"], scope_permissions=frozenset({"vote.cast"}))
    assert not await access.can_read(board(gremium_id=G1), token)
    assert not await access.can_configure(board(gremium_id=G1), token)
    scope = await access.scope(token)
    assert scope == ReadScope()
    assert await access.scope(token) is scope


async def test_can_configure_per_kind(grants: dict[str, Any]) -> None:
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    user = _p(permissions={"platform.manage"})
    assert not await access.can_configure(board(gremium_id=G1), user)
    grants["todo.configure"] = {G1}
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    assert await access.can_configure(board(gremium_id=G1), user)
    assert not await access.can_configure(board(gremium_id=G2), user)
    assert await access.can_configure(board(kind="personal", gremium_id=None, owner_id=ME), user)
    team = board(kind="team", gremium_id=None, permission="platform.manage")
    assert await access.can_configure(team, user)
    # Configure without write scope: no.
    writer = _p(scope_permissions=frozenset({"todo.write"}))
    assert not await access.can_configure(team, writer)


async def test_scope_of_a_member_and_of_an_admin(grants: dict[str, Any]) -> None:
    session = ScriptedSession(scalar=[ME], scalars=[["platform.manage", None, "x.y"]])
    access = BoardAccess(session)  # type: ignore[arg-type]
    scope = await access.scope(_p(permissions={"platform.manage"}))
    assert scope == ReadScope(
        all_gremien=False, gremium_ids={G1}, owner_id=ME, team_permissions={"platform.manage"}
    )
    session = ScriptedSession(scalar=[ME], scalars=[[]])
    scope = await BoardAccess(session).scope(_p(roles=["admin"]))  # type: ignore[arg-type]
    assert scope.all_gremien and scope.gremium_ids == set()


async def test_members_of_each_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _holders(_session: Any, perm: str) -> list[tuple[uuid.UUID, str | None, str | None]]:
        assert perm == "platform.manage"
        return [(OTHER, "Zora", None), (ME, None, "ada@x.org")]

    monkeypatch.setattr(access_mod, "permission_holders", _holders)
    session = ScriptedSession(
        execute=[[(ME, "Ada", None)], [(OTHER, None, None), (ME, "Ada", None)]]
    )
    access = BoardAccess(session)  # type: ignore[arg-type]
    personal = await access.members(board(kind="personal", gremium_id=None, owner_id=ME))
    assert [(m.principal_id, m.display_name) for m in personal] == [(ME, "Ada")]
    gremium = await access.member_ids(board())
    assert gremium == {ME, OTHER}
    assert "gremium_membership" in str(session.statements[-1])
    team = await access.members(board(kind="team", gremium_id=None, permission="platform.manage"))
    assert [m.display_name for m in team] == ["ada@x.org", "Zora"]
    team_none = board(kind="team", gremium_id=None, permission=None)
    monkeypatch.setattr(access_mod, "permission_holders", _empty_holders)
    assert await access.members(team_none) == []


async def _empty_holders(_session: Any, perm: str) -> list[tuple[uuid.UUID, str, str]]:
    assert perm == ""
    return []
