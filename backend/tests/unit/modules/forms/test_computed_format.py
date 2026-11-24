"""Computed fields that read the cost total and have a format (specs 002960-002962).

The tests prove: an expression reads ``costTotal`` and ``amount`` like a form rule, a
field that cannot be computed stays empty without an error, ``money`` rounds to cents and
``percent`` to four decimal places, and only a ``computed`` field takes a format. The
shared fixture runs here and in the frontend, so both sides compute the same values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.forms.validation import validate_answers, with_computed
from app.shared.config_schemas import FormFieldDef

_FIXTURE = (
    Path(__file__).resolve().parents[5] / "frontend/src/app/shared/forms/computed.fixture.json"
)
FIXTURE: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
FIELDS = [FormFieldDef.model_validate(f) for f in FIXTURE["fields"]]
COMPUTED = [f.key for f in FIELDS if f.type == "computed"]


def _field(key: str, type: str, **kw: Any) -> FormFieldDef:
    kw.setdefault("label", {"de": key})
    return FormFieldDef.model_validate({"key": key, "type": type, **kw})


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=[c["name"] for c in FIXTURE["cases"]])
def test_shared_fixture_gives_the_same_values(case: dict[str, Any]) -> None:
    out = with_computed(FIELDS, case["data"])
    got = {k: out[k] for k in COMPUTED if k in out}
    assert got == pytest.approx(case["values"])
    assert set(got) == set(case["values"])


def test_an_empty_funding_does_not_stop_the_submit() -> None:
    offers = [{"label": n, "value": 0, "preferred": n == "A"} for n in "ABC"]
    out = validate_answers(FIELDS, {"kosten": [{"label": "P", "offers": offers}]})
    assert "foerderquote" not in out
    assert "eigenanteil" not in out


def test_percent_rounds_to_four_decimal_places() -> None:
    fields = [_field("q", "computed", compute={"/": [1000, 1200]}, format="percent")]
    assert with_computed(fields, {})["q"] == 0.8333


def test_money_rounds_half_up_to_cents() -> None:
    fields = [_field("m", "computed", compute={"-": [1200, 1000.004]}, format="money")]
    assert with_computed(fields, {})["m"] == 200.0


def test_money_needs_a_number() -> None:
    fields = [_field("m", "computed", compute={">": [2, 1]}, format="money")]
    assert "m" not in with_computed(fields, {})


def test_number_keeps_a_value_that_is_no_number() -> None:
    fields = [_field("flag", "computed", compute={">": [2, 1]})]
    assert with_computed(fields, {})["flag"] is True


def test_a_number_that_is_not_finite_gives_no_value() -> None:
    fields = [_field("big", "computed", compute={"*": [1e308, 10]})]
    assert "big" not in with_computed(fields, {})


def test_only_a_computed_field_takes_a_format() -> None:
    with pytest.raises(ValidationError, match="format is allowed only"):
        _field("t", "text", format="money")
