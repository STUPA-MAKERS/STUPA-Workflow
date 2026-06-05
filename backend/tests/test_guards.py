"""TDD: pure Guard-/Action-Evaluator (flows §9.2). Branch-Coverage-Ziel 100 %."""

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


def test_role_is() -> None:
    ctx = GuardContext(roles=frozenset({"applicant"}))
    assert eval_guard({"roleIs": "applicant"}, ctx) is True
    assert eval_guard({"roleIs": "admin"}, ctx) is False


def test_permission_is() -> None:
    ctx = GuardContext(permissions=frozenset({"application.manage"}))
    assert eval_guard({"permissionIs": "application.manage"}, ctx) is True
    assert eval_guard({"permissionIs": "vote.cast"}, ctx) is False


def test_fields_complete() -> None:
    assert eval_guard({"fieldsComplete": True}, GuardContext(fields_complete=True)) is True
    assert eval_guard({"fieldsComplete": True}, GuardContext(fields_complete=False)) is False
    assert eval_guard({"fieldsComplete": False}, GuardContext(fields_complete=False)) is True


def test_vote_result() -> None:
    ctx = GuardContext(vote_result="passed")
    assert eval_guard({"voteResult": "passed"}, ctx) is True
    assert eval_guard({"voteResult": "rejected"}, ctx) is False
    assert eval_guard({"voteResult": "tie"}, GuardContext(vote_result="tie")) is True
    assert eval_guard({"voteResult": "passed"}, GuardContext()) is False


def test_vote_result_invalid_value_raises() -> None:
    with pytest.raises(GuardError):
        eval_guard({"voteResult": "maybe"}, GuardContext())


def test_deadline_passed() -> None:
    assert eval_guard({"deadlinePassed": True}, GuardContext(deadline_passed=True)) is True
    assert eval_guard({"deadlinePassed": True}, GuardContext(deadline_passed=False)) is False


def test_manual() -> None:
    assert eval_guard({"manual": True}, GuardContext(manual=True)) is True
    assert eval_guard({"manual": True}, GuardContext(manual=False)) is False


def test_and_or_not_combinators() -> None:
    ctx = GuardContext(roles=frozenset({"applicant"}), fields_complete=True)
    assert eval_guard({"and": [{"fieldsComplete": True}, {"roleIs": "applicant"}]}, ctx) is True
    assert eval_guard({"and": [{"fieldsComplete": True}, {"roleIs": "admin"}]}, ctx) is False
    assert eval_guard({"or": [{"roleIs": "admin"}, {"fieldsComplete": True}]}, ctx) is True
    assert eval_guard({"not": {"roleIs": "admin"}}, ctx) is True
    assert eval_guard({"not": [{"roleIs": "applicant"}]}, ctx) is False


def test_spec_example_guard() -> None:
    # flows §9.2 / data-model §5.2 Beispiel
    ctx = GuardContext(roles=frozenset({"applicant"}), fields_complete=True)
    guard = {"and": [{"fieldsComplete": True}, {"roleIs": "applicant"}]}
    assert eval_guard(guard, ctx) is True


def test_unknown_guard_operator_raises() -> None:
    with pytest.raises(GuardError, match="unknown guard operator"):
        eval_guard({"isAdmin": True}, GuardContext())


def test_multi_key_guard_raises() -> None:
    with pytest.raises(GuardError):
        eval_guard({"roleIs": "x", "manual": True}, GuardContext())


def test_not_arity_and_bad_child() -> None:
    with pytest.raises(GuardError):
        eval_guard({"not": [{"manual": True}, {"manual": True}]}, GuardContext())
    with pytest.raises(GuardError):
        eval_guard({"and": ["notadict"]}, GuardContext())


def test_validate_guard_ok() -> None:
    validate_guard(None)
    validate_guard({})
    validate_guard({"and": [{"roleIs": "applicant"}, {"not": {"manual": True}}]})


def test_validate_guard_rejects_unknown_operator() -> None:
    with pytest.raises(GuardError, match="unknown guard operator"):
        validate_guard({"sudo": True})
    with pytest.raises(GuardError):
        validate_guard({"or": []})
    with pytest.raises(GuardError):
        validate_guard({"not": [{"manual": True}, {"manual": True}]})
    with pytest.raises(GuardError):
        validate_guard({"voteResult": "nope"})
    with pytest.raises(GuardError):
        validate_guard({"roleIs": "x", "manual": True})


def test_validate_action_ok_all_types() -> None:
    for t in ACTION_TYPES:
        validate_action({"type": t})


def test_validate_action_rejects_unknown_and_missing() -> None:
    with pytest.raises(GuardError, match="unknown action type"):
        validate_action({"type": "deleteEverything"})
    with pytest.raises(GuardError, match="missing 'type'"):
        validate_action({"group": "gremium"})
    with pytest.raises(GuardError):
        validate_action("notadict")  # type: ignore[arg-type]


def test_whitelists_exact() -> None:
    assert {
        "roleIs", "permissionIs", "fieldsComplete", "voteResult",
        "deadlinePassed", "manual", "and", "or", "not",
    } == GUARD_OPERATORS
    assert {
        "notify", "webhook", "exportPdf", "setEditLock",
        "budgetReserve", "budgetBook", "openVote", "requeue",
    } == ACTION_TYPES
