"""Pure rules of a status list (F/administration/admin/003035-003038).

Every function takes plain values and returns plain values. The service reads the
database and calls them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.modules.statuses.models import STATUS_PHASES

#: The shape of a key: lower case, starts with a letter, at most 40 characters.
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


@dataclass(frozen=True, slots=True)
class StatusItem:
    """One status of a list as the admin sends it."""

    key: str
    phase: str
    start: bool
    sets_date: str | None = None


def _error(field: str, msg: str) -> dict[str, str]:
    return {"field": field, "msg": msg}


def _start_errors(items: Sequence[StatusItem]) -> tuple[dict[str, str], ...]:
    """Return the error of the start status: exactly one, in the phase ``open``."""
    starts = [item for item in items if item.start]
    if len(starts) != 1:
        return (_error("statuses", "exactly one status must be the start"),)
    if starts[0].phase != "open":
        return (_error("statuses", "the start status must have the phase open"),)
    return ()


def list_errors(kind: str, items: Sequence[StatusItem]) -> list[dict[str, str]]:
    """Return the errors of a status list, empty for a valid list.

    A key is unique and has the shape of `KEY_PATTERN`. Exactly one status is the start
    status, and its phase is ``open``. Each phase has at least one status. Only a status
    of the Bestellungen sets a date.
    """
    keys = [item.key for item in items]
    shape = [
        _error("statuses", f"key {key!r} has a wrong shape")
        for key in keys
        if not KEY_PATTERN.match(key)
    ]
    twice = (
        [_error("statuses", "a key is twice in the list")] if len(set(keys)) != len(keys) else []
    )
    phases = [
        _error("statuses", f"no status has the phase {phase}")
        for phase in STATUS_PHASES
        if not any(item.phase == phase for item in items)
    ]
    dates = (
        [_error("statuses", "only a status of an order sets a date")]
        if kind != "order" and any(item.sets_date for item in items)
        else []
    )
    return [*shape, *twice, *_start_errors(items), *phases, *dates]


def replacement_errors(
    removed: Iterable[str], replacements: Mapping[str, str], keys: Iterable[str]
) -> list[dict[str, str]]:
    """Return the errors of the replacements of the removed keys.

    A replacement names a removed key and a key that stays in the list.
    """
    removed_set = frozenset(removed)
    kept = frozenset(keys)
    return [
        _error("replacements", f"{old!r} is not removed")
        if old not in removed_set
        else _error("replacements", f"{new!r} is not in the list")
        for old, new in replacements.items()
        if old not in removed_set or new not in kept
    ]
