"""TDD: reine Form-Engine T-11 (validate_definition/effective_form/validate_answers).

Akzeptanzkriterien: jeder Feldtyp valid/invalid; required; visibleIf (sichtbar⇒
Pflicht); compute korrekt; unbekannter Typ → Fehler; effective_form-Sektionen;
promoted-Extraktion.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.forms.validation import (
    AnswerValidationError,
    FieldError,
    FormDefinitionError,
    FormSection,
    _validate_value,
    effective_form,
    extract_promoted,
    validate_answers,
    validate_definition,
)
from app.shared.config_schemas import FormFieldDef


def _field(key: str, type: str, **kw: Any) -> FormFieldDef:
    kw.setdefault("label", {"de": key})
    return FormFieldDef.model_validate({"key": key, "type": type, **kw})


def _errkeys(exc: AnswerValidationError) -> set[str]:
    return {e.field for e in exc.errors}


# --------------------------------------------------------------------------- #
# validate_definition
# --------------------------------------------------------------------------- #
def test_validate_definition_ok() -> None:
    validate_definition([_field("title", "text"), _field("amount", "currency")])


def test_validate_definition_duplicate_keys() -> None:
    with pytest.raises(FormDefinitionError, match="duplicate field keys"):
        validate_definition([_field("a", "text"), _field("a", "number")])


def test_validate_definition_promoted_must_be_numeric() -> None:
    with pytest.raises(FormDefinitionError, match="must be numeric"):
        validate_definition(
            [_field("x", "text", isPromoted=True, promoteTarget="amount")]
        )


def test_validate_definition_promoted_numeric_ok() -> None:
    validate_definition(
        [_field("amount", "currency", isPromoted=True, promoteTarget="amount")]
    )


# --------------------------------------------------------------------------- #
# effective_form
# --------------------------------------------------------------------------- #
def test_effective_form_main_only_without_pot() -> None:
    sections = effective_form([_field("title", "text")])
    assert sections == [FormSection(key="main", fields=[_field("title", "text")])]


def test_effective_form_adds_budget_section_with_pot() -> None:
    sections = effective_form([_field("title", "text")], [_field("cost_center", "text")])
    assert [s.key for s in sections] == ["main", "budget"]
    assert sections[1].fields[0].key == "cost_center"


def test_effective_form_empty_pot_no_budget_section() -> None:
    sections = effective_form([_field("title", "text")], [])
    assert [s.key for s in sections] == ["main"]


# --------------------------------------------------------------------------- #
# validate_answers — required + presence
# --------------------------------------------------------------------------- #
def test_required_missing_field_errors() -> None:
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers([_field("title", "text", required=True)], {})
    assert _errkeys(ei.value) == {"title"}
    assert ei.value.errors[0].msg == "required"


def test_required_empty_string_errors() -> None:
    with pytest.raises(AnswerValidationError):
        validate_answers([_field("title", "text", required=True)], {"title": ""})


def test_optional_missing_ok() -> None:
    assert validate_answers([_field("title", "text")], {}) == {}


def test_collects_all_errors() -> None:
    fields = [_field("a", "text", required=True), _field("b", "number", required=True)]
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers(fields, {})
    assert _errkeys(ei.value) == {"a", "b"}


# --------------------------------------------------------------------------- #
# validate_answers — pro Feldtyp valid/invalid
# --------------------------------------------------------------------------- #
def test_text_valid_and_constraints() -> None:
    f = _field("t", "text", validation={"minLen": 2, "maxLen": 4, "pattern": "[a-z]+"})
    assert validate_answers([f], {"t": "abc"}) == {"t": "abc"}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"t": "a"})  # too short
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"t": "abcde"})  # too long
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"t": "AB"})  # pattern (also too short, both error)
    with pytest.raises(AnswerValidationError):
        validate_answers([_field("t", "text")], {"t": 123})  # not a string


def test_number_valid_and_range() -> None:
    f = _field("n", "number", validation={"min": 0, "max": 10})
    assert validate_answers([f], {"n": 5}) == {"n": 5}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"n": -1})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"n": 11})
    with pytest.raises(AnswerValidationError):
        validate_answers([_field("n", "number")], {"n": True})  # bool not number
    with pytest.raises(AnswerValidationError):
        validate_answers([_field("n", "number")], {"n": "x"})  # unparseable


def test_currency_valid() -> None:
    f = _field("c", "currency", validation={"min": 0})
    assert validate_answers([f], {"c": "250.00"}) == {"c": "250.00"}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"c": -5})


def test_date_valid_invalid() -> None:
    f = _field("d", "date")
    assert validate_answers([f], {"d": "2026-06-05"}) == {"d": "2026-06-05"}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"d": "2026-13-40"})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"d": 20260605})


def test_select_valid_invalid() -> None:
    f = _field("s", "select", options=[{"value": "a", "label": {"de": "A"}}])
    assert validate_answers([f], {"s": "a"}) == {"s": "a"}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"s": "z"})


def test_multiselect_valid_invalid() -> None:
    f = _field(
        "m",
        "multiselect",
        options=[{"value": "a", "label": {"de": "A"}}, {"value": "b", "label": {"de": "B"}}],
    )
    assert validate_answers([f], {"m": ["a", "b"]}) == {"m": ["a", "b"]}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"m": ["a", "z"]})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"m": "a"})  # not a list


def test_checkbox_valid_invalid() -> None:
    f = _field("agree", "checkbox")
    assert validate_answers([f], {"agree": True}) == {"agree": True}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"agree": "yes"})


def test_file_valid_invalid() -> None:
    f = _field("doc", "file")
    assert validate_answers([f], {"doc": "att-1"}) == {"doc": "att-1"}
    assert validate_answers([f], {"doc": ["att-1", "att-2"]}) == {"doc": ["att-1", "att-2"]}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"doc": [1, 2]})


def test_table_valid_invalid() -> None:
    f = _field("rows", "table", validation={"maxRows": 2})
    ok = {"rows": [{"item": "a"}, {"item": "b"}]}
    assert validate_answers([f], ok) == ok
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"rows": [{"a": 1}, {"b": 2}, {"c": 3}]})  # > maxRows
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"rows": "nope"})  # not a list
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"rows": ["nope"]})  # row not object


def test_markdown_valid() -> None:
    assert validate_answers([_field("md", "markdown")], {"md": "# hi"}) == {"md": "# hi"}


def test_unknown_type_errors() -> None:
    # FormFieldDef.type ist Literal — unbekannter Typ wird über den internen
    # Dispatcher mit einem Pseudo-Feld geprüft (defensiver else-Zweig).
    errors: list[FieldError] = []
    _validate_value(SimpleNamespace(key="x", type="bogus"), "v", errors)  # type: ignore[arg-type]
    assert errors and "unknown field type" in errors[0].msg


# --------------------------------------------------------------------------- #
# visibleIf — sichtbar ⇒ Pflicht
# --------------------------------------------------------------------------- #
def test_visible_if_hidden_skips_required() -> None:
    f = _field(
        "iban",
        "text",
        required=True,
        visibleIf={"==": [{"var": "has_budget"}, True]},
    )
    # nicht sichtbar (has_budget False) → required nicht erzwungen
    assert validate_answers([f], {}, context={"has_budget": False}) == {}


def test_visible_if_visible_enforces_required() -> None:
    f = _field(
        "iban",
        "text",
        required=True,
        visibleIf={"==": [{"var": "has_budget"}, True]},
    )
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers([f], {}, context={"has_budget": True})
    assert _errkeys(ei.value) == {"iban"}


def test_visible_if_eval_error_is_conservatively_visible() -> None:
    # T-05 and/or ohne Kurzschluss: {">":[var y,0]} wirft bei fehlendem y →
    # konservativ sichtbar ⇒ required greift.
    f = _field(
        "x",
        "text",
        required=True,
        visibleIf={"and": [{"var": "flag"}, {">": [{"var": "y"}, 0]}]},
    )
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {}, context={"flag": False})


# --------------------------------------------------------------------------- #
# compute — abgeleitete Felder
# --------------------------------------------------------------------------- #
def test_compute_derives_value() -> None:
    fields = [
        _field("qty", "number"),
        _field("unit_price", "currency"),
        _field("total", "computed", compute={"*": [{"var": "qty"}, {"var": "unit_price"}]}),
    ]
    out = validate_answers(fields, {"qty": 3, "unit_price": 10})
    assert out["total"] == 30


def test_compute_failure_reports_error() -> None:
    fields = [_field("total", "computed", compute={"/": [{"var": "a"}, {"var": "b"}]})]
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers(fields, {"a": 1, "b": 0})  # division by zero
    assert _errkeys(ei.value) == {"total"}


def test_compute_value_visible_in_visible_if() -> None:
    fields = [
        _field("qty", "number"),
        _field("total", "computed", compute={"+": [{"var": "qty"}, 1]}),
        _field("note", "text", required=True, visibleIf={">": [{"var": "total"}, 5]}),
    ]
    # total = 5 → note hidden, kein Pflichtfehler
    assert "note" not in validate_answers(fields, {"qty": 4})
    # total = 11 → note sichtbar ⇒ Pflicht
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers(fields, {"qty": 10})
    assert _errkeys(ei.value) == {"note"}


# --------------------------------------------------------------------------- #
# extract_promoted
# --------------------------------------------------------------------------- #
def test_extract_promoted_numeric_to_decimal() -> None:
    fields = [_field("amount", "currency", isPromoted=True, promoteTarget="amount")]
    assert extract_promoted(fields, {"amount": "250.00"}) == {"amount": Decimal("250.00")}


def test_extract_promoted_skips_missing_and_non_promoted() -> None:
    fields = [
        _field("amount", "currency", isPromoted=True, promoteTarget="amount"),
        _field("title", "text"),
    ]
    assert extract_promoted(fields, {"title": "x"}) == {}


def test_extract_promoted_non_numeric_passthrough() -> None:
    fields = [_field("ref", "text", isPromoted=True, promoteTarget="ref")]
    assert extract_promoted(fields, {"ref": "abc"}) == {"ref": "abc"}


def test_extract_promoted_unparseable_numeric_skipped() -> None:
    fields = [_field("amount", "number", isPromoted=True, promoteTarget="amount")]
    assert extract_promoted(fields, {"amount": "not-a-number"}) == {}
