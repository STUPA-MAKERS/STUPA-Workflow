"""Unit tests for the guard rewrite of migration e5b16898d639 (drop deadline policies)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.shared.guards import validate_guard


def _load() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "migrations"
        / "versions"
        / "e5b16898d639_drop_deadline_policies.py"
    )
    spec = importlib.util.spec_from_file_location("mig_drop_deadlines", path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIG = _load()
FIELD = {"hasField": "amount"}
ROLE = {"roleIs": "admin"}


@pytest.mark.parametrize(
    ("guard", "expected", "manual"),
    [
        # Leaves alone: both polarities fold to always-true (NULL).
        ({"deadlinePassed": True}, None, True),
        ({"deadlinePassed": False}, None, False),
        ({"not": {"deadlinePassed": True}}, None, False),
        ({"not": {"deadlinePassed": False}}, None, True),
        ({"not": {"not": {"deadlinePassed": True}}}, None, True),
        # `and`: the leaf drops out, a single rest is unwrapped.
        ({"and": [{"deadlinePassed": True}, FIELD]}, FIELD, True),
        ({"and": [{"deadlinePassed": False}, FIELD, ROLE]}, {"and": [FIELD, ROLE]}, False),
        # `or`: a satisfied leaf makes the whole `or` true.
        ({"or": [{"deadlinePassed": True}, FIELD]}, None, True),
        ({"or": [{"deadlinePassed": False}, FIELD]}, None, False),
        # Under `not`, the polarity flips and `and`/`or` fold accordingly.
        ({"not": {"and": [{"deadlinePassed": True}, FIELD]}}, None, False),
        ({"not": {"and": [{"deadlinePassed": False}, FIELD]}}, None, True),
        ({"not": {"or": [{"deadlinePassed": False}, FIELD]}}, {"not": FIELD}, True),
        ({"not": {"or": [{"deadlinePassed": True}, FIELD]}}, {"not": FIELD}, False),
        # Nested mix.
        (
            {"and": [ROLE, {"or": [FIELD, {"not": {"deadlinePassed": True}}]}]},
            ROLE,
            False,
        ),
        (
            {"and": [ROLE, {"not": {"or": [FIELD, {"deadlinePassed": True}]}}]},
            {"and": [ROLE, {"not": FIELD}]},
            False,
        ),
        # A single non-list child is accepted like the evaluator does.
        ({"and": {"deadlinePassed": True}}, None, True),
    ],
)
def test_rewrite_guard(guard: dict[str, Any], expected: Any, manual: bool) -> None:  # noqa: ANN401
    new_guard, requires_passed = MIG.rewrite_guard(guard)
    assert new_guard == expected
    assert requires_passed is manual
    validate_guard(new_guard)


@pytest.mark.parametrize("guard", [None, {}, FIELD, {"and": [FIELD, {"not": ROLE}]}])
def test_guard_without_operator_is_unchanged(guard: Any) -> None:  # noqa: ANN401
    assert MIG.rewrite_guard(guard) == (guard, False)


def test_rewrite_transition_sets_manual() -> None:
    passed = {"from": "a", "to": "b", "automatic": True, "guard": {"deadlinePassed": True}}
    before = {"from": "a", "to": "c", "automatic": True, "guard": {"deadlinePassed": False}}
    plain = {"from": "a", "to": "d", "automatic": True, "guard": FIELD}

    assert MIG.rewrite_transition(passed) == {**passed, "guard": None, "automatic": False}
    assert MIG.rewrite_transition(before) == {**before, "guard": None}
    assert MIG.rewrite_transition(plain) == plain


def test_rewrite_flow_snapshot() -> None:
    snapshot = {
        "states": [
            {"key": "a", "config": {"deadlinePolicyKey": "p", "other": 1}},
            {"key": "b", "config": {}},
            {"key": "c"},
        ],
        "transitions": [
            {"from": "a", "to": "b", "automatic": True, "guard": {"deadlinePassed": True}},
        ],
        "layout": {"x": 1},
    }
    out = MIG.rewrite_flow_snapshot(snapshot)
    assert out["states"] == [
        {"key": "a", "config": {"other": 1}},
        {"key": "b", "config": {}},
        {"key": "c"},
    ]
    assert out["transitions"] == [
        {"from": "a", "to": "b", "automatic": False, "guard": None},
    ]
    assert out["layout"] == {"x": 1}
