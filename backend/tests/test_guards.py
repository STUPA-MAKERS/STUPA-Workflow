"""TDD: pure Guard-/Action-Evaluator (flows §9.2, #28-Redesign). Branch-Coverage 100 %."""

from decimal import Decimal

import pytest

from app.shared.guards import (
    ACTION_TYPES,
    GUARD_OPERATORS,
    GuardContext,
    GuardError,
    eval_guard,
    validate_action,
    validate_guard,
)


def test_empty_guard_is_true() -> None:
    assert eval_guard(None, GuardContext()) is True
    assert eval_guard({}, GuardContext()) is True


# --- Akteur-Gates (manuell) -------------------------------------------------
def test_role_is() -> None:
    ctx = GuardContext(roles=frozenset({"reviewer"}))
    assert eval_guard({"roleIs": "reviewer"}, ctx) is True
    assert eval_guard({"roleIs": "admin"}, ctx) is False


def test_is_in_committee() -> None:
    ctx = GuardContext(actor_committees=frozenset({"g-1"}))
    assert eval_guard({"isInCommittee": "g-1"}, ctx) is True
    assert eval_guard({"isInCommittee": "g-2"}, ctx) is False


# --- Antragsteller ----------------------------------------------------------
def test_applicant_role_and_committee() -> None:
    ctx = GuardContext(
        applicant_roles=frozenset({"student"}),
        applicant_committees=frozenset({"g-9"}),
    )
    assert eval_guard({"applicantRoleIs": "student"}, ctx) is True
    assert eval_guard({"applicantRoleIs": "staff"}, ctx) is False
    assert eval_guard({"applicantCommitteeIs": "g-9"}, ctx) is True
    assert eval_guard({"applicantCommitteeIs": "g-0"}, ctx) is False


# --- Budget -----------------------------------------------------------------
def test_budget_is_and_fits() -> None:
    ctx = GuardContext(budget_id="b-1", budget_fits=True)
    assert eval_guard({"budgetIs": "b-1"}, ctx) is True
    assert eval_guard({"budgetIs": "b-2"}, ctx) is False
    assert eval_guard({"budgetIs": "b-1"}, GuardContext()) is False
    assert eval_guard({"budgetFitsApplication": True}, ctx) is True
    assert eval_guard({"budgetFitsApplication": False}, ctx) is False


def test_deadline_passed() -> None:
    assert eval_guard({"deadlinePassed": True}, GuardContext(deadline_passed=True)) is True
    assert eval_guard({"deadlinePassed": True}, GuardContext(deadline_passed=False)) is False


# --- Felder -----------------------------------------------------------------
def test_has_field() -> None:
    ctx = GuardContext(field_values={"iban": "DE123", "blank": "", "list": []})
    assert eval_guard({"hasField": "iban"}, ctx) is True
    assert eval_guard({"hasField": "blank"}, ctx) is False
    assert eval_guard({"hasField": "list"}, ctx) is False
    assert eval_guard({"hasField": "missing"}, ctx) is False


def test_compare_numeric() -> None:
    ctx = GuardContext(
        field_values={"amount": Decimal("500")}, field_types={"amount": "currency"}
    )
    assert eval_guard({"compare": {"field": "amount", "op": ">", "value": 100}}, ctx) is True
    assert eval_guard({"compare": {"field": "amount", "op": "<", "value": 100}}, ctx) is False
    assert eval_guard({"compare": {"field": "amount", "op": "==", "value": 500}}, ctx) is True


def test_compare_text_and_in() -> None:
    ctx = GuardContext(field_values={"kind": "hardware"}, field_types={"kind": "text"})
    assert eval_guard({"compare": {"field": "kind", "op": "==", "value": "hardware"}}, ctx) is True
    assert eval_guard({"compare": {"field": "kind", "op": "!=", "value": "food"}}, ctx) is True
    assert eval_guard(
        {"compare": {"field": "kind", "op": "in", "value": ["food", "hardware"]}}, ctx
    ) is True


def test_compare_date_and_bool() -> None:
    ctx = GuardContext(
        field_values={"due": "2026-06-09", "flag": True},
        field_types={"due": "date", "flag": "bool"},
    )
    assert eval_guard({"compare": {"field": "due", "op": ">=", "value": "2026-01-01"}}, ctx) is True
    assert eval_guard({"compare": {"field": "flag", "op": "==", "value": True}}, ctx) is True


def test_compare_missing_field_is_false() -> None:
    ctx = GuardContext(field_values={}, field_types={"amount": "currency"})
    assert eval_guard({"compare": {"field": "amount", "op": ">", "value": 0}}, ctx) is False


def test_compare_wrong_op_for_type_raises() -> None:
    ctx = GuardContext(field_values={"amount": 5}, field_types={"amount": "currency"})
    with pytest.raises(GuardError, match="not allowed for type"):
        eval_guard({"compare": {"field": "amount", "op": "in", "value": [1]}}, ctx)


# --- Kombinatoren -----------------------------------------------------------
def test_and_or_not_combinators() -> None:
    ctx = GuardContext(roles=frozenset({"reviewer"}), deadline_passed=True)
    assert eval_guard({"and": [{"deadlinePassed": True}, {"roleIs": "reviewer"}]}, ctx) is True
    assert eval_guard({"and": [{"deadlinePassed": True}, {"roleIs": "admin"}]}, ctx) is False
    assert eval_guard({"or": [{"roleIs": "admin"}, {"deadlinePassed": True}]}, ctx) is True
    assert eval_guard({"not": {"roleIs": "admin"}}, ctx) is True
    assert eval_guard({"not": [{"roleIs": "reviewer"}]}, ctx) is False


def test_unknown_guard_operator_raises() -> None:
    with pytest.raises(GuardError, match="unknown guard operator"):
        eval_guard({"isAdmin": True}, GuardContext())


def test_multi_key_guard_raises() -> None:
    with pytest.raises(GuardError):
        eval_guard({"roleIs": "x", "deadlinePassed": True}, GuardContext())


def test_not_arity_and_bad_child() -> None:
    with pytest.raises(GuardError):
        eval_guard({"not": [{"deadlinePassed": True}, {"deadlinePassed": True}]}, GuardContext())
    with pytest.raises(GuardError):
        eval_guard({"and": ["notadict"]}, GuardContext())


# --- Validierung (Speicher-Gate) --------------------------------------------
def test_validate_guard_ok() -> None:
    validate_guard(None)
    validate_guard({})
    validate_guard({"and": [{"roleIs": "reviewer"}, {"not": {"deadlinePassed": True}}]})
    validate_guard({"compare": {"field": "amount", "op": ">=", "value": 0}})


def test_validate_guard_rejects_actor_op_on_automatic() -> None:
    # roleIs/isInCommittee nur auf manuellen Übergängen erlaubt.
    validate_guard({"roleIs": "x"}, allow_actor_ops=True)
    with pytest.raises(GuardError, match="only allowed on manual"):
        validate_guard({"roleIs": "x"}, allow_actor_ops=False)
    with pytest.raises(GuardError, match="only allowed on manual"):
        validate_guard({"and": [{"isInCommittee": "g"}]}, allow_actor_ops=False)


def test_validate_guard_rejects_unknown_and_bad_structure() -> None:
    with pytest.raises(GuardError, match="unknown guard operator"):
        validate_guard({"sudo": True})
    with pytest.raises(GuardError):
        validate_guard({"or": []})
    with pytest.raises(GuardError):
        validate_guard({"not": [{"deadlinePassed": True}, {"deadlinePassed": True}]})
    with pytest.raises(GuardError, match="unknown compare operator"):
        validate_guard({"compare": {"field": "x", "op": "~="}})
    with pytest.raises(GuardError, match="requires a list value"):
        validate_guard({"compare": {"field": "x", "op": "in", "value": "notalist"}})


# --- Actions ----------------------------------------------------------------
def test_validate_action_ok() -> None:
    validate_action({"type": "webhook", "webhookId": "w-1"})
    validate_action(
        {"type": "notify", "recipients": [{"kind": "applicant"}, {"kind": "email", "ref": "a@b.c"}]}
    )
    validate_action({"type": "addToNextSession", "gremiumId": "g-1"})
    validate_action({"type": "assignBudget", "budgetId": "b-1"})


def test_validate_action_required_fields() -> None:
    with pytest.raises(GuardError, match="webhookId"):
        validate_action({"type": "webhook"})
    with pytest.raises(GuardError, match="recipients"):
        validate_action({"type": "notify", "recipients": []})
    with pytest.raises(GuardError, match="unknown notify recipient kind"):
        validate_action({"type": "notify", "recipients": [{"kind": "nope"}]})
    with pytest.raises(GuardError, match="requires 'ref'"):
        validate_action({"type": "notify", "recipients": [{"kind": "gremium"}]})
    with pytest.raises(GuardError, match="gremiumId"):
        validate_action({"type": "addToNextSession"})
    with pytest.raises(GuardError, match="budgetId"):
        validate_action({"type": "assignBudget"})


def test_validate_action_rejects_unknown_and_missing() -> None:
    with pytest.raises(GuardError, match="unknown action type"):
        validate_action({"type": "deleteEverything"})
    with pytest.raises(GuardError, match="missing 'type'"):
        validate_action({"group": "gremium"})
    with pytest.raises(GuardError):
        validate_action("notadict")  # type: ignore[arg-type]


def test_whitelists_exact() -> None:
    assert {
        "deadlinePassed", "applicantRoleIs", "applicantCommitteeIs", "budgetIs",
        "budgetFitsApplication", "hasField", "compare", "roleIs", "isInCommittee",
        "and", "or", "not",
    } == GUARD_OPERATORS
    assert {"webhook", "notify", "addToNextSession", "assignBudget"} == ACTION_TYPES
