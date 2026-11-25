"""Pure field-diff computation for application versions. No DB and no HTTP.

`compute_diff` compares two ``data`` snapshots. It returns
``{"added": {key: new}, "removed": {key: old}, "changed": {key: {"old", "new"}}}``.

The code compares a nested field as a whole value. This covers an object and a
``table`` row list. There is no recursive cell diff. Mixed structures therefore
stay safe to compare.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict

from app.modules.applications.position_ids import without_position_ids


class FieldChange(TypedDict):
    """The old and the new value of one changed field."""

    old: Any
    new: Any


class DataDiff(TypedDict):
    """The added, removed and changed fields between two versions of ``data``."""

    added: dict[str, Any]
    removed: dict[str, Any]
    changed: dict[str, FieldChange]


def compute_diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> DataDiff:
    """Compute a structured diff of two field-value maps.

    Returns:
        ``added`` holds the keys only in ``new``. ``removed`` holds the keys
        only in ``old``. ``changed`` holds the keys in both maps whose values
        differ. The ids of the positions of a Kostenaufstellung are left out, because
        an id is no answer of the applicant (F/finance/orders/002932).
    """
    old, new = without_position_ids(old), without_position_ids(new)
    added: dict[str, Any] = {k: new[k] for k in new.keys() - old.keys()}
    removed: dict[str, Any] = {k: old[k] for k in old.keys() - new.keys()}
    changed: dict[str, FieldChange] = {
        k: {"old": old[k], "new": new[k]} for k in old.keys() & new.keys() if old[k] != new[k]
    }
    return {"added": added, "removed": removed, "changed": changed}


def is_empty_diff(diff: DataDiff) -> bool:
    """Return ``True`` when the diff holds no change, so no new version is needed."""
    return not (diff["added"] or diff["removed"] or diff["changed"])
