"""Pure form engine T-11 (validate_definition, effective_form, validate_answers).

Acceptance criteria: every field type passes and fails as expected. Required fields
apply. A visible visibleIf field becomes mandatory. compute derives the right value.
An unknown type raises an error. effective_form builds the sections. extract_promoted
reads the promoted values.
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
    # S1: without this gate, a broken regex pattern causes a 500 at answer time.
    with pytest.raises(FormDefinitionError, match="invalid validation pattern"):
        validate_definition([_field("t", "text", validation={"pattern": "["})])


def test_validate_definition_rejects_bad_jsonlogic() -> None:
    # FormFieldDef validates JsonLogic at build time. This test bends the field after
    # the build to reach the defensive storage gate in validate_definition.
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
    sections = effective_form(
        [
            _field("intro", "section", label={"de": "Start"}),
            _field("a", "text"),
        ]
    )
    assert [s.key for s in sections] == ["intro"]
    assert sections[0].label == {"de": "Start"}
    # No title field is present, so the engine injects one into the intro section.
    assert [f.key for f in sections[0].fields] == [SYSTEM_TITLE_KEY, "a"]


def test_validate_answers_ignores_section_markers() -> None:
    # A section marker is never required and it carries no answer value.
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
    field = _positions_field()  # no validation block, so minOffers falls back to 3
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
    # The engine ceiling applies even without maxPositions (#sec-audit AUD-047).
    field = _positions_field(validation={"minOffers": 1, "maxPositions": 2})
    value = [_position(f"P{i}", ("A", 5, True)) for i in range(3)]
    errors: list[FieldError] = []
    _validate_value(field, value, errors)
    assert any("more than 2 position" in e.msg for e in errors)


def test_positions_engine_default_max_positions() -> None:
    field = _positions_field(validation={"minOffers": 1})  # no maxPositions, so the cap applies
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
    # The engine allows the opt-out by default. One offer plus a reason beats minOffers 3.
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
    # A table without maxRows keeps the default cap on the row count.
    f = _field("rows", "table")
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"rows": [{"i": n} for n in range(1001)]})


def test_table_explicit_max_rows_zero_rejects_any_row() -> None:
    # AUD-047 regression: an explicit maxRows=0 is valid (ge=0) and must reject every
    # row. A falsy `or` must not fall back to the default cap of 1000.
    f = _field("rows", "table", validation={"maxRows": 0})
    with pytest.raises(AnswerValidationError) as exc:
        validate_answers([f], {"rows": [{"a": 1}, {"b": 2}, {"c": 3}]})
    assert "rows" in _errkeys(exc.value)
    # An empty table stays valid at maxRows=0 because 0 rows is not more than 0.
    assert validate_answers([f], {"rows": []}) == {"rows": []}


def test_table_configured_max_rows_capped_at_engine_ceiling() -> None:
    # A builder value above the engine cap cannot lift that cap.
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
    # Defense in depth: validate_definition normally rejects a broken pattern. At
    # runtime a broken pattern must not cause a 500.
    f = _field("t", "text", validation={"pattern": "["})
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers([f], {"t": "x"})
    assert ei.value.errors[0].msg == "field has an invalid validation pattern"


# ReDoS hardening: input length cap plus wall-clock timeout (security.md)
def test_pattern_value_over_length_cap_is_rejected() -> None:
    # A value above _PATTERN_MAX_INPUT_LEN never matches. The engine skips the match.
    from app.modules.forms.validation import _PATTERN_MAX_INPUT_LEN

    f = _field("t", "text", validation={"pattern": ".*"})
    over = "a" * (_PATTERN_MAX_INPUT_LEN + 1)
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers([f], {"t": over})
    assert ei.value.errors[0].msg == "does not match required pattern"


def test_pattern_value_at_length_cap_still_matches() -> None:
    # A value exactly at the limit runs the normal match. The cap does not cut in.
    from app.modules.forms.validation import _PATTERN_MAX_INPUT_LEN

    f = _field("t", "text", validation={"pattern": "a*"})
    at = "a" * _PATTERN_MAX_INPUT_LEN
    assert validate_answers([f], {"t": at}) == {"t": at}


def test_pattern_match_timeout_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    # A wall-clock timeout (ReDoS) gives a field error. It never stalls the event
    # loop and it never gives a 500.
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
    f = _field("n", "number", validation={"min": 0, "max": 10})
    assert validate_answers([f], {"n": 5}) == {"n": 5}
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"n": -1})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"n": 11})
    with pytest.raises(AnswerValidationError):
        validate_answers([_field("n", "number")], {"n": True})  # a bool is not a number
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
    # B1: Decimal("NaN") builds without an error. A min or max compare then raises
    # decimal.InvalidOperation and gives a 500. This must end as a 422 field error.
    plain = _field("n", ftype)
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers([plain], {"n": bad})
    assert ei.value.errors[0].msg == "must be a finite number"
    # Also test the range constraints, because that is the path that really breaks.
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
    # FieldOption.value is a str. A non-string value, also an unhashable dict or
    # list, must end as an invalid option and never as a 500.
    f = _field("s", "select", options=[{"value": "a", "label": {"de": "A"}}])
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"s": bad})


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


def test_multiselect_unhashable_element_is_422_not_500() -> None:
    # An unhashable element such as a dict or a list must not raise a TypeError in
    # the membership test. It must end as an invalid option.
    f = _field("m", "multiselect", options=[{"value": "a", "label": {"de": "A"}}])
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"m": ["a", {"nested": 1}]})
    with pytest.raises(AnswerValidationError):
        validate_answers([f], {"m": [1, ["x"]]})


@pytest.mark.parametrize("ftype", ["gremium_select", "budget_select"])
def test_dynamic_select_uuid_valid_invalid(ftype: str) -> None:
    f = _field("ziel", ftype)
    good = "00000000-0000-0000-0000-0000000060e1"
    assert validate_answers([f], {"ziel": good}) == {"ziel": good}
    # An empty string counts as absent. The engine skips it because the field is optional.
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
    f = _field("iban", "iban")
    # A valid test IBAN (mod 97). The engine accepts spaces.
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
    # FormFieldDef.type is a Literal. This test drives the internal dispatcher with a
    # fake field to reach the defensive else branch.
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
    # T-05: and/or do not short-circuit. {">": [var y, 0]} raises when y is missing.
    # The field then counts as visible, so required applies.
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
    # total is 5, so note stays hidden and no required error appears.
    assert "note" not in validate_answers(fields, {"qty": 4})
    # total is 11, so note becomes visible and required applies.
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
    # B1: never pass a Decimal NaN or a Decimal Infinity on as an amount.
    fields = [_field("amount", "currency", isPromoted=True, promoteTarget="amount")]
    assert extract_promoted(fields, {"amount": bad}) == {}
