"""The fixed ids of the positions of a Kostenaufstellung (F/finance/orders/002932).

Each position has an ``id``. A Bestellung names a position by this id, because a reference
by the place in the list points to a different position after an edit.

The functions are pure. The key of a positions field differs from form to form, so they
find the positions by their shape: an answer that is a list of rows of which one holds
``offers``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any


def position_rows(value: object) -> tuple[Mapping[str, Any], ...]:
    """Return the positions of one answer, or nothing for a different answer."""
    rows = (
        tuple(row for row in value if isinstance(row, Mapping)) if isinstance(value, list) else ()
    )
    return rows if any("offers" in row for row in rows) else ()


def position_ids(data: Mapping[str, object]) -> frozenset[str]:
    """Return the ids of all positions in the data of an Antrag."""
    return frozenset(
        str(row["id"]) for value in data.values() for row in position_rows(value) if row.get("id")
    )


def _new_id() -> str:
    """Draw a new id of a position."""
    return str(uuid.uuid4())


def _kept_id(
    row: Mapping[str, Any], index: int, before: Sequence[Mapping[str, Any]], known: frozenset[str]
) -> str | None:
    """Return the id that the row keeps from the version before, or None.

    A sent id stays only when the version before holds it, so a client cannot invent the
    id of a position. A row without an id takes the id of the row at the same place with
    the same label.
    """
    sent = str(row["id"]) if row.get("id") else None
    if sent is not None and sent in known:
        return sent
    same_place = before[index] if index < len(before) else None
    return (
        str(same_place["id"])
        if sent is None
        and same_place is not None
        and same_place.get("id")
        and same_place.get("label") == row.get("label")
        else None
    )


def _with_ids(
    rows: Sequence[object], before: Sequence[Mapping[str, Any]], new_id: Callable[[], str]
) -> list[object]:
    """Give each position of one field its id; each id at most once in the list."""
    known = frozenset(str(row["id"]) for row in before if row.get("id"))
    kept = tuple(
        _kept_id(row, index, before, known) if isinstance(row, Mapping) else None
        for index, row in enumerate(rows)
    )
    first = {value: index for index, value in reversed(tuple(enumerate(kept))) if value}
    return [
        {**row, "id": value if value and first[value] == index else new_id()}
        if isinstance(row, Mapping)
        else row
        for index, (row, value) in enumerate(zip(rows, kept, strict=True))
    ]


def with_position_ids(
    data: Mapping[str, Any],
    previous: Mapping[str, Any],
    new_id: Callable[[], str] = _new_id,
) -> dict[str, Any]:
    """Return the data with an id at each position.

    ``previous`` is the data of the version before, or empty for a new Antrag. A position
    keeps its id through the versions.
    """
    return {
        key: _with_ids(value, position_rows(previous.get(key)), new_id)
        if position_rows(value)
        else value
        for key, value in data.items()
    }


def without_position_ids(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return the data without the ids of the positions, for the diff of two versions.

    The id is no answer of the applicant, so it must not show as a change.
    """
    return {
        key: [
            {k: v for k, v in row.items() if k != "id"} if isinstance(row, Mapping) else row
            for row in value
        ]
        if position_rows(value)
        else value
        for key, value in data.items()
    }
