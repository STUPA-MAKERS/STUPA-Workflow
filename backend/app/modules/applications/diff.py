"""Pure field-diff computation for application versions — no DB/HTTP.

:func:`compute_diff` compares two ``data`` snapshots and returns
``{"added": {key: new}, "removed": {key: old}, "changed": {key: {"old", "new"}}}``.
Nested fields (objects, ``table`` row lists) are compared by value as a whole —
no recursive cell diff; robust against heterogeneous structures.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict


class FieldChange(TypedDict):
    old: Any
    new: Any


class DataDiff(TypedDict):
    added: dict[str, Any]
    removed: dict[str, Any]
    changed: dict[str, FieldChange]


def compute_diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> DataDiff:
    """Compute a structured diff of two field-value maps.

    ``added``: keys only in ``new``; ``removed``: keys only in ``old``;
    ``changed``: keys in both with unequal values.
    """
    added: dict[str, Any] = {k: new[k] for k in new.keys() - old.keys()}
    removed: dict[str, Any] = {k: old[k] for k in old.keys() - new.keys()}
    changed: dict[str, FieldChange] = {
        k: {"old": old[k], "new": new[k]}
        for k in old.keys() & new.keys()
        if old[k] != new[k]
    }
    return {"added": added, "removed": removed, "changed": changed}


def is_empty_diff(diff: DataDiff) -> bool:
    """Return ``True`` if the diff contains no change (no new version needed)."""
    return not (diff["added"] or diff["removed"] or diff["changed"])
