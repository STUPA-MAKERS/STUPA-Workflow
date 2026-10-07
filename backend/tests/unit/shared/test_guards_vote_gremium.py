"""Flow variant B in the pure guard evaluator: the new guards, actions and recipients."""

from __future__ import annotations

import pytest

from app.shared.guards import (
    GUARD_ACTOR_OPERATORS,
    GuardContext,
    GuardError,
    budget_ids_of_action,
    eval_guard,
    validate_action,
    validate_guard,
)


def test_is_in_vote_gremium_needs_a_member_of_the_snapshot() -> None:
    member = GuardContext(vote_gremium_id="g-1", actor_committees=frozenset({"g-1"}))
    other = GuardContext(vote_gremium_id="g-1", actor_committees=frozenset({"g-2"}))
    no_vote = GuardContext(vote_gremium_id=None, actor_committees=frozenset({"g-1"}))
    assert eval_guard({"isInVoteGremium": True}, member) is True
    assert eval_guard({"isInVoteGremium": True}, other) is False
    # Fail closed: without a vote Gremium nobody is a member of it.
    assert eval_guard({"isInVoteGremium": True}, no_vote) is False
    assert eval_guard({"isInVoteGremium": False}, other) is True


def test_is_in_vote_gremium_is_an_actor_gate() -> None:
    assert "isInVoteGremium" in GUARD_ACTOR_OPERATORS
    validate_guard({"isInVoteGremium": True})
    with pytest.raises(GuardError, match="manual"):
        validate_guard({"isInVoteGremium": True}, allow_actor_ops=False)
    with pytest.raises(GuardError, match="boolean"):
        validate_guard({"isInVoteGremium": "g-1"})


def test_budget_has_decision_gremium_is_a_condition() -> None:
    yes = GuardContext(budget_has_decision_gremium=True)
    no = GuardContext()
    assert eval_guard({"budgetHasDecisionGremium": True}, yes) is True
    assert eval_guard({"budgetHasDecisionGremium": True}, no) is False
    assert eval_guard({"budgetHasDecisionGremium": False}, no) is True
    validate_guard({"budgetHasDecisionGremium": False}, allow_actor_ops=False)
    with pytest.raises(GuardError, match="boolean"):
        validate_guard({"budgetHasDecisionGremium": "yes"})


def test_add_to_next_session_gremium_is_optional() -> None:
    validate_action({"type": "addToNextSession"})
    validate_action({"type": "addToNextSession", "gremiumId": "g-1"})
    with pytest.raises(GuardError, match="non-empty"):
        validate_action({"type": "addToNextSession", "gremiumId": ""})
    with pytest.raises(GuardError, match="non-empty"):
        validate_action({"type": "addToNextSession", "gremiumId": 3})


def test_assign_from_applicant_gremium_parent_is_optional() -> None:
    validate_action({"type": "assignBudgetFromApplicantGremium"})
    validate_action({"type": "assignBudgetFromApplicantGremium", "parentId": "b-1"})
    with pytest.raises(GuardError, match="parentId"):
        validate_action({"type": "assignBudgetFromApplicantGremium", "parentId": ""})


@pytest.mark.parametrize(
    ("action", "match"),
    [
        ({"type": "assignBudgetFromMap", "map": {"a": "b-1"}}, "field"),
        ({"type": "assignBudgetFromMap", "field": "", "map": {"a": "b-1"}}, "field"),
        ({"type": "assignBudgetFromMap", "field": "f"}, "map"),
        ({"type": "assignBudgetFromMap", "field": "f", "map": {}}, "map"),
        ({"type": "assignBudgetFromMap", "field": "f", "map": ["b-1"]}, "map"),
        ({"type": "assignBudgetFromMap", "field": "f", "map": {"": "b-1"}}, "map"),
        ({"type": "assignBudgetFromMap", "field": "f", "map": {"a": ""}}, "map"),
        ({"type": "assignBudgetFromMap", "field": "f", "map": {"a": 1}}, "map"),
    ],
)
def test_assign_from_map_shape(action: dict, match: str) -> None:
    with pytest.raises(GuardError, match=match):
        validate_action(action)


def test_assign_from_map_valid() -> None:
    validate_action({"type": "assignBudgetFromMap", "field": "f", "map": {"a": "b-1"}})


def test_new_recipient_kinds_take_no_ref() -> None:
    validate_action(
        {"type": "notify", "recipients": [{"kind": "voteGremium"}, {"kind": "budgetGremium"}]}
    )
    for kind in ("voteGremium", "budgetGremium", "applicant"):
        with pytest.raises(GuardError, match="must not have 'ref'"):
            validate_action({"type": "notify", "recipients": [{"kind": kind, "ref": "x"}]})


def test_budget_ids_of_action() -> None:
    assert budget_ids_of_action(
        {"type": "assignBudgetFromMap", "field": "f", "map": {"a": "b-1", "c": "b-2"}}
    ) == ["b-1", "b-2"]
    assert budget_ids_of_action({"type": "assignBudgetFromMap", "map": "nope"}) == []
    assert budget_ids_of_action(
        {"type": "assignBudgetFromApplicantGremium", "parentId": "b-3"}
    ) == ["b-3"]
    assert budget_ids_of_action({"type": "assignBudgetFromApplicantGremium"}) == []
    assert budget_ids_of_action({"type": "assignBudget", "budgetId": "b-4"}) == []
