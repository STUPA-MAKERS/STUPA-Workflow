"""Unit tests for `scripts/build_uml.py`: the UML data in `specs/uml/`."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from sqlalchemy import CheckConstraint, Column, MetaData, Table, Text

import app.models  # noqa: F401  — populates Base.metadata
from app.db import Base

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "build_uml.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_uml", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


uml = _load()


def test_views_are_written_with_the_same_bytes() -> None:
    """§S/specs/uml/000680: two runs give the same bytes."""
    for name, build in uml.BUILDERS.items():
        assert uml._dump(build()) == uml._dump(build()), name


def test_committed_views_are_current() -> None:
    """§S/specs/uml/000680: the files in specs/uml are what the script writes now."""
    assert uml.run(write=False) == []


def test_component_view_has_the_layer_of_each_module() -> None:
    """§S/specs/uml/000681: each module of the import contract has its layer."""
    view = uml.components()
    layer_of = {e["id"]: e["layer"] for e in view["elements"]}
    for module, layer in uml.layers().items():
        assert layer_of[module] == layer
    assert layer_of["shared"] == uml.SHARED_LAYER
    assert all(edge["count"] >= 1 for edge in view["edges"])
    assert all(layer_of[e["from"]] <= layer_of[e["to"]] for e in view["edges"])


def test_class_view_has_each_table_and_foreign_key() -> None:
    """§S/specs/uml/000682: one element per table, one edge per foreign key."""
    view = uml.classes()
    assert {e["table"] for e in view["elements"]} == set(Base.metadata.tables)
    foreign_keys = sum(len(t.foreign_keys) for t in Base.metadata.tables.values())
    assert len(view["edges"]) == foreign_keys
    meeting = next(e for e in view["elements"] if e["table"] == "meeting")
    status = next(a for a in meeting["attributes"] if a["name"] == "status")
    assert status["values"] == ["planned", "live", "closed"]


def test_deployment_view_has_each_service() -> None:
    """§S/specs/uml/000683: one element per compose service, no environment."""
    view = uml.deployment()
    ids = {e["id"] for e in view["elements"]}
    assert {"api", "worker", "postgres", "web"} <= ids
    assert all("environment" not in e for e in view["elements"])
    assert {"from": "api", "to": "postgres"} in view["edges"]


def test_check_values_reads_an_in_list() -> None:
    """§S/specs/uml/000682: the values of `<column> IN (...)` are read in order."""
    table = Table(
        "t",
        MetaData(),
        Column("status", Text),
        CheckConstraint("status IN ('a', 'b')", name="status"),
    )
    assert uml.check_values(table) == {"status": ["a", "b"]}


def test_state_view_must_have_the_values_of_its_check_constraint() -> None:
    """§S/specs/uml/000684: missing states and a second initial state fail."""
    view = {
        "view": "state",
        "title": "T",
        "table": "t",
        "column": "status",
        "elements": [
            {"id": "a", "name": "a", "path": "scripts", "initial": True},
            {"id": "b", "name": "b", "path": "scripts", "initial": True},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }
    errors = uml.check_state("specs/uml/states/t-status.json", view, {"t": {"status": ["a", "c"]}})
    assert any("initial" in e for e in errors)
    assert any("'trigger'" in e for e in errors)
    assert any("check constraint" in e for e in errors)


def test_format_finds_unknown_edge_ends_and_double_ids() -> None:
    """§S/specs/uml/000679: an edge to no element and a double ID fail."""
    view = {
        "view": "x",
        "title": "X",
        "elements": [
            {"id": "a", "name": "a", "path": "scripts"},
            {"id": "a", "name": "a", "path": "scripts"},
        ],
        "edges": [{"from": "a", "to": "z"}],
    }
    errors = uml.check_format("specs/uml/x.json", view)
    assert any("not unique" in e for e in errors)
    assert any("'z'" in e for e in errors)
