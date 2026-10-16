"""The to-do part of the erasure, the Auskunft and the account merge."""

from __future__ import annotations

from datetime import date

from app.modules.todos.merge import fold_personal_board, rewrite_mentions
from app.modules.todos.privacy import erase_todos, todo_export
from tests.unit.modules.todos.fakes import (
    ME,
    NOW,
    OTHER,
    Rows,
    ScriptedSession,
    board,
    card,
    column,
    comment,
    label,
)


async def test_erase_todos_drops_the_assignments_and_the_personal_board() -> None:
    session = ScriptedSession()
    await erase_todos(session, ME)  # type: ignore[arg-type]
    first, second = (str(s) for s in session.statements)
    assert first.startswith("DELETE FROM todo_assignee")
    assert second.startswith("DELETE FROM todo_board") and "kind" in second


async def test_todo_export() -> None:
    assert await todo_export(ScriptedSession(), []) == {"cards": [], "comments": []}  # type: ignore[arg-type]
    b = board(name="StuPa")
    col = column(b.id, "Offen")
    due = card(b, col, title="A", due_date=date(2026, 11, 1))
    plain = card(b, col, title="B")
    note = comment(due.id, ME, body="Hi", deleted_at=NOW)
    session = ScriptedSession(
        execute=[[(due, "StuPa", "Offen"), (plain, "StuPa", "Offen")], [(note, "A")]]
    )
    out = await todo_export(session, [ME])  # type: ignore[arg-type]
    assert out["cards"][0] == {
        "board": "StuPa",
        "title": "A",
        "column": "Offen",
        "dueDate": date(2026, 11, 1),
        "createdAt": NOW,
    }
    assert out["cards"][1]["dueDate"] is None
    assert out["comments"] == [{"card": "A", "body": "Hi", "createdAt": NOW, "deletedAt": NOW}]


async def test_rewrite_mentions_counts_or_applies() -> None:
    preview = ScriptedSession(scalar=[3])
    assert await rewrite_mentions(preview, ME, OTHER, apply=False) == 3  # type: ignore[arg-type]
    none = ScriptedSession(scalar=[None])
    assert await rewrite_mentions(none, ME, OTHER, apply=False) == 0  # type: ignore[arg-type]
    apply = ScriptedSession(execute=[Rows(rowcount=2)])
    assert await rewrite_mentions(apply, ME, OTHER, apply=True) == 2  # type: ignore[arg-type]
    assert "jsonb_array_elements_text" in str(apply.statements[0])


async def test_fold_personal_board_moves_cards_and_labels() -> None:
    source, target = board(kind="personal"), board(kind="personal")
    first = column(target.id, "Offen", 0)
    done = column(target.id, "Erledigt", 3, is_done=True)
    same_t = label(target.id, "Wichtig")
    same_s = label(source.id, "wichtig")
    moved_label = label(source.id, "Neu")
    open_card = card(source, column(source.id), rank="b")
    done_card = card(source, column(source.id, is_done=True), rank="c")
    session = ScriptedSession(
        scalars=[[done, first][::-1], [same_t], [same_s, moved_label]],
        execute=[[], [(open_card, False), (done_card, True)]],
        scalar=["m", None],
    )
    assert await fold_personal_board(session, source.id, target.id) == 2  # type: ignore[arg-type]
    assert moved_label.board_id == target.id
    assert session.deleted == [same_s]
    assert (open_card.board_id, open_card.column_id) == (target.id, first.id)
    assert open_card.rank > "m"
    assert (done_card.column_id, done_card.rank) == (done.id, "i")
    sql = [str(s) for s in session.statements]
    assert any(s.startswith("UPDATE todo_card_label") for s in sql)
    assert sql[-1].startswith("DELETE FROM todo_board")
    assert sql[-2].startswith("UPDATE todo_board")
