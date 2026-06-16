"""Unit: Feld-Diff zweier ``data``-Snapshots (T-12, data-model §1)."""

from __future__ import annotations

from app.modules.applications.diff import compute_diff, is_empty_diff


def test_diff_added_removed_changed() -> None:
    old = {"a": 1, "b": 2, "c": 3}
    new = {"b": 2, "c": 30, "d": 4}
    diff = compute_diff(old, new)
    assert diff["added"] == {"d": 4}
    assert diff["removed"] == {"a": 1}
    assert diff["changed"] == {"c": {"old": 3, "new": 30}}


def test_diff_unchanged_is_empty() -> None:
    data = {"a": 1, "nested": {"x": [1, 2]}}
    diff = compute_diff(data, dict(data))
    assert diff == {"added": {}, "removed": {}, "changed": {}}
    assert is_empty_diff(diff) is True


def test_diff_nested_values_compared_whole() -> None:
    # Tabellen-/Objektfelder werden wertweise als Ganzes verglichen (kein Zell-Diff).
    old = {"rows": [{"k": 1}]}
    new = {"rows": [{"k": 1}, {"k": 2}]}
    diff = compute_diff(old, new)
    assert diff["changed"] == {"rows": {"old": [{"k": 1}], "new": [{"k": 1}, {"k": 2}]}}
    assert is_empty_diff(diff) is False


def test_diff_empty_inputs() -> None:
    assert is_empty_diff(compute_diff({}, {})) is True
