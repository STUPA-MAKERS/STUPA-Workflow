"""Lexorank placement of cards: the target column, the slot, the rank and the respread."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from itertools import accumulate

from app.modules.todos.lexorank import MAX_LENGTH, RankError, between, spread
from app.modules.todos.models import TodoBoard, TodoCard, TodoColumn
from app.modules.todos.service.common import _invalid, _now
from app.shared.errors import ConflictError, ForbiddenError


def _check_transfer_kinds(source: TodoBoard, target: TodoBoard) -> None:
    """Refuse a transfer from a shared board into a personal board (403).

    Raises:
        ForbiddenError: ``transfer_to_personal``.
    """
    if source.kind != "personal" and target.kind == "personal":
        raise ForbiddenError(
            "A card of a shared board cannot move into a personal board.",
            code="transfer_to_personal",
        )


def _pick_column(columns: Sequence[TodoColumn], column_id: uuid.UUID | None) -> TodoColumn:
    """Return the column ``column_id`` of a board, or its first column for ``None``.

    Raises:
        ValidationProblem: The column is not on the board (HTTP 422, ``column_not_on_board``).
    """
    if column_id is None:
        return columns[0]
    found = next((c for c in columns if c.id == column_id), None)
    if found is None:
        raise _invalid("The column is not on this board.", "column_not_on_board", "columnId")
    return found


def _card_moved() -> ConflictError:
    return ConflictError("The card was moved in the meantime.", code="card_moved")


def _rank(low: str | None, high: str | None) -> str:
    """Return ``between(low, high)``, or raise RankError for a rank above ``MAX_LENGTH``."""
    rank = between(low, high)
    if len(rank) > MAX_LENGTH:
        raise RankError(f"rank longer than {MAX_LENGTH}")
    return rank


def _respread(ordered: Sequence[TodoCard]) -> None:
    """Give the cards a fresh order with ``spread``, in the order given."""
    now = _now()
    for card, rank in zip(ordered, spread(len(ordered)), strict=True):
        card.rank = rank
        card.updated_at = now


def _append(live: Sequence[TodoCard], cards: Sequence[TodoCard]) -> None:
    """Rank ``cards`` after the live cards ``live`` of a column, in the order given.

    A rank above ``MAX_LENGTH`` or a broken rank gives the live cards and ``cards``
    a fresh order. The caller holds the board lock, so no parallel write ranks the
    column at the same time.
    """
    try:
        ranks = _ranks_after(live[-1].rank if live else None, len(cards))
    except RankError:
        _respread([*live, *cards])
        return
    for card, rank in zip(cards, ranks, strict=True):
        card.rank = rank


def _ranks_after(last: str | None, count: int) -> tuple[str, ...]:
    """Return ``count`` ascending ranks after ``last`` (``None``: an empty column).

    Raises:
        RankError: A rank is broken or a new rank is longer than ``MAX_LENGTH``.
    """
    if count == 0:
        return ()
    first = _rank(last, None)
    return tuple(accumulate(range(count - 1), lambda rank, _: _rank(rank, None), initial=first))


def _place(live: Sequence[TodoCard], index: int, card: TodoCard) -> bool:
    """Rank ``card`` at ``index`` among the live cards ``live`` of a column.

    Two cards that share a rank, a broken rank or a new rank above ``MAX_LENGTH``
    give the column a fresh order. The
    caller holds the board lock, so no parallel write ranks the column at the same time.

    Returns:
        True when the column got a fresh order. The caller then pings the whole
        board, because the other cards of the column changed too.
    """
    low = live[index - 1].rank if index > 0 else None
    high = live[index].rank if index < len(live) else None
    try:
        card.rank = _rank(low, high)
    except RankError:
        _respread([*live[:index], card, *live[index:]])
        return True
    return False


def _slot(
    siblings: Sequence[TodoCard], after_id: uuid.UUID | None, before_id: uuid.UUID | None
) -> int:
    """Return the index in ``siblings`` where the moved card goes.

    Raises:
        ValidationProblem: A neighbor is not in the column, or the two neighbors are
            not adjacent (HTTP 422, ``rank_neighbors_invalid``).
    """
    index = {c.id: i for i, c in enumerate(siblings)}

    def at(card_id: uuid.UUID, name: str) -> int:
        if card_id not in index:
            raise _invalid("The neighbor is not in this column.", "rank_neighbors_invalid", name)
        return index[card_id]

    if after_id is not None and before_id is not None:
        above, below = at(after_id, "afterId"), at(before_id, "beforeId")
        if below != above + 1:
            raise _invalid("The neighbors are not adjacent.", "rank_neighbors_invalid", "beforeId")
        return below
    if before_id is not None:
        return at(before_id, "beforeId")
    if after_id is not None:
        return at(after_id, "afterId") + 1
    return len(siblings)
