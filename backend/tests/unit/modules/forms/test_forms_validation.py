"""Pure form engine (validate_definition, effective_form, validate_answers).

The tests prove: every field type passes and fails as expected. Required fields
apply. A visible visibleIf field becomes mandatory. compute derives the right value.
An unknown type raises an error. effective_form builds the sections. extract_promoted
reads the promoted values.

The ReDoS tests check the input length cap and the wall-clock timeout of a pattern.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.forms.validation import (
    SYSTEM_TITLE_KEY,
    AnswerValidationError,
    FieldError,
    FormDefinitionError,
    FormSection,
    _validate_value,
    effective_form,
    extract_promoted,
    positions_total,
    validate_answers,
    validate_definition,
)
from app.shared.config_schemas import FormFieldDef


def _position(label: str, *offers: tuple[str, float, bool]) -> dict[str, Any]:
    return {
        "label": label,
        "offers": [{"label": lbl, "value": v, "preferred": p} for (lbl, v, p) in offers],
    }


def _field(key: str, type: str, **kw: Any) -> FormFieldDef:
    kw.setdefault("label", {"de": key})
    return FormFieldDef.model_validate({"key": key, "type": type, **kw})


def _errkeys(exc: AnswerValidationError) -> set[str]:
    return {e.field for e in exc.errors}


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


def test_validate_definition_rejects_bad_pattern() -> None:
    """Reject a broken regex at save time, else it causes a 500 at answer time."""
    with pytest.raises(FormDefinitionError, match="invalid validation pattern"):
        validate_definition([_field("t", "text", validation={"pattern": "["})])


def test_validate_definition_rejects_bad_jsonlogic() -> None:
    """Reject broken JsonLogic in the defensive storage gate.

    FormFieldDef validates JsonLogic at build time, so the test bends the field after the
    build.
    """
    f = _field("t", "text")
    f.visible_if = {"system": ["rm", "-rf"]}
    with pytest.raises(FormDefinitionError, match="invalid expression"):
        validate_definition([f])


def test_effective_form_main_only_without_pot() -> None:
    sections = effective_form([_field("title", "text")])
    assert sections == [FormSection(key="main", fields=[_field("title", "text")])]


def test_effective_form_injects_required_system_title_when_absent() -> None:
    sections = effective_form([_field("amount", "currency")])
    main = sections[0].fields
    assert main[0].key == SYSTEM_TITLE_KEY and main[0].required is True
    assert [f.key for f in main] == [SYSTEM_TITLE_KEY, "amount"]


def test_effective_form_does_not_duplicate_existing_title() -> None:
    main = effective_form([_field("title", "text"), _field("amount", "currency")])[0]
    assert [f.key for f in main.fields] == ["title", "amount"]


def test_effective_form_splits_at_section_markers() -> None:
    sections = effective_form(
        [
            _field("title", "text"),
            _field("a", "text"),
            _field("step2", "section", label={"de": "Kosten", "en": "Costs"}),
            _field("b", "currency"),
        ]
    )
    assert [s.key for s in sections] == ["main", "step2"]
    assert [f.key for f in sections[0].fields] == ["title", "a"]
    assert [f.key for f in sections[1].fields] == ["b"]
    assert sections[1].label == {"de": "Kosten", "en": "Costs"}
    assert all(f.type != "section" for s in sections for f in s.fields)


def test_effective_form_leading_section_titles_first_section() -> None:
    """Inject the title field into the intro section when no title field exists."""
    sections = effective_form(
        [
            _field("intro", "section", label={"de": "Start"}),
            _field("a", "text"),
        ]
    )
    assert [s.key for s in sections] == ["intro"]
    assert sections[0].label == {"de": "Start"}
    assert [f.key for f in sections[0].fields] == [SYSTEM_TITLE_KEY, "a"]


def test_validate_answers_ignores_section_markers() -> None:
    """Never require a section marker; it carries no answer value."""
    result = validate_answers(
        [_field("s", "section", label={"de": "X"}), _field("name", "text")],
        {"name": "ok"},
    )
    assert result == {"name": "ok"}


def _positions_field(**kw: Any) -> FormFieldDef:
    return _field("positions", "positions", **kw)


def test_positions_valid() -> None:
    field = _positions_field(validation={"minOffers": 2})
    value = [
        _position("Catering", ("A", 500, True), ("B", 600, False)),
        _position("Technik", ("X", 200, False), ("Y", 150, True)),
    ]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert errors == []


def test_positions_too_few_offers_and_no_preferred() -> None:
    field = _positions_field(validation={"minOffers": 3})
    value = [_position("Catering", ("A", 500, False), ("B", 600, False))]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    msgs = " ".join(e.msg for e in errors)
    assert "at least 3 comparison offer" in msgs
    assert "exactly one offer must be marked preferred" in msgs


def test_positions_default_min_offers_is_three() -> None:
    """Fall back to minOffers 3 without a validation block."""
    field = _positions_field()
    value = [_position("P", ("A", 1, True), ("B", 2, False))]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert any("at least 3 comparison offer" in e.msg for e in errors)


def test_positions_non_positive_value_rejected() -> None:
    field = _positions_field(validation={"minOffers": 1})
    value = [_position("P", ("A", 0, True))]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert any("greater than 0" in e.msg for e in errors)


def test_positions_min_positions() -> None:
    field = _positions_field(validation={"minOffers": 1, "minPositions": 2})
    value = [_position("P", ("A", 5, True))]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert any("at least 2 position" in e.msg for e in errors)


def test_positions_engine_max_positions_ceiling() -> None:
    """Apply a configured maxPositions."""
    field = _positions_field(validation={"minOffers": 1, "maxPositions": 2})
    value = [_position(f"P{i}", ("A", 5, True)) for i in range(3)]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert any("more than 2 position" in e.msg for e in errors)


def test_positions_engine_default_max_positions() -> None:
    """Apply the engine cap without maxPositions."""
    field = _positions_field(validation={"minOffers": 1})
    value = [_position(f"P{i}", ("A", 5, True)) for i in range(201)]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert any("more than 200 position" in e.msg for e in errors)


def test_positions_engine_max_offers_ceiling() -> None:
    field = _positions_field(validation={"minOffers": 1, "maxOffers": 2})
    value = [_position("P", ("A", 5, True), ("B", 6, False), ("C", 7, False))]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert any("more than 2 comparison offer" in e.msg for e in errors)


def test_positions_no_offers_opt_out_with_reason_needs_one_offer() -> None:
    """Accept one offer plus a reason instead of minOffers 3; the opt-out is on by default."""
    field = _positions_field(validation={"minOffers": 3})
    value = [
        _position("Spezialgerät", ("Einziger Anbieter", 500, True))
        | {"noOffers": True, "noOffersReason": "Einziger Anbieter in der Region."}
    ]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert errors == []


def test_positions_no_offers_requires_reason() -> None:
    field = _positions_field(validation={"minOffers": 3})
    value = [_position("P", ("A", 500, True)) | {"noOffers": True, "noOffersReason": "  "}]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert any("needs a reason" in e.msg for e in errors)


def test_positions_no_offers_still_requires_one_offer() -> None:
    field = _positions_field(validation={"minOffers": 3})
    value = [{"label": "P", "offers": [], "noOffers": True, "noOffersReason": "Begründung"}]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert any("at least 1 comparison offer" in e.msg for e in errors)


def test_positions_no_offers_rejected_when_disallowed() -> None:
    field = _positions_field(validation={"minOffers": 3, "allowNoOffers": False})
    value = [
        _position("P", ("A", 500, True)) | {"noOffers": True, "noOffersReason": "Begründung"}
    ]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert any("not allowed" in e.msg for e in errors)


def test_table_default_max_rows_ceiling() -> None:
    """Keep the default cap on the row count without maxRows."""
    f = _field("rows", "table")
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"rows": [{"i": n} for n in range(1001)]})


def test_table_explicit_max_rows_zero_rejects_any_row() -> None:
    """Reject every row at an explicit maxRows=0.

    maxRows=0 is valid (ge=0), so a falsy `or` must not fall back to the default cap of
    1000. An empty table stays valid, because 0 rows is not more than 0.
    """
    f = _field("rows", "table", validation={"maxRows": 0})
    with pytest.raises(AnswerValidationError) as exc:
        validate_answers([f], {"rows": [{"a": 1}, {"b": 2}, {"c": 3}]})
    assert "rows" in _errkeys(exc.value)
    assert validate_answers([f], {"rows": []}) == {"rows": []}


def test_table_configured_max_rows_capped_at_engine_ceiling() -> None:
    """Keep the engine cap when the builder sets a higher value."""
    f = _field("rows", "table", validation={"maxRows": 100000})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"rows": [{"i": n} for n in range(1001)]})


def test_positions_total_sums_preferred() -> None:
    value = [
        _position("Catering", ("A", 500, True), ("B", 600, False)),
        _position("Technik", ("X", 200, False), ("Y", 150, True)),
    ]
    assert positions_total(value) == Decimal("650")
    assert positions_total([]) is None


def test_extract_promoted_positions_feeds_amount() -> None:
    fields = [_positions_field()]
    data = {
        "positions": [
            _position("Catering", ("A", 500, True), ("B", 600, False)),
            _position("Technik", ("X", 200, False), ("Y", 150, True)),
        ]
    }
    assert extract_promoted(fields, data) == {"amount": Decimal("650")}


def _funding_form(**kw: Any) -> list[FormFieldDef]:
    """Build a form with a requested funding, separate from the cost total."""
    return [_positions_field(validation={"minOffers": 1}), _field("foerderung", "funding", **kw)]


def _costs(*values: float) -> list[dict[str, Any]]:
    return [_position(f"P{i}", ("A", v, True)) for i, v in enumerate(values)]


def test_validate_definition_funding_needs_positions() -> None:
    with pytest.raises(FormDefinitionError, match="needs a positions field"):
        validate_definition([_field("foerderung", "funding")])
    validate_definition(_funding_form())


def test_validate_definition_at_most_one_funding_field() -> None:
    fields = [*_funding_form(), _field("foerderung2", "funding")]
    with pytest.raises(FormDefinitionError, match="at most one funding field"):
        validate_definition(fields)


def test_validate_definition_funding_cannot_be_promoted() -> None:
    fields = [
        _positions_field(),
        _field("foerderung", "funding", isPromoted=True, promoteTarget="amount"),
    ]
    with pytest.raises(FormDefinitionError, match="must be numeric"):
        validate_definition(fields)


def test_funding_within_cost_total_is_valid() -> None:
    data = {"positions": _costs(300, 200), "foerderung": "500"}
    validate_answers(_funding_form(), data)
    validate_answers(_funding_form(), {**data, "foerderung": 120.5})


def test_funding_optional_and_required() -> None:
    validate_answers(_funding_form(), {"positions": _costs(100)})
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers(_funding_form(required=True), {"positions": _costs(100)})
    assert _errkeys(ei.value) == {"foerderung"}


def test_funding_above_cost_total_rejected() -> None:
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers(_funding_form(), {"positions": _costs(300, 200), "foerderung": 500.01})
    assert [e.msg for e in ei.value.errors] == ["greater than the cost total 500"]


def test_funding_without_positions_answer_rejected() -> None:
    fields = [
        _positions_field(validation={"minOffers": 1}, visibleIf={"==": [{"var": "x"}, 1]}),
        _field("foerderung", "funding"),
    ]
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers(fields, {"positions": _costs(100), "foerderung": 50})
    assert [e.msg for e in ei.value.errors] == ["greater than the cost total 0"]


@pytest.mark.parametrize(
    ("bad", "msg"),
    [(0, "must be greater than 0"), (-5, "must be greater than 0"), ("abc", "must be a number")],
)
def test_funding_bad_value_gives_one_error(bad: object, msg: str) -> None:
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers(_funding_form(), {"positions": _costs(100), "foerderung": bad})
    assert [e.msg for e in ei.value.errors] == [msg]


def test_funding_before_positions_in_field_order() -> None:
    fields = list(reversed(_funding_form()))
    validate_answers(fields, {"positions": _costs(100), "foerderung": 100})
    with pytest.raises(AnswerValidationError):
        validate_answers(fields, {"positions": _costs(100), "foerderung": 101})


def test_extract_promoted_funding_replaces_cost_total() -> None:
    fields = [*_funding_form(), _field("x", "currency", isPromoted=True, promoteTarget="amount")]
    data = {"positions": _costs(300, 200), "foerderung": "350.50", "x": 7}
    assert extract_promoted(fields, data) == {"amount": Decimal("350.50")}


@pytest.mark.parametrize("empty", [None, "", "abc", True, "NaN"])
def test_extract_promoted_without_funding_keeps_cost_total(empty: object) -> None:
    data = {"positions": _costs(300, 200), "foerderung": empty}
    assert extract_promoted(_funding_form(), data) == {"amount": Decimal("500")}


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


def test_text_valid_and_constraints() -> None:
    f = _field("t", "text", validation={"minLen": 2, "maxLen": 4, "pattern": "[a-z]+"})
    assert validate_answers([f], {"t": "abc"}) == {"t": "abc"}
    len_only = _field("t", "text", validation={"minLen": 2, "maxLen": 4})
    assert validate_answers([len_only], {"t": "abc"}) == {"t": "abc"}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"t": "a"})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"t": "abcde"})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"t": "AB"})
    with pytest.raises(AnswerValidationError):
        validate_answers([_field("t", "text")], {"t": 123})


def test_text_runtime_bad_pattern_is_422_not_500() -> None:
    """Give a field error, not a 500, for a broken pattern at runtime.

    This is defense in depth, because validate_definition normally rejects it.
    """
    f = _field("t", "text", validation={"pattern": "["})
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers([f], {"t": "x"})
    assert ei.value.errors[0].msg == "field has an invalid validation pattern"


def test_pattern_value_over_length_cap_is_rejected() -> None:
    """Never match a value above `_PATTERN_MAX_INPUT_LEN`; the engine skips the match."""
    from app.modules.forms.validation import _PATTERN_MAX_INPUT_LEN

    f = _field("t", "text", validation={"pattern": ".*"})
    over = "a" * (_PATTERN_MAX_INPUT_LEN + 1)
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers([f], {"t": over})
    assert ei.value.errors[0].msg == "does not match required pattern"


def test_pattern_value_at_length_cap_still_matches() -> None:
    """Run the normal match for a value exactly at the cap."""
    from app.modules.forms.validation import _PATTERN_MAX_INPUT_LEN

    f = _field("t", "text", validation={"pattern": "a*"})
    at = "a" * _PATTERN_MAX_INPUT_LEN
    assert validate_answers([f], {"t": at}) == {"t": at}


def test_pattern_match_timeout_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give a field error for a match timeout; never stall the event loop or give a 500."""
    from concurrent.futures import TimeoutError as FutureTimeout

    from app.modules.forms import validation as val_mod

    class _StuckFuture:
        def result(self, timeout: float | None = None) -> bool:
            raise FutureTimeout

    class _StuckExecutor:
        def submit(self, *_a: object, **_k: object) -> _StuckFuture:
            return _StuckFuture()

    monkeypatch.setattr(val_mod, "_PATTERN_EXECUTOR", _StuckExecutor())
    f = _field("t", "text", validation={"pattern": "[a-z]+"})
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers([f], {"t": "abc"})
    assert ei.value.errors[0].msg == "field has an invalid validation pattern"


def test_number_valid_and_range() -> None:
    """Accept a number in range and reject a bool and values out of range."""
    f = _field("n", "number", validation={"min": 0, "max": 10})
    assert validate_answers([f], {"n": 5}) == {"n": 5}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"n": -1})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"n": 11})
    with pytest.raises(AnswerValidationError):
        validate_answers([_field("n", "number")], {"n": True})
    with pytest.raises(AnswerValidationError):
        validate_answers([_field("n", "number")], {"n": "x"})


def test_currency_valid() -> None:
    f = _field("c", "currency", validation={"min": 0})
    assert validate_answers([f], {"c": "250.00"}) == {"c": "250.00"}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"c": -5})


@pytest.mark.parametrize("ftype", ["number", "currency"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity"])
def test_number_currency_non_finite_is_422_not_500(ftype: str, bad: object) -> None:
    """Give a field error, not a 500, for NaN or Infinity.

    ``Decimal("NaN")`` builds without an error, but a min or max compare raises
    ``decimal.InvalidOperation``. The range constraints are the path that really breaks.
    """
    plain = _field("n", ftype)
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers([plain], {"n": bad})
    assert ei.value.errors[0].msg == "must be a finite number"
    ranged = _field("n", ftype, validation={"min": 0, "max": 10})
    with pytest.raises(AnswerValidationError):
        validate_answers([ranged], {"n": bad})


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


@pytest.mark.parametrize("bad", [1, True, 1.0, ["a"], {"a": 1}])
def test_select_non_string_is_422_not_500(bad: object) -> None:
    """Reject a non-string value, also an unhashable one, as an invalid option."""
    f = _field("s", "select", options=[{"value": "a", "label": {"de": "A"}}])
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"s": bad})


def test_multiselect_valid_invalid() -> None:
    """Accept valid options and reject an invalid option and a non-list."""
    f = _field(
        "m",
        "multiselect",
        options=[{"value": "a", "label": {"de": "A"}}, {"value": "b", "label": {"de": "B"}}],
    )
    assert validate_answers([f], {"m": ["a", "b"]}) == {"m": ["a", "b"]}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"m": ["a", "z"]})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"m": "a"})


def test_multiselect_unhashable_element_is_422_not_500() -> None:
    """Reject an unhashable element as an invalid option without a TypeError."""
    f = _field("m", "multiselect", options=[{"value": "a", "label": {"de": "A"}}])
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"m": ["a", {"nested": 1}]})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"m": [1, ["x"]]})


@pytest.mark.parametrize("ftype", ["gremium_select", "budget_select"])
def test_dynamic_select_uuid_valid_invalid(ftype: str) -> None:
    """Accept a uuid, reject other values, and skip an empty string of an optional field."""
    f = _field("ziel", ftype)
    good = "00000000-0000-0000-0000-0000000060e1"
    assert validate_answers([f], {"ziel": good}) == {"ziel": good}
    for bad in ("not-a-uuid", 42):
        with pytest.raises(AnswerValidationError):
            validate_answers([f], {"ziel": bad})


def test_email_field_valid_invalid() -> None:
    f = _field("mail", "email")
    assert validate_answers([f], {"mail": "a@b.de"}) == {"mail": "a@b.de"}
    for bad in ("no-at", "a@b", "a b@c.de", 1):
        with pytest.raises(AnswerValidationError):
            validate_answers([f], {"mail": bad})


def test_iban_field_checksum() -> None:
    """Accept a valid test IBAN with spaces and reject a bad checksum."""
    f = _field("iban", "iban")
    assert validate_answers([f], {"iban": "DE89 3704 0044 0532 0130 00"}) == {
        "iban": "DE89 3704 0044 0532 0130 00"
    }
    for bad in ("DE00370400440532013000", "GB82WEST12345698765432X!", "short", 1):
        with pytest.raises(AnswerValidationError):
            validate_answers([f], {"iban": bad})


def test_daterange_field_valid_invalid() -> None:
    f = _field("zr", "daterange")
    ok = {"from": "2026-01-01", "to": "2026-01-03"}
    assert validate_answers([f], {"zr": ok}) == {"zr": ok}
    for bad in (
        "not-a-dict",
        {"from": "2026-01-01"},
        {"from": "2026-01-05", "to": "2026-01-01"},
        {"from": "nope", "to": "2026-01-01"},
        {"from": 1, "to": 2},
    ):
        with pytest.raises(AnswerValidationError):
            validate_answers([f], {"zr": bad})


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
        validate_answers([f], {"rows": [{"a": 1}, {"b": 2}, {"c": 3}]})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"rows": "nope"})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"rows": ["nope"]})


def test_markdown_valid() -> None:
    assert validate_answers([_field("md", "markdown")], {"md": "# hi"}) == {"md": "# hi"}


def test_unknown_type_errors() -> None:
    """Reach the defensive else branch with a fake field type.

    FormFieldDef.type is a Literal, so the test drives the internal dispatcher directly.
    """
    errors: list[FieldError] = []
    _validate_value(SimpleNamespace(key="x", type="bogus"), "v", errors)  # type: ignore[arg-type]
    assert errors and "unknown field type" in errors[0].msg


def test_visible_if_hidden_skips_required() -> None:
    f = _field(
        "iban",
        "text",
        required=True,
        visibleIf={"==": [{"var": "has_budget"}, True]},
    )
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
    """Treat a visibleIf that raises as visible, so required applies.

    `and` and `or` do not short-circuit, so ``{">": [var y, 0]}`` raises for a missing y.
    """
    f = _field(
        "x",
        "text",
        required=True,
        visibleIf={"and": [{"var": "flag"}, {">": [{"var": "y"}, 0]}]},
    )
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {}, context={"flag": False})


def test_compute_derives_value() -> None:
    fields = [
        _field("qty", "number"),
        _field("unit_price", "currency"),
        _field("total", "computed", compute={"*": [{"var": "qty"}, {"var": "unit_price"}]}),
    ]
    out = validate_answers(fields, {"qty": 3, "unit_price": 10})
    assert out["total"] == 30


def test_compute_failure_reports_error() -> None:
    """Report a compute error such as a division by zero."""
    fields = [_field("total", "computed", compute={"/": [{"var": "a"}, {"var": "b"}]})]
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers(fields, {"a": 1, "b": 0})
    assert _errkeys(ei.value) == {"total"}


def test_compute_value_visible_in_visible_if() -> None:
    """Use a computed value in visibleIf.

    A total of 5 keeps the note hidden. A total of 11 makes it visible and required.
    """
    fields = [
        _field("qty", "number"),
        _field("total", "computed", compute={"+": [{"var": "qty"}, 1]}),
        _field("note", "text", required=True, visibleIf={">": [{"var": "total"}, 5]}),
    ]
    assert "note" not in validate_answers(fields, {"qty": 4})
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers(fields, {"qty": 10})
    assert _errkeys(ei.value) == {"note"}


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


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "NaN", "Infinity"])
def test_extract_promoted_non_finite_skipped(bad: object) -> None:
    """Never pass NaN or Infinity on as the amount."""
    fields = [_field("amount", "currency", isPromoted=True, promoteTarget="amount")]
    assert extract_promoted(fields, {"amount": bad}) == {}
