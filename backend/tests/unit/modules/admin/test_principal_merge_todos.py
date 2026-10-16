"""Account merge, the to-do area: mentions, assignments and the personal board."""

from __future__ import annotations

import uuid
from typing import Any, get_args

import pytest

from app.modules.admin import principal_merge as merge_mod
from app.modules.admin.principal_merge import AREAS, PrincipalMergeService, _Tally
from app.modules.admin.schemas import MergeArea
from tests.unit.modules.todos.fakes import Rows, ScriptedSession

OLD = uuid.UUID(int=1)
NEW = uuid.UUID(int=2)
SRC_BOARD = uuid.UUID(int=101)
DST_BOARD = uuid.UUID(int=102)


class _Row:
    def __init__(self, pid: uuid.UUID) -> None:
        self.id = pid


def test_the_merge_lists_the_todo_columns() -> None:
    assert "todos" in AREAS and "todos" in get_args(MergeArea)
    columns = {str(col) for area, col in merge_mod.ID_COLUMNS if area == "todos"}
    assert columns == {
        "TodoCard.created_by",
        "TodoComment.author_id",
        "TodoEvent.actor_id",
        "TodoLink.created_by",
    }
    assert "TodoAssignee.principal_id" in {str(c) for c in merge_mod.COMBINED_COLUMNS}
    assert "todo_board.owner_id" in merge_mod.EXCLUDED_COLUMNS


@pytest.fixture
def mentions(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []

    async def _rewrite(_s: Any, old: uuid.UUID, new: uuid.UUID, *, apply: bool) -> int:
        assert (old, new) == (OLD, NEW)
        calls.append(apply)
        return 2

    monkeypatch.setattr(merge_mod, "rewrite_mentions", _rewrite)
    return calls


async def _run(session: ScriptedSession, *, apply: bool) -> dict[str, int]:
    tally = _Tally()
    service = PrincipalMergeService(session)  # type: ignore[arg-type]
    await service._todos(_Row(OLD), _Row(NEW), tally, apply=apply)  # type: ignore[arg-type]
    return vars(tally.by_area["todos"])


async def test_without_a_personal_board_only_the_mentions_move(mentions: list[bool]) -> None:
    out = await _run(ScriptedSession(execute=[[(DST_BOARD, NEW)]]), apply=True)
    assert out == {"rewritten": 2, "combined": 0, "removed": 0}
    assert mentions == [True]


async def test_the_board_changes_its_owner(mentions: list[bool]) -> None:
    preview = ScriptedSession(execute=[[(SRC_BOARD, OLD)]])
    assert (await _run(preview, apply=False))["rewritten"] == 3
    assert len(preview.statements) == 1
    session = ScriptedSession(execute=[[(SRC_BOARD, OLD)], Rows(rowcount=1)])
    assert (await _run(session, apply=True))["rewritten"] == 3
    assert str(session.statements[-1]).startswith("UPDATE todo_board SET owner_id")


async def test_two_boards_fold_into_the_target(
    mentions: list[bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    folded: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def _fold(_s: Any, source: uuid.UUID, target: uuid.UUID) -> int:
        folded.append((source, target))
        return 4

    monkeypatch.setattr(merge_mod, "fold_personal_board", _fold)
    both = [(SRC_BOARD, OLD), (DST_BOARD, NEW)]
    preview = ScriptedSession(execute=[both], scalar=[5])
    assert await _run(preview, apply=False) == {"rewritten": 7, "combined": 1, "removed": 0}
    session = ScriptedSession(execute=[both])
    assert await _run(session, apply=True) == {"rewritten": 6, "combined": 1, "removed": 0}
    assert folded == [(SRC_BOARD, DST_BOARD)]
