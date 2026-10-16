"""The to-do part of the erasure, the Auskunft and the account merge."""

from __future__ import annotations

import uuid
from datetime import date

from app.modules.todos.merge import fold_personal_board, rewrite_mentions
from app.modules.todos.privacy import erase_todos, todo_export
from tests.unit.modules.todos.fakes import (
    ME,
    NOW,
    OTHER,
    FakeFiles,
    Rows,
    ScriptedSession,
    board,
    card,
    column,
    comment,
    label,
)


async def test_erase_todos_drops_the_assignments_and_the_personal_board() -> None:
    comment_id = uuid.uuid4()
    session = ScriptedSession(scalars=[[comment_id]])
    files = FakeFiles()
    await erase_todos(session, ME, files=files, actor="admin")  # type: ignore[arg-type]
    board_lock, card_lock, lookup, first, second = (str(s) for s in session.statements)
    # The board and its cards are locked, in id order, before the comment ids are read.
    assert board_lock.startswith("SELECT todo_board.id") and "todo_board.kind" in board_lock
    assert "ORDER BY todo_board.id" in board_lock and board_lock.endswith("FOR UPDATE")
    assert card_lock.startswith("SELECT todo_card.id") and "todo_board.owner_id" in card_lock
    assert "ORDER BY todo_card.id" in card_lock and card_lock.endswith("FOR UPDATE")
    assert "todo_comment.id" in lookup and "todo_board.owner_id" in lookup
    assert files.removed == [([comment_id], "admin")]
    assert first.startswith("DELETE FROM todo_assignee")
    assert second.startswith("DELETE FROM todo_board") and "kind" in second


async def test_erase_todos_builds_its_own_files_service() -> None:
    session = ScriptedSession(scalars=[[]])
    await erase_todos(session, ME)  # type: ignore[arg-type]
    assert len(session.statements) == 5


async def test_todo_export() -> None:
    assert await todo_export(ScriptedSession(), []) == {"cards": [], "comments": []}  # type: ignore[arg-type]
    b = board(name="StuPa")
    col = column(b.id, "Offen")
    due = card(b, col, title="A", due_date=date(2026, 11, 1), description_md="Raum buchen")
    plain = card(b, col, title="B", description_md="fremd", created_by=OTHER)
    note = comment(due.id, ME, body="Hi", deleted_at=NOW)
    session = ScriptedSession(
        execute=[
            [(due, "StuPa", "Offen"), (plain, "StuPa", "Offen")],
            [(note, "A")],
            [(note.id, "a.pdf"), (note.id, "b.png")],
        ]
    )
    out = await todo_export(session, [ME])  # type: ignore[arg-type]
    assert out["cards"][0] == {
        "board": "StuPa",
        "title": "A",
        "column": "Offen",
        "dueDate": date(2026, 11, 1),
        "createdAt": NOW,
        "description": "Raum buchen",
    }
    assert out["cards"][1]["dueDate"] is None
    assert out["cards"][1]["description"] is None
    assert out["comments"] == [
        {
            "card": "A",
            "body": "Hi",
            "createdAt": NOW,
            "deletedAt": NOW,
            "attachments": ["a.pdf", "b.png"],
        }
    ]
    assert "attachment.todo_comment_id IN" in str(session.statements[2])
    # Without comments no file query runs.
    session = ScriptedSession(execute=[[], []])
    out = await todo_export(session, [ME])  # type: ignore[arg-type]
    assert out["comments"] == []
    assert len(session.statements) == 2


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
