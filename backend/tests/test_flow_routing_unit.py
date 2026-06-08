"""Unit (ohne DB): reine Routing-Logik der Global-Flow-Engine (#28).

Deckt das Prädikat-DSL (amount/typeKey/applicantRole + Operatoren, fail-closed) und
die Erste-Treffer-/else-Auflösung von ``decision``-States ab.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.flow.routing import DecisionFacts, evaluate_decision


def _facts(amount=None, type_key=None, roles=()):
    return DecisionFacts(
        amount=None if amount is None else Decimal(str(amount)),
        type_key=type_key,
        applicant_roles=frozenset(roles),
    )


def test_amount_threshold_routes_to_gremium_vote() -> None:
    rules = [{"when": {"field": "amount", "op": ">=", "value": 500}, "to": "stupa_vote"}]
    assert evaluate_decision(rules, "vorstand_vote", _facts(amount=500)) == "stupa_vote"
    assert evaluate_decision(rules, "vorstand_vote", _facts(amount=499)) == "vorstand_vote"


def test_first_matching_rule_wins() -> None:
    rules = [
        {"when": {"field": "amount", "op": ">=", "value": 1000}, "to": "plenum"},
        {"when": {"field": "amount", "op": ">=", "value": 500}, "to": "stupa"},
    ]
    assert evaluate_decision(rules, "vorstand", _facts(amount=1500)) == "plenum"
    assert evaluate_decision(rules, "vorstand", _facts(amount=700)) == "stupa"
    assert evaluate_decision(rules, "vorstand", _facts(amount=100)) == "vorstand"


def test_type_key_routing() -> None:
    rules = [{"when": {"field": "typeKey", "op": "==", "value": "grossantrag"}, "to": "x"}]
    assert evaluate_decision(rules, "y", _facts(type_key="grossantrag")) == "x"
    assert evaluate_decision(rules, "y", _facts(type_key="kleinantrag")) == "y"
    rules_in = [{"when": {"field": "typeKey", "op": "in", "value": ["a", "b"]}, "to": "x"}]
    assert evaluate_decision(rules_in, "y", _facts(type_key="b")) == "x"


def test_applicant_role_routing() -> None:
    rules = [
        {"when": {"field": "applicantRole", "op": "in", "value": ["referent"]}, "to": "fast"}
    ]
    assert evaluate_decision(rules, "slow", _facts(roles=["referent"])) == "fast"
    assert evaluate_decision(rules, "slow", _facts(roles=["member"])) == "slow"
    has = [{"when": {"field": "applicantRole", "op": "has", "value": "vorstand"}, "to": "fast"}]
    assert evaluate_decision(has, "slow", _facts(roles=["vorstand", "member"])) == "fast"


def test_empty_when_is_unconditional_default() -> None:
    rules = [{"to": "always"}]  # no when → matches
    assert evaluate_decision(rules, "fallback", _facts(amount=5)) == "always"


def test_unknown_field_or_op_fails_closed_to_else() -> None:
    bad_field = [{"when": {"field": "nope", "op": "==", "value": 1}, "to": "x"}]
    assert evaluate_decision(bad_field, "else", _facts(amount=1)) == "else"
    bad_op = [{"when": {"field": "amount", "op": "~=", "value": 1}, "to": "x"}]
    assert evaluate_decision(bad_op, "else", _facts(amount=1)) == "else"


def test_amount_missing_does_not_match() -> None:
    rules = [{"when": {"field": "amount", "op": ">=", "value": 0}, "to": "x"}]
    # amount None → predicate False → else
    assert evaluate_decision(rules, "else", _facts(amount=None)) == "else"


def test_all_comparison_operators() -> None:
    f = _facts(amount=10)
    cases = {">": 9, ">=": 10, "<": 11, "<=": 10, "==": 10, "!=": 5}
    for op, val in cases.items():
        rules = [{"when": {"field": "amount", "op": op, "value": val}, "to": "hit"}]
        assert evaluate_decision(rules, "miss", f) == "hit", op
