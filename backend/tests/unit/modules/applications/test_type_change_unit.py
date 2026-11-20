"""The pure helpers of the change of the Antragsart (specs 001660, 001661)."""

from __future__ import annotations

from typing import Any

from app.modules.applications.service.type_change import (
    carry_values,
    dropped_fields,
    missing_fields,
    missing_note,
)
from app.shared.config_schemas import FormFieldDef


def _f(key: str, ftype: str = "text", **extra: Any) -> FormFieldDef:
    label = extra.pop("label", {"de": f"DE {key}", "en": f"EN {key}"})
    return FormFieldDef.model_validate({"key": key, "type": ftype, "label": label, **extra})


def test_carry_takes_same_key_same_type_and_valid_value() -> None:
    """§ 001660: key and type must match, and the value must pass the new field."""
    old = [
        _f("a"),
        _f("b", "number"),
        _f("c"),
        _f("d", "select", options=[{"value": "p", "label": {"de": "P"}}]),
    ]
    new = [
        _f("a"),
        _f("b"),
        _f("c", validation={"maxLen": 1}),
        _f("e"),
        _f("d", "computed", compute={"var": "a"}),
    ]
    data = {"a": "x", "b": 2, "c": "lang", "d": "q", "e": "fremd"}
    assert carry_values(old, new, data) == {"a": "x"}


def test_missing_lists_required_and_nested_errors() -> None:
    """§ 001661: required fields without a value and fields with a path error."""
    fields = [
        _f("a", required=True),
        _f("b", required=False),
        _f("rows", "positions", required=True),
    ]
    assert [f.key for f in missing_fields(fields, {"rows": [{}]}, {})] == ["a", "rows"]
    assert missing_fields([_f("a", required=True)], {"a": "x"}, {}) == ()


def test_dropped_lists_old_values_that_do_not_move() -> None:
    """§ 001662: an old value outside the carried set is named, an empty one is not."""
    old = [_f("a"), _f("b"), _f("c"), _f("d"), _f("s", "section")]
    data = {"a": "x", "b": "", "c": [], "d": 0, "s": "y"}
    assert [f.key for f in dropped_fields(old, data, {"a": "x"})] == ["d"]


def test_missing_note_language_and_extra_text() -> None:
    """§ 001661: the note names the fields in the language of the application."""
    fields = [_f("a"), _f("b", label={"fr": "Bé"}), _f("c", label={})]
    de = missing_note(fields, None, None)
    assert de == "Nach dem Wechsel der Antragsart fehlen diese Pflichtangaben: DE a, Bé, c."
    en = missing_note(fields[:1], "en", "  Please add it.  ")
    assert en.startswith("After the change of the application type")
    assert "EN a" in en
    assert en.endswith("\n\nPlease add it.")
    assert missing_note(fields[:1], "fr", " ").startswith("Nach dem Wechsel")
