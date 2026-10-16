"""``TodoService``: boards, columns and labels with a scripted session."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.auth.principal import Principal
from app.modules.todos import service as svc_mod
from app.modules.todos.access import ReadScope
from app.modules.todos.models import TodoColumn, TodoLabel
from app.modules.todos.schemas import BoardPatch, ColumnPatch, LabelCreate, LabelPatch
from app.modules.todos.service import TodoService
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from tests.unit.modules.todos.fakes import (
    ME,
    USER,
    FakeAccess,
    FakeLinks,
    ScriptedSession,
    board,
    card,
    column,
    label,
)

OUT = object()


def _svc(session: ScriptedSession, **kw: Any) -> TodoService:
    return TodoService(
        session,  # type: ignore[arg-type]
        access=kw.pop("access", FakeAccess(**kw)),  # type: ignore[arg-type]
        links=FakeLinks(),  # type: ignore[arg-type]
    )


def _stub(service: TodoService) -> list[Any]:
    """Replace the board read at the end of a write; return its calls."""
    calls: list[Any] = []

    async def _out(b: Any, _p: Any) -> Any:
        calls.append(b)
        return OUT

    service._board_out = _out  # type: ignore[method-assign]
    return calls


# -- list -------------------------------------------------------------------------


async def test_list_boards_needs_the_scope() -> None:
    token = Principal(sub="t", scope_permissions=frozenset({"vote.cast"}))
    with pytest.raises(ForbiddenError):
        await _svc(ScriptedSession()).list_boards(token)


async def test_list_boards_sorts_counts_and_creates_the_personal_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensured: list[uuid.UUID] = []

    async def _ensure(_s: Any, owner: uuid.UUID) -> bool:
        ensured.append(owner)
        return True

    monkeypatch.setattr(svc_mod, "ensure_personal_board", _ensure)
    personal = board(kind="personal", gremium_id=None, owner_id=ME, name="Meine To-Dos")
    stupa = board(name="StuPa")
    asta = board(name="asta")
    team = board(kind="team", gremium_id=None, permission="platform.manage", name="Plattform")
    session = ScriptedSession(
        scalars=[[team, stupa, personal, asta]], execute=[[(stupa.id, 3), (personal.id, 1)]]
    )
    out = await _svc(session).list_boards(USER, gremium_id=stupa.gremium_id)
    assert [b.name for b in out] == ["Meine To-Dos", "asta", "StuPa", "Plattform"]
    assert [b.open_count for b in out] == [1, 0, 3, 0]
    assert all(b.can_write and b.can_configure for b in out)
    assert ensured == [ME]
    assert "todo_board.gremium_id =" in str(session.statements[0])


async def test_list_boards_without_an_account_or_boards(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _never(_s: Any, _owner: uuid.UUID) -> bool:
        raise AssertionError("no account, no personal board")

    monkeypatch.setattr(svc_mod, "ensure_personal_board", _never)
    session = ScriptedSession(scalars=[[]])
    assert await _svc(session, me=None, scope=ReadScope()).list_boards(USER) == []


# -- board read ---------------------------------------------------------------------


async def test_board_404_when_unknown_or_unreadable() -> None:
    with pytest.raises(NotFoundError):
        await _svc(ScriptedSession()).board(uuid.uuid4(), USER)
    b = board()
    session = ScriptedSession()
    session.put(b)
    with pytest.raises(NotFoundError):
        await _svc(session, read=False).board(b.id, USER)


async def test_board_out_orders_counts_and_builds_tiles() -> None:
    b = board()
    first, done = column(b.id, "Offen", 0), column(b.id, "Erledigt", 1, is_done=True)
    lab = label(b.id)
    c1 = card(b, done, rank="a")
    c2 = card(b, first, rank="z")
    stray = card(b, column(b.id, "Weg", 9), rank="b")
    session = ScriptedSession(
        scalars=[[first, done], [lab], [c1, c2, stray], []],
        scalar=[2],
        execute=[[(c1.id, lab.id)], [(c1.id, ME)], [(c1.id, 3, 1)], [(c2.id, 4)]],
    )
    session.put(b)
    out = await _svc(session, configure=False).board(b.id, USER)
    assert [c.id for c in out.cards] == [c2.id, c1.id, stray.id]
    assert [c.card_count for c in out.columns] == [1, 1]
    assert out.archived_count == 2 and out.can_configure is False
    assert out.labels[0].name == "Wichtig"
    tile = out.cards[1]
    assert tile.label_ids == [lab.id]
    assert tile.checklist.done == 1 and tile.checklist.total == 3
    assert out.cards[0].comment_count == 4
    assert tile.assignees[0].principal_id is None  # unknown person: deleted


async def test_board_out_of_an_empty_board() -> None:
    b = board()
    session = ScriptedSession(scalars=[[], [], []], scalar=[None])
    session.put(b)
    out = await _svc(session).board(b.id, USER)
    assert out.cards == [] and out.archived_count == 0


# -- board writes -------------------------------------------------------------------


async def test_patch_board_needs_configure() -> None:
    b = board()
    session = ScriptedSession()
    session.put(b)
    with pytest.raises(ForbiddenError) as exc:
        await _svc(session, configure=False).patch_board(b.id, BoardPatch(name="x"), USER)
    assert exc.value.code == "todo_configure_required"


async def test_patch_board_renames_and_sets_the_archive_days() -> None:
    b = board()
    session = ScriptedSession()
    session.put(b)
    service = _svc(session)
    _stub(service)
    payload = BoardPatch.model_validate({"name": "  Neu  ", "archiveAfterDays": None})
    assert await service.patch_board(b.id, payload, USER) is OUT
    assert (b.name, b.archive_after_days) == ("Neu", None)
    await service.patch_board(b.id, BoardPatch(name=" "), USER)
    assert b.name == "Neu"
    await service.patch_board(b.id, BoardPatch.model_validate({"archiveAfterDays": 7}), USER)
    assert b.archive_after_days == 7 and session.committed == 3


async def test_members_and_archive() -> None:
    b = board()
    c = card(b, column(b.id))
    session = ScriptedSession(scalar=[1, 0], scalars=[[c], [], []], execute=[[], [], [], []])
    session.put(b)
    service = _svc(session)
    assert [m.principal_id for m in await service.members(b.id, USER)] != []
    page = await service.archive(b.id, USER, q=" Plak%t ", limit=10, offset=0)
    assert page.total == 1 and page.items[0].id == c.id
    assert "LIKE" in str(session.statements[0]).upper()
    empty = await service.archive(b.id, USER)
    assert empty.total == 0 and empty.items == []


# -- columns ------------------------------------------------------------------------


async def test_add_column_appends() -> None:
    b = board()
    session = ScriptedSession(scalars=[[column(b.id, position=4)], []])
    session.put(b)
    service = _svc(session)
    _stub(service)
    await service.add_column(b.id, " Neu ", USER)
    await service.add_column(b.id, "Erste", USER)
    added = [o for o in session.added if isinstance(o, TodoColumn)]
    assert [(c.name, c.position) for c in added] == [("Neu", 5), ("Erste", 0)]


async def test_patch_column_unknown_or_foreign() -> None:
    b = board()
    foreign = column(uuid.uuid4())
    session = ScriptedSession()
    session.put(b, foreign)
    service = _svc(session)
    with pytest.raises(NotFoundError):
        await service.patch_column(b.id, uuid.uuid4(), ColumnPatch(name="x"), USER)
    with pytest.raises(NotFoundError):
        await service.patch_column(b.id, foreign.id, ColumnPatch(name="x"), USER)


async def test_patch_column_renames_and_moves_the_done_flag() -> None:
    b = board()
    first, done = column(b.id, "Offen"), column(b.id, "Erledigt", 1, is_done=True)
    old_done = card(b, done, completed_at=svc_mod._now())
    new_done = card(b, first)
    kept = card(b, first, completed_at=svc_mod._now())
    session = ScriptedSession(scalars=[[first, done], [old_done], [new_done, kept]])
    session.put(b, first, done)
    service = _svc(session)
    _stub(service)
    stamp = kept.completed_at
    payload = ColumnPatch.model_validate({"name": " Fertig ", "isDone": True})
    await service.patch_column(b.id, first.id, payload, USER)
    assert first.name == "Fertig" and first.is_done and not done.is_done
    assert old_done.completed_at is None
    assert new_done.completed_at is not None and kept.completed_at == stamp
    assert session.flushed == 1
    # The done column again: nothing moves.
    await service.patch_column(b.id, first.id, ColumnPatch.model_validate({"isDone": True}), USER)
    await service.patch_column(b.id, first.id, ColumnPatch(name=" "), USER)
    assert first.name == "Fertig" and session.flushed == 1


async def test_order_columns() -> None:
    b = board()
    a, c = column(b.id, "A", 0), column(b.id, "C", 1)
    session = ScriptedSession(scalars=[[a, c], [a, c], [a, c]])
    session.put(b)
    service = _svc(session)
    _stub(service)
    with pytest.raises(ValidationProblem):
        await service.order_columns(b.id, [a.id], USER)
    with pytest.raises(ValidationProblem):
        await service.order_columns(b.id, [a.id, uuid.uuid4()], USER)
    await service.order_columns(b.id, [c.id, a.id], USER)
    assert (c.position, a.position) == (0, 1)


async def test_delete_column_rules() -> None:
    b = board()
    done = column(b.id, "Erledigt", 2, is_done=True)
    col = column(b.id, "Wartet", 1)
    other_board_col = column(uuid.uuid4())
    c = card(b, col)
    session = ScriptedSession(scalars=[[c], [c], [c]])
    session.put(b, done, col, other_board_col)
    service = _svc(session)
    with pytest.raises(ConflictError) as exc:
        await service.delete_column(b.id, done.id, USER)
    assert exc.value.code == "done_column_required"
    with pytest.raises(ConflictError) as exc:
        await service.delete_column(b.id, col.id, USER)
    assert exc.value.code == "column_not_empty"
    with pytest.raises(ValidationProblem):
        await service.delete_column(b.id, col.id, USER, move_to=other_board_col.id)
    with pytest.raises(ValidationProblem):
        await service.delete_column(b.id, col.id, USER, move_to=col.id)


async def test_delete_column_moves_the_cards_and_renumbers() -> None:
    b = board()
    first = column(b.id, "Offen", 0)
    col = column(b.id, "Wartet", 1)
    done = column(b.id, "Erledigt", 2, is_done=True)
    moving = [card(b, col, rank="a"), card(b, col, rank="b", completed_at=svc_mod._now())]
    present = card(b, done, rank="m")
    session = ScriptedSession(
        execute=[[]], scalars=[moving, [present], [first, done], [], [first, done]]
    )
    session.put(b, first, col, done)
    service = _svc(session)
    _stub(service)
    stamp = moving[1].completed_at
    await service.delete_column(b.id, col.id, USER, move_to=done.id)
    assert all(m.column_id == done.id for m in moving)
    assert present.rank < moving[0].rank < moving[1].rank
    assert moving[0].completed_at is not None and moving[1].completed_at == stamp
    assert session.deleted == [col]
    assert (first.position, done.position) == (0, 1)
    # An empty column into a column without cards and not done.
    empty = column(b.id, "Leer", 3)
    session.put(empty)
    session.scalars_q[:] = [[], [first, done]]
    await service.delete_column(b.id, empty.id, USER)
    assert session.deleted[-1] is empty


async def test_delete_column_into_an_open_column() -> None:
    b = board()
    col, target = column(b.id, "A", 0), column(b.id, "B", 1)
    moving = card(b, col)
    session = ScriptedSession(scalars=[[moving], [], [target]])
    session.put(b, col, target)
    service = _svc(session)
    _stub(service)
    await service.delete_column(b.id, col.id, USER, move_to=target.id)
    assert moving.column_id == target.id and moving.completed_at is None
    assert moving.rank == "i"


# -- labels -------------------------------------------------------------------------


async def test_add_label() -> None:
    b = board()
    session = ScriptedSession(scalar=[uuid.uuid4(), None])
    session.put(b)
    service = _svc(session)
    with pytest.raises(ConflictError) as exc:
        await service.add_label(b.id, LabelCreate(name="Wichtig", color="red"), USER)
    assert exc.value.code == "label_exists"
    out = await service.add_label(b.id, LabelCreate(name=" Neu ", color="blue"), USER)
    assert (out.name, out.color) == ("Neu", "blue")
    assert any(isinstance(o, TodoLabel) for o in session.added)


async def test_patch_and_delete_label() -> None:
    b = board()
    lab = label(b.id)
    foreign = label(uuid.uuid4())
    session = ScriptedSession(scalar=[uuid.uuid4(), None])
    session.put(b, lab, foreign)
    service = _svc(session)
    with pytest.raises(NotFoundError):
        await service.patch_label(b.id, foreign.id, LabelPatch(color="red"), USER)
    with pytest.raises(NotFoundError):
        await service.delete_label(b.id, uuid.uuid4(), USER)
    with pytest.raises(ConflictError):
        await service.patch_label(b.id, lab.id, LabelPatch(name="Andere"), USER)
    out = await service.patch_label(b.id, lab.id, LabelPatch(name=" Eilig ", color="green"), USER)
    assert (out.name, out.color) == ("Eilig", "green")
    out = await service.patch_label(b.id, lab.id, LabelPatch(), USER)
    assert out.name == "Eilig"
    assert "!=" in str(session.statements[-1])
    await service.delete_label(b.id, lab.id, USER)
    assert session.deleted == [lab]
