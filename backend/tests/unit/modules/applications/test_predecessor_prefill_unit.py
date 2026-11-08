"""The prefill of a Folgeantrag picks the answers of the Vorgänger that the current form takes.

§ F/applications/applications/000544: only a key of the current form with a valid value;
file, derived and structural fields and unreadable ``isPII`` fields stay out.
"""

from __future__ import annotations

from typing import Any

from app.modules.applications.service.links import prefill_data
from app.modules.forms.validation import value_is_valid
from app.shared.config_schemas import FormFieldDef


def _field(key: str, type_: str = "text", **extra: Any) -> FormFieldDef:
    return FormFieldDef.model_validate({"key": key, "type": type_, "label": {"de": key}, **extra})


def test_prefill_keeps_only_fitting_answers() -> None:
    """§ 000544: a removed key, an invalid value, a file and a hidden key stay out."""
    fields = [
        _field("title"),
        _field("short", validation={"maxLen": 3}),
        _field("amount", "number"),
        _field("doc", "file"),
        _field("total", "computed", compute={"+": [1, 1]}),
        _field("iban", "iban", isPII=True),
        _field("empty"),
    ]
    data = {
        "title": "Sommerfest",
        "short": "viel zu lang",
        "amount": 120,
        "doc": ["0b9f8e8a-0000-4000-8000-000000000000"],
        "total": 2,
        "iban": "DE89370400440532013000",
        "empty": "",
        "gone": "weg",
    }

    assert prefill_data(fields, data, {"iban"}) == {"title": "Sommerfest", "amount": 120}
    assert prefill_data(fields, data, set())["iban"] == "DE89370400440532013000"


def test_value_is_valid_needs_a_present_valid_value() -> None:
    """§ 000544: an absent value is not copied, a wrong type neither."""
    number = _field("n", "number")
    assert value_is_valid(number, 3)
    assert not value_is_valid(number, "drei")
    assert not value_is_valid(number, None)
