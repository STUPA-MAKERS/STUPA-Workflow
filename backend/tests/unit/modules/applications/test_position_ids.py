"""The fixed ids of the positions of a Kostenaufstellung (§ F/finance/orders/002932)."""

from __future__ import annotations

import importlib.util
from itertools import count
from pathlib import Path
from types import ModuleType
from typing import Any

from app.modules.applications.diff import compute_diff, is_empty_diff
from app.modules.applications.position_ids import (
    position_ids,
    position_rows,
    with_position_ids,
    without_position_ids,
)


def _ids() -> Any:
    numbers = count(1)
    return lambda: f"new-{next(numbers)}"


def _pos(label: str, **extra: object) -> dict[str, object]:
    return {"label": label, "offers": [{"label": "A", "value": 1, "preferred": True}], **extra}


def test_positions_are_found_by_their_shape() -> None:
    assert position_rows([_pos("Regal"), "x"]) == (_pos("Regal"),)
    assert position_rows([{"id": "zeile"}]) == ()
    assert position_rows("text") == ()
    assert position_ids({"k": [_pos("Regal", id="p1"), _pos("Tisch")], "n": 3}) == {"p1"}


def test_a_new_antrag_gets_an_id_for_each_position() -> None:
    data = {"title": "x", "kosten": [_pos("Regal"), _pos("Tisch", id="invented"), "kaputt"]}
    out = with_position_ids(data, {}, _ids())
    assert [row["id"] for row in out["kosten"][:2]] == ["new-1", "new-2"]
    assert out["kosten"][2] == "kaputt"
    assert out["title"] == "x"


def test_a_position_keeps_its_id_through_an_edit() -> None:
    before = {"kosten": [_pos("Regal", id="p1"), _pos("Tisch", id="p2")]}
    moved = {"kosten": [_pos("Tisch", id="p2"), _pos("Regal", id="p1"), _pos("Stuhl")]}
    out = with_position_ids(moved, before, _ids())
    assert [row["id"] for row in out["kosten"]] == ["p2", "p1", "new-1"]


def test_a_position_without_an_id_takes_the_id_of_its_place() -> None:
    before = {"kosten": [_pos("Regal", id="p1"), _pos("Tisch", id="p2")]}
    sent = {"kosten": [_pos("Regal"), _pos("Stuhl"), _pos("Lampe")]}
    out = with_position_ids(sent, before, _ids())
    assert [row["id"] for row in out["kosten"]] == ["p1", "new-1", "new-2"]


def test_an_id_stands_once_in_a_list() -> None:
    before = {"kosten": [_pos("Regal", id="p1")]}
    sent = {"kosten": [_pos("Regal", id="p1"), _pos("Kopie", id="p1")]}
    out = with_position_ids(sent, before, _ids())
    assert [row["id"] for row in out["kosten"]] == ["p1", "new-1"]


def test_the_id_is_no_change_of_a_version() -> None:
    old = {"kosten": [_pos("Regal")], "title": "x"}
    new = with_position_ids(old, {}, _ids())
    assert without_position_ids(new) == old
    assert is_empty_diff(compute_diff(old, new))
    changed = compute_diff(old, {"kosten": [_pos("Tisch", id="p1")], "title": "x"})
    assert changed["changed"]["kosten"]["new"] == [_pos("Tisch")]


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "e7d870f703d5_position_ids.py"
    )
    spec = importlib.util.spec_from_file_location("mig_position_ids", path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_migration_gives_the_same_position_the_same_id() -> None:
    fill = _migration().fill_position_ids
    first = fill({"kosten": [_pos("Regal"), _pos("Tisch")], "title": "x"}, {})
    ids = [row["id"] for row in first["kosten"]]
    assert len(set(ids)) == 2
    second = fill({"kosten": [_pos("Regal"), _pos("Stuhl"), "kaputt"]}, first)
    assert second["kosten"][0]["id"] == ids[0]
    assert second["kosten"][1]["id"] not in ids
    assert second["kosten"][2] == "kaputt"
    assert fill(second, first) == second
    twice = fill({"kosten": [_pos("Regal", id=ids[0]), _pos("Regal")]}, first)
    assert twice["kosten"][1]["id"] != ids[0]
