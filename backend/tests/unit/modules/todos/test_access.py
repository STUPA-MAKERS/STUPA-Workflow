"""Board rules: the role per board kind, the read scope and the members (spec 001078)."""

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
G3 = uuid.UUID(int=13)
FREE = uuid.UUID(int=21)


class Grants:
    """What the lookups answer: memberships, configure gremien and entry roles."""

    def __init__(self) -> None:
        self.member: set[uuid.UUID] = {G1}
        self.configure: set[uuid.UUID] = set()
        self.entries: dict[uuid.UUID, int] = {}
        self.calls: list[str] = []


@pytest.fixture
def grants(monkeypatch: pytest.MonkeyPatch) -> Grants:
    """Patch the membership, the configure and the entry lookups of ``access``."""
    table = Grants()

    async def _members(_session: Any, _principal: Principal) -> frozenset[uuid.UUID]:
        table.calls.append("member")
        return frozenset(table.member)

    async def _held(_session: Any, principal: Principal, perm: str) -> set[uuid.UUID]:
        table.calls.append(perm)
        return set(table.configure) if principal.scope_allows(perm) else set()

    async def _entries(_session: Any, _me: uuid.UUID | None, _gremien: Any) -> dict[uuid.UUID, int]:
        table.calls.append("entries")
        return dict(table.entries)

    monkeypatch.setattr(access_mod, "member_gremium_ids", _members)
    monkeypatch.setattr(policy, "held_gremium_ids", _held)
    monkeypatch.setattr(access_mod, "entry_roles", _entries)
    return table


def _p(**kw: Any) -> Principal:
    return Principal(sub=kw.pop("sub", "me-sub"), **kw)


def _free(**kw: Any) -> Any:
    return board(id=kw.pop("id", FREE), kind="free", gremium_id=None, **kw)


_PERSONAL_MINE = {"kind": "personal", "gremium_id": None, "owner_id": ME}
_PERSONAL_OTHER = {"kind": "personal", "gremium_id": None, "owner_id": OTHER}
_TEAM = {"kind": "team", "gremium_id": None, "permission": "platform.manage"}


def test_read_scope_condition_and_allows() -> None:
    empty = ReadScope()
    assert str(empty.condition()) == "false"
    full = ReadScope(all_gremien=True, owner_id=ME, team_permissions={"platform.manage"})
    sql = str(full.condition())
    assert "todo_board.kind" in sql and "owner_id" in sql and "permission" in sql
    assert "archived_at IS NULL" in sql
    some = ReadScope(gremium_ids={G1}, board_ids={FREE})
    assert "gremium_id IN" in str(some.condition()) and "todo_board.id IN" in str(some.condition())
    assert some.allows(board(gremium_id=G1))
    assert not some.allows(board(gremium_id=G2))
    assert some.allows(_free())
    assert not some.allows(_free(id=uuid.uuid4()))
    assert full.allows(board(gremium_id=G2))
    assert full.allows(_free(id=uuid.uuid4()))
    assert full.allows(board(**_PERSONAL_MINE))
    assert not some.allows(board(**_PERSONAL_MINE))
    assert full.allows(board(**_TEAM))
    assert not some.allows(board(**_TEAM))


async def test_me_is_cached_per_sub() -> None:
    session = ScriptedSession(scalar=[ME])
    access = BoardAccess(session)  # type: ignore[arg-type]
    assert await access.me(_p()) == ME
    assert await access.me(_p()) == ME
    assert len(session.statements) == 1


async def test_every_member_of_the_gremium_edits_its_board(grants: Grants) -> None:
    """Let each member edit the gremium board, whatever the gremium role (spec 001078)."""
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    user = _p()
    assert await access.role(board(gremium_id=G1), user) == access_mod.EDIT
    assert await access.can_write(board(gremium_id=G1), user)
    assert not await access.can_configure(board(gremium_id=G1), user)
    assert not await access.can_read(board(gremium_id=G2), user)
    assert grants.calls.count("member") == 1


async def test_todo_configure_in_the_gremium_manages_its_board(grants: Grants) -> None:
    grants.configure = {G1}
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    assert await access.can_configure(board(gremium_id=G1), _p())
    writer = _p(scope_permissions=frozenset({"todo.write"}))
    assert not await access.can_configure(board(gremium_id=G1), writer)
    assert await access.can_write(board(gremium_id=G1), writer)


async def test_an_entry_adds_its_role_to_a_gremium_board(grants: Grants) -> None:
    """Give a person outside the gremium the role of an entry (spec 001077)."""
    grants.member = set()
    reader = board(gremium_id=G2)
    editor = board(gremium_id=G3)
    grants.entries = {reader.id: access_mod.READ, editor.id: access_mod.EDIT}
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    assert await access.can_read(reader, _p())
    assert not await access.can_write(reader, _p())
    assert await access.can_write(editor, _p())
    assert not await access.can_configure(editor, _p())


async def test_a_free_board_follows_its_entries(grants: Grants) -> None:
    """Read, write and configure a free board by the best entry role (spec 001062)."""
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    assert not await access.can_read(_free(), _p())
    for rank, reads, writes, manages in (
        (access_mod.READ, True, False, False),
        (access_mod.EDIT, True, True, False),
        (access_mod.MANAGE, True, True, True),
    ):
        grants.entries = {FREE: rank}
        fresh = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
        assert await fresh.can_read(_free(), _p()) is reads
        assert await fresh.can_write(_free(), _p()) is writes
        assert await fresh.can_configure(_free(), _p()) is manages


async def test_personal_and_team_boards(grants: Grants) -> None:
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    user = _p(permissions={"platform.manage"})
    assert await access.can_configure(board(**_PERSONAL_MINE), user)
    assert not await access.can_read(board(**_PERSONAL_OTHER), user)
    assert not await access.can_read(board(kind="personal", gremium_id=None, owner_id=None), user)
    assert await access.can_configure(board(**_TEAM), user)
    assert not await access.can_read(board(kind="team", gremium_id=None, permission=None), user)
    assert not await access.can_read(board(**_TEAM), _p())


async def test_the_admin_manages_every_shared_board_but_no_foreign_personal_one(
    grants: Grants,
) -> None:
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    admin = _p(roles=["admin"])
    assert await access.can_configure(board(gremium_id=G2), admin)
    assert await access.can_configure(_free(), admin)
    assert not await access.can_read(board(**_PERSONAL_OTHER), admin)


async def test_a_token_without_the_scope_reads_nothing(grants: Grants) -> None:
    access = BoardAccess(ScriptedSession())  # type: ignore[arg-type]
    token = _p(roles=["admin"], scope_permissions=frozenset({"vote.cast"}))
    assert not await access.can_read(board(gremium_id=G1), token)
    assert not await access.can_configure(board(gremium_id=G1), token)
    scope = await access.scope(token)
    assert scope == ReadScope()
    assert await access.scope(token) is scope


async def test_scope_of_a_member_and_of_an_admin(grants: Grants) -> None:
    grants.entries = {FREE: access_mod.READ}
    session = ScriptedSession(scalar=[ME], scalars=[["platform.manage", None, "x.y"]])
    access = BoardAccess(session)  # type: ignore[arg-type]
    scope = await access.scope(_p(permissions={"platform.manage"}))
    assert scope == ReadScope(
        all_gremien=False,
        gremium_ids={G1},
        owner_id=ME,
        team_permissions={"platform.manage"},
        board_ids={FREE},
    )
    session = ScriptedSession(scalar=[ME], scalars=[[]])
    scope = await BoardAccess(session).scope(_p(roles=["admin"]))  # type: ignore[arg-type]
    assert scope.all_gremien and scope.gremium_ids == set() and scope.board_ids == set()


@pytest.mark.parametrize(
    ("key", "writes"),
    [("todo.read_all", False), ("todo.all", True)],
)
async def test_a_global_key_reads_every_shared_board_and_no_foreign_personal_one(
    grants: Grants, key: str, writes: bool
) -> None:
    """Let a global key read every shared board, free boards too (spec 001066).

    Neither key configures a board. The own personal board keeps the owner rule.
    """
    grants.member = set()
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    holder = _p(permissions={key})
    for shared in (board(gremium_id=G2), board(**_TEAM), _free()):
        assert await access.can_read(shared, holder)
        assert await access.can_write(shared, holder) is writes
        assert not await access.can_configure(shared, holder)
    assert not await access.can_read(board(**_PERSONAL_OTHER), holder)
    assert await access.can_write(board(**_PERSONAL_MINE), holder)


@pytest.mark.parametrize(
    ("scope", "reads", "writes"),
    [
        (frozenset({"todo.read_all"}), True, False),
        (frozenset({"todo.write", "todo.configure", "todo.all"}), True, True),
        (frozenset({"vote.manage"}), False, False),
    ],
)
async def test_the_scope_caps_the_global_keys(
    grants: Grants, scope: frozenset[str], reads: bool, writes: bool
) -> None:
    """Cap the global keys with the token scope; a team board needs its own permission."""
    grants.member = set()
    access = BoardAccess(ScriptedSession(scalar=[ME]))  # type: ignore[arg-type]
    token = _p(permissions={"todo.all", "todo.read_all"}, scope_permissions=scope)
    assert await access.can_read(board(gremium_id=G2), token) is reads
    assert await access.can_write(board(gremium_id=G2), token) is writes
    assert not await access.can_read(board(**_TEAM), token)
    wide = _p(
        permissions={"todo.all", "todo.read_all"}, scope_permissions=scope | {"platform.manage"}
    )
    assert await access.can_read(board(**_TEAM), wide) is reads
    assert await access.can_write(board(**_TEAM), wide) is writes


async def test_an_admin_read_token_reads_every_gremium_board_but_writes_none(
    grants: Grants,
) -> None:
    """The team board "Plattform" (``ticket.manage``) stays closed to a ``read`` token."""
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


@pytest.mark.parametrize("key", ["todo.read_all", "todo.all"])
async def test_the_read_scope_of_a_global_key_holds_every_shared_board(
    grants: Grants, key: str
) -> None:
    session = ScriptedSession(scalar=[ME])
    scope = await BoardAccess(session).scope(_p(permissions={key}))  # type: ignore[arg-type]
    assert scope == ReadScope(all_gremien=True, owner_id=ME, all_teams=True)
    assert scope.allows(board(gremium_id=G2))
    assert scope.allows(_free(id=uuid.uuid4()))
    assert scope.allows(board(kind="team", gremium_id=None, permission="other.key"))
    assert not scope.allows(board(**_PERSONAL_OTHER))


async def test_members_of_each_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _holders(_session: Any, perm: str) -> list[tuple[uuid.UUID, str | None, str | None]]:
        assert perm == "platform.manage"
        return [(OTHER, "Zora", None), (ME, None, "ada@x.org")]

    monkeypatch.setattr(access_mod, "permission_holders", _holders)
    session = ScriptedSession(
        execute=[
            [(ME, "Ada", None)],
            [(OTHER, None, None), (ME, "Ada", None)],
            [(ME, "Ada", None)],
        ]
    )
    access = BoardAccess(session)  # type: ignore[arg-type]
    personal = await access.members(board(**_PERSONAL_MINE))
    assert [(m.principal_id, m.display_name) for m in personal] == [(ME, "Ada")]
    assert await access.member_ids(board()) == {ME, OTHER}
    sql = str(session.statements[-1])
    assert "gremium_membership" in sql and "todo_board_entry" in sql
    assert await access.member_ids(_free()) == {ME}
    team = await access.members(board(**_TEAM))
    assert [m.display_name for m in team] == ["ada@x.org", "Zora"]


async def test_agenda_gremien_are_the_own_gremium_and_the_entries() -> None:
    session = ScriptedSession(scalars=[[G2, None], [G3]])
    access = BoardAccess(session)  # type: ignore[arg-type]
    assert await access.agenda_gremien(board(gremium_id=G1)) == {G1, G2}
    assert await access.agenda_gremien(_free()) == {G3}
    assert await access.agenda_gremien(board(**_TEAM)) == set()


def test_the_token_gate_lets_every_read_key_through() -> None:
    assert access_mod.token_reads(_p())
    for key in ("todo.write", "todo.all", "todo.read_all"):
        assert access_mod.token_reads(_p(scope_permissions=frozenset({key})))
    assert not access_mod.token_reads(_p(scope_permissions=frozenset({"todo.configure"})))


def test_who_creates_a_free_board() -> None:
    assert access_mod.can_create_board(_p(roles=["admin"]))
    assert access_mod.can_create_board(_p(permissions={"todo.create_board"}))
    assert not access_mod.can_create_board(_p(permissions={"todo.all"}))
