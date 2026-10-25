"""Board rules: read, configure, the read scope and the members, per board kind."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.auth import policy
from app.modules.auth.principal import Principal
from app.modules.todos import access as access_mod
from app.modules.todos.access import BoardAccess, ReadScope
from tests.unit.modules.todos.fakes import ME, OTHER, ScriptedSession, board

G1 = uuid.UUID(int=11)
G2 = uuid.UUID(int=12)


@pytest.fixture
def grants(monkeypatch: pytest.MonkeyPatch) -> dict[str, set[uuid.UUID]]:
    """The gremien per permission that ``policy.held_gremium_ids`` answers."""
    table: dict[str, set[uuid.UUID]] = {"todo.write": {G1}, "todo.configure": set()}
    calls: list[str] = []

    async def _ids(
        _session: Any, _principal: Principal, perm: str, _now: object = None
    ) -> set[uuid.UUID]:
        calls.append(perm)
        return set(table.get(perm, set()))

    monkeypatch.setattr(policy, "held_gremium_ids", _ids)
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
    """Check the read access for each board kind.

    The gremium lookup runs once per permission.
    """
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
    """Check the configure access for each board kind.

    Configure without the write scope gives no access.
    """
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


_PERSONAL_MINE = {"kind": "personal", "gremium_id": None, "owner_id": ME}
_PERSONAL_OTHER = {"kind": "personal", "gremium_id": None, "owner_id": OTHER}
_TEAM = {"kind": "team", "gremium_id": None, "permission": "platform.manage"}


@pytest.mark.parametrize(
    ("key", "writes"),
    [("todo.read_all", False), ("todo.all", True)],
)
async def test_a_global_key_reads_every_shared_board_and_no_foreign_personal_one(
    grants: dict[str, Any], key: str, writes: bool
) -> None:
    """Let a global key read every shared board but no foreign personal board.

    Neither key configures a board. The own personal board keeps the owner rule.
    """
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    holder = _p(permissions={key})
    for shared in (board(gremium_id=G2), board(**_TEAM)):
        assert await access.can_read(shared, holder)
        assert await access.can_write(shared, holder) is writes
        assert not await access.can_configure(shared, holder)
    assert not await access.can_read(board(**_PERSONAL_OTHER), holder)
    assert not await access.can_write(board(**_PERSONAL_OTHER), holder)
    assert await access.can_write(board(**_PERSONAL_MINE), holder)


async def test_the_native_writer_writes_and_a_plain_member_does_not(
    grants: dict[str, Any],
) -> None:
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    user = _p(permissions={"platform.manage"})
    assert await access.can_write(board(gremium_id=G1), user)
    assert not await access.can_write(board(gremium_id=G2), user)
    assert await access.can_write(board(**_TEAM), user)
    assert not await access.can_write(board(kind="team", gremium_id=None, permission=None), user)
    assert not await access.can_read(board(gremium_id=G2), user)


@pytest.mark.parametrize(
    ("scope", "reads", "writes"),
    [
        (frozenset({"todo.read_all"}), True, False),
        (frozenset({"todo.write", "todo.configure", "todo.all"}), True, True),
        (frozenset({"vote.manage"}), False, False),
    ],
)
async def test_the_scope_caps_the_global_keys(
    grants: dict[str, Any], scope: frozenset[str], reads: bool, writes: bool
) -> None:
    """Cap the global keys with the token scope.

    The ``read`` scope holds ``todo.read_all``, so it reads and never writes. The
    ``todos:write`` scope holds ``todo.all``. A team board through a global key also needs
    its own permission in the scope.
    """
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    token = _p(permissions={"todo.all", "todo.read_all"}, scope_permissions=scope)
    assert await access.can_read(board(gremium_id=G2), token) is reads
    assert await access.can_write(board(gremium_id=G2), token) is writes
    assert not await access.can_read(board(**_TEAM), token)
    assert not await access.can_write(board(**_TEAM), token)
    wide = _p(
        permissions={"todo.all", "todo.read_all"}, scope_permissions=scope | {"platform.manage"}
    )
    assert await access.can_read(board(**_TEAM), wide) is reads
    assert await access.can_write(board(**_TEAM), wide) is writes


async def test_an_admin_read_token_reads_every_gremium_board_but_writes_none(
    grants: dict[str, Any],
) -> None:
    """Let an admin read token read every gremium board but write none.

    The team board "Plattform" (``ticket.manage``) stays closed to a ``read`` token.
    """
    access = BoardAccess(
        ScriptedSession(scalar=[ME], scalars=[["ticket.manage", "platform.manage"]])  # type: ignore[arg-type]
    )
    token = _p(
        roles=["admin"],
        scope_permissions=frozenset({"todo.read_all", "meeting.view_all", "platform.manage"}),
    )
    assert await access.can_read(board(gremium_id=G2), token)
    assert not await access.can_write(board(gremium_id=G2), token)
    assert not await access.can_read(board(**_PERSONAL_MINE), token)
    plattform = board(kind="team", gremium_id=None, permission="ticket.manage")
    assert not await access.can_read(plattform, token)
    assert await access.can_read(board(**_TEAM), token)
    scope = await access.scope(token)
    assert scope == ReadScope(all_gremien=True, team_permissions={"platform.manage"})
    assert not scope.allows(plattform) and scope.allows(board(**_TEAM))


@pytest.mark.parametrize("key", ["todo.read_all", "todo.all"])
async def test_the_read_scope_of_a_global_key_holds_every_shared_board(
    grants: dict[str, Any], key: str
) -> None:
    """Put every shared board in the read scope of a global key.

    No team-permission query runs, because every team board is in the scope already.
    """
    session = ScriptedSession(scalar=[ME])
    scope = await BoardAccess(session).scope(_p(permissions={key}))  # type: ignore[arg-type]
    assert scope == ReadScope(all_gremien=True, owner_id=ME, all_teams=True)
    assert len(session.statements) == 1
    sql = str(scope.condition())
    assert sql.count("todo_board.kind") == 2 and "gremium_id IN" not in sql
    assert scope.allows(board(gremium_id=G2))
    assert scope.allows(board(kind="team", gremium_id=None, permission="other.key"))
    assert not scope.allows(board(**_PERSONAL_OTHER))
    assert scope.allows(board(**_PERSONAL_MINE))


def test_the_token_gate_lets_every_read_key_through() -> None:
    assert access_mod.token_reads(_p())
    for key in ("todo.write", "todo.all", "todo.read_all"):
        assert access_mod.token_reads(_p(scope_permissions=frozenset({key})))
    assert not access_mod.token_reads(_p(scope_permissions=frozenset({"todo.configure"})))
