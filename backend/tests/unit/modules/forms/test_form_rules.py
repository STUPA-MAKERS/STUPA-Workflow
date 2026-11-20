"""Rules across fields, the field for the number of participants and the root of a picker.

Specs 001631, 001670, 001671, 001680 and 001681. The shared fixture
`frontend/src/app/shared/forms/form-rules.fixture.json` runs here and in the frontend
test `form-rules.spec.ts`, so both evaluators give the same broken rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.applications.service.form_checks import (
    COST_CENTRE_OUTSIDE_SUBTREE,
    FORM_RULE_FAILED,
    check_form_rules,
)
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import below_root
from app.modules.forms.validation import (
    FormDefinitionError,
    broken_rules,
    cost_total,
    outside_subtree,
    rule_context,
    rule_met,
    validate_definition,
)
from app.shared.config_schemas import FieldOption, FormFieldDef, FormRule
from app.shared.errors import ValidationProblem

_FIXTURE = (
    Path(__file__).resolve().parents[5]
    / "frontend/src/app/shared/forms/form-rules.fixture.json"
)


def _fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _field(key: str, type: str, **kw: Any) -> FormFieldDef:
    kw.setdefault("label", {"de": key})
    return FormFieldDef.model_validate({"key": key, "type": type, **kw})


def _rule(logic: dict[str, Any], severity: str = "block") -> FormRule:
    return FormRule.model_validate(
        {"logic": logic, "message": {"de": "Regel", "en": "Rule"}, "severity": severity}
    )


def _position(value: float) -> dict[str, Any]:
    return {"label": "P", "offers": [{"label": "A", "value": value, "preferred": True}]}


FIXTURE = _fixture()


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=[c["name"] for c in FIXTURE["cases"]])
def test_shared_fixture_gives_the_same_broken_rules(case: dict[str, Any]) -> None:
    fields = [FormFieldDef.model_validate(f) for f in FIXTURE["fields"]]
    rules = [FormRule.model_validate(r) for r in FIXTURE["rules"]]
    validate_definition(fields)
    broken = [i for i, _rule in broken_rules(rules, fields, case["data"])]
    assert broken == case["broken"]


def test_a_rule_with_an_operator_that_is_not_allowed_is_refused() -> None:
    with pytest.raises(ValidationError, match="unknown operator"):
        _rule({"eval": ["1"]})


def test_a_rule_needs_its_message_in_both_languages() -> None:
    with pytest.raises(ValidationError, match="German and in English"):
        FormRule.model_validate({"logic": {"var": "a"}, "message": {"de": "Nur Deutsch"}})


def test_a_form_version_saves_its_rules() -> None:
    payload = FormVersionCreate.model_validate(
        {
            "fields": [{"key": "a", "type": "number", "label": {"de": "A"}}],
            "rules": [
                {
                    "logic": {">=": [{"var": "a"}, 1]},
                    "message": {"de": "A", "en": "A"},
                    "severity": "warn",
                }
            ],
        }
    )
    assert payload.rules[0].severity == "warn"
    assert payload.model_dump(by_alias=True)["rules"][0]["logic"] == {">=": [{"var": "a"}, 1]}


def test_the_severity_defaults_to_block() -> None:
    rule = FormRule.model_validate({"logic": {"var": "a"}, "message": {"de": "x", "en": "y"}})
    assert rule.severity == "block"


def test_rule_met_needs_exactly_true() -> None:
    assert rule_met(_rule({"var": "a"}), {"a": True}) is True
    assert rule_met(_rule({"var": "a"}), {"a": 1}) is False
    assert rule_met(_rule({">": [{"var": "a"}, 1]}), {"a": None}) is True


def test_rule_context_holds_amount_and_cost_total() -> None:
    fields = [_field("kosten", "positions"), _field("foerderung", "funding")]
    ctx = rule_context(fields, {"kosten": [_position(80), _position(20)], "foerderung": 60})
    assert ctx["amount"] == 60.0
    assert ctx["costTotal"] == 100.0
    assert ctx["kosten"][0]["label"] == "P"


def test_rule_context_without_positions_has_no_amount() -> None:
    ctx = rule_context([_field("a", "text")], {"a": "x"})
    assert ctx["amount"] is None
    assert ctx["costTotal"] is None


def test_cost_total_adds_every_positions_field() -> None:
    fields = [_field("a", "positions"), _field("b", "positions"), _field("c", "text")]
    assert cost_total(fields, {"a": [_position(1.5)], "b": [_position(2)]}) == 3.5
    assert cost_total(fields, {"a": [], "c": "x"}) is None


def test_participants_belongs_to_one_number_field() -> None:
    validate_definition([_field("n", "number", validation={"participants": True})])
    with pytest.raises(FormDefinitionError, match="at most one field"):
        validate_definition(
            [
                _field("n", "number", validation={"participants": True}),
                _field("m", "number", validation={"participants": True}),
            ]
        )
    with pytest.raises(FormDefinitionError, match="only a number field"):
        validate_definition([_field("t", "text", validation={"participants": True})])


def test_root_belongs_to_a_budget_select_field() -> None:
    validate_definition([_field("ks", "budget_select", validation={"rootPath": "QSM"})])
    with pytest.raises(FormDefinitionError, match="only a budget_select field"):
        validate_definition([_field("t", "text", validation={"rootPath": "QSM"})])


def _opt(value: str, parent: str | None, path: str) -> FieldOption:
    return FieldOption.model_validate(
        {"value": value, "label": {"de": path}, "parentId": parent, "pathKey": path}
    )


def test_below_root_keeps_the_subtree_without_the_root() -> None:
    options = [
        _opt("q", None, "QSM"),
        _opt("q1", "q", "QSM-1"),
        _opt("q11", "q1", "QSM-11"),
        _opt("v", None, "VSM"),
        _opt("v1", "v", "VSM-1"),
    ]
    out = below_root(options, "QSM")
    assert [o.value for o in out] == ["q1", "q11"]
    assert out[0].parent_id is None
    assert out[1].parent_id == "q1"
    assert below_root(options, "XYZ") == []


def test_outside_subtree_reads_the_injected_options() -> None:
    field = _field(
        "ks",
        "budget_select",
        validation={"rootPath": "QSM"},
        options=[{"value": "q1", "label": {"de": "Q1"}}],
    )
    free = _field("frei", "budget_select")
    assert outside_subtree([field, free], {"ks": "q1", "frei": "anything"}) == ()
    assert outside_subtree([field], {"ks": None}) == ()
    (err,) = outside_subtree([field], {"ks": "v1"})
    assert err.field == "ks"


def _effective(fields: list[FormFieldDef], rules: list[FormRule]) -> Any:
    return SimpleNamespace(sections=[SimpleNamespace(fields=fields)], rules=rules)


def test_check_form_rules_refuses_a_block_rule() -> None:
    fields = [_field("a", "number")]
    block = _rule({">=": [{"var": "a"}, 10]})
    warn = _rule({">=": [{"var": "a"}, 100]}, "warn")
    check_form_rules(_effective(fields, [block, warn]), {"a": 50})
    with pytest.raises(ValidationProblem) as exc:
        check_form_rules(_effective(fields, [warn, block]), {"a": 5})
    assert exc.value.code == FORM_RULE_FAILED
    assert [e.field for e in exc.value.errors or ()] == ["rules[1]"]


def test_check_form_rules_refuses_a_cost_centre_outside_the_root() -> None:
    field = _field(
        "ks",
        "budget_select",
        validation={"rootPath": "QSM"},
        options=[{"value": "q1", "label": {"de": "Q1"}}],
    )
    with pytest.raises(ValidationProblem) as exc:
        check_form_rules(_effective([field], []), {"ks": str(uuid4())})
    assert exc.value.code == COST_CENTRE_OUTSIDE_SUBTREE


def test_check_form_rules_of_an_edit_reads_only_the_changed_fields() -> None:
    field = _field(
        "ks",
        "budget_select",
        validation={"rootPath": "QSM"},
        options=[{"value": "q1", "label": {"de": "Q1"}}],
    )
    check_form_rules(_effective([field], []), {"ks": "old"}, changed=frozenset({"title"}))
    with pytest.raises(ValidationProblem):
        check_form_rules(_effective([field], []), {"ks": "old"}, changed=frozenset({"ks"}))
