"""A computed field as the amount of the Antrag (specs 000284, 002840, 002841).

The tests prove: the definition check takes a computed amount field and refuses a second
source of the amount. The server computes every computed field again, ignores the value
of the client, rounds the amount half up to cents and refuses a result that is no amount.
The promoted amount and the form rules read the computed value.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.modules.applications.service.service_base import _amount_currency
from app.modules.forms.validation import (
    AnswerValidationError,
    FormDefinitionError,
    extract_promoted,
    is_computed_amount,
    rule_context,
    validate_answers,
    validate_definition,
    with_computed,
)
from app.shared.config_schemas import FormFieldDef

_RATE = {"/": [{"*": [{"var": "km"}, 35]}, 100]}


def _field(key: str, type: str, **kw: Any) -> FormFieldDef:
    kw.setdefault("label", {"de": key})
    return FormFieldDef.model_validate({"key": key, "type": type, **kw})


def _amount(compute: dict[str, Any] | None = None, **kw: Any) -> FormFieldDef:
    return _field(
        "summe",
        "computed",
        compute=compute or _RATE,
        isPromoted=True,
        promoteTarget="amount",
        **kw,
    )


def _form(compute: dict[str, Any] | None = None) -> list[FormFieldDef]:
    return [_field("km", "number", required=True), _amount(compute)]


def _errors(fields: list[FormFieldDef], data: dict[str, Any]) -> dict[str, str]:
    with pytest.raises(AnswerValidationError) as ei:
        validate_answers(fields, data)
    return {e.field: e.msg for e in ei.value.errors}


def test_definition_takes_a_computed_amount_field() -> None:
    validate_definition(_form())
    assert is_computed_amount(_amount())
    assert not is_computed_amount(_field("x", "computed", compute=_RATE))


def test_definition_refuses_a_computed_field_with_another_target() -> None:
    field = _field("summe", "computed", compute=_RATE, isPromoted=True, promoteTarget="other")
    with pytest.raises(FormDefinitionError, match="must be numeric"):
        validate_definition([field])


def test_definition_still_refuses_other_non_numeric_promoted_types() -> None:
    with pytest.raises(FormDefinitionError, match="must be numeric"):
        validate_definition([_field("x", "text", isPromoted=True, promoteTarget="amount")])


@pytest.mark.parametrize(
    "other",
    [
        _field("pos", "positions"),
        _field("cost", "currency", isPromoted=True, promoteTarget="amount"),
    ],
)
def test_definition_refuses_a_second_amount_source(other: FormFieldDef) -> None:
    with pytest.raises(FormDefinitionError, match="only source of the amount"):
        validate_definition([*_form(), other])


def test_definition_refuses_a_computed_amount_beside_funding() -> None:
    fields = [*_form(), _field("pos", "positions"), _field("f", "funding")]
    with pytest.raises(FormDefinitionError, match="only source of the amount"):
        validate_definition(fields)


def test_definition_refuses_two_computed_amount_fields() -> None:
    second = _field("zwei", "computed", compute=_RATE, isPromoted=True, promoteTarget="amount")
    with pytest.raises(FormDefinitionError, match="only source of the amount"):
        validate_definition([*_form(), second])


def test_server_value_wins_over_the_client_value() -> None:
    fields = _form()
    data = with_computed(fields, {"km": 84, "summe": 999})
    assert data == {"km": 84, "summe": 29.4}
    assert validate_answers(fields, {"km": 84, "summe": 999}) == data
    assert _amount_currency(fields, data) == (Decimal("29.40"), "EUR")


def test_an_edit_computes_again() -> None:
    fields = _form()
    data = with_computed(fields, {"km": 100, "summe": 29.4})
    assert data["summe"] == 35.0
    assert _amount_currency(fields, data) == (Decimal("35.00"), "EUR")


def test_a_numeric_text_answer_is_read_as_its_number() -> None:
    assert with_computed(_form(), {"km": "84"})["summe"] == 29.4


def test_the_amount_is_rounded_half_up_to_cents() -> None:
    fields = _form({"*": [{"var": "km"}, 1]})
    assert with_computed(fields, {"km": 29.405})["summe"] == 29.41
    assert with_computed(fields, {"km": 0.125})["summe"] == 0.13
    assert extract_promoted(fields, {"km": 1, "summe": 0.125}) == {"amount": Decimal("0.13")}


def test_a_missing_input_is_refused_and_gives_no_amount() -> None:
    fields = _form()
    errors = _errors(fields, {"summe": 999})
    assert errors["km"] == "required"
    assert errors["summe"].startswith("compute failed")
    data = with_computed(fields, {"summe": 999})
    assert "summe" not in data
    assert _amount_currency(fields, data) == (None, None)


@pytest.mark.parametrize(
    "compute",
    [
        {"-": [0, {"var": "km"}]},
        {"var": "nothing"},
        {"==": [{"var": "km"}, 84]},
        {"var": ["nothing", "abc"]},
        {"*": [{"var": "km"}, 1e308, 10]},
    ],
)
def test_a_result_that_is_no_amount_is_refused(compute: dict[str, Any]) -> None:
    fields = [_field("km", "number", required=True), _amount(compute)]
    assert _errors(fields, {"km": 84}) == {"summe": "the amount must be a finite number from 0"}
    assert "summe" not in with_computed(fields, {"km": 84, "summe": 5})


def test_zero_is_an_amount() -> None:
    fields = _form()
    assert validate_answers(fields, {"km": 0}) == {"km": 0, "summe": 0.0}


def test_every_computed_field_is_computed_by_the_server() -> None:
    fields = [
        _field("km", "number"),
        _field("double", "computed", compute={"*": [{"var": "km"}, 2]}),
    ]
    assert with_computed(fields, {"km": 3, "double": "forged"}) == {"km": 3, "double": 6.0}
    assert with_computed(fields, {"double": "forged"}) == {}


def test_a_form_rule_reads_the_computed_amount() -> None:
    fields = _form()
    ctx = rule_context(fields, with_computed(fields, {"km": 84, "summe": 999}))
    assert ctx["amount"] == 29.4
    assert ctx["summe"] == 29.4
