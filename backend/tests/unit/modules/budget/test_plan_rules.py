"""Pure rules of the Haushaltsplan: states, balance, raised parents, allocations."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.budget import plan_rules

D = Decimal
TOP, INC, EXP, EXP_A, EXP_B, EXP_A1 = (uuid.uuid4() for _ in range(6))
PARENT_OF: dict[uuid.UUID, uuid.UUID | None] = {
    TOP: None, INC: TOP, EXP: TOP, EXP_A: EXP, EXP_B: EXP, EXP_A1: EXP_A,
}


_OPEN = {"name": "Beschluss", "gremiumId": None, "passedAt": None}
_DONE = {"name": "Beschluss", "gremiumId": None, "passedAt": "2026-11-12T10:00:00+00:00"}


def test_next_step() -> None:
    assert plan_rules.next_step([]) is None
    assert plan_rules.next_step([_DONE, _OPEN, _OPEN]) == 1
    assert plan_rules.next_step([_DONE]) is None


@pytest.mark.parametrize(
    ("state", "steps", "allowed"),
    [
        ("draft", [], True),
        ("draft", [_OPEN], False),
        ("in_progress", [_DONE], True),
        ("in_progress", [_DONE, _OPEN], False),
        ("in_force", [], False),
        ("replaced", [_DONE], False),
    ],
)
def test_can_enter_force(state: str, steps: list[dict[str, object]], allowed: bool) -> None:
    """§F/finance/budget/000792: into force after the last step, or from draft without steps."""
    assert plan_rules.can_enter_force(state, steps) is allowed


def test_can_return_to_draft() -> None:
    """§F/finance/budget/000792: only a version that passes its steps moves back to draft."""
    assert [plan_rules.can_return_to_draft(s) for s in ("in_progress", "draft", "in_force")] == [
        True, False, False,
    ]


def test_step_snapshot_and_pass() -> None:
    """A version keeps the steps of its budget and the time of each one.

    Rule: §F/finance/budget/000824.
    """
    gremium = uuid.uuid4()
    steps = plan_rules.step_snapshot([("Beschluss", gremium), ("Genehmigung", None)])
    assert steps == [
        {"name": "Beschluss", "gremiumId": str(gremium), "passedAt": None},
        {"name": "Genehmigung", "gremiumId": None, "passedAt": None},
    ]
    passed = plan_rules.with_step_passed(steps, 0, "2026-11-12T10:00:00+00:00")
    assert [s["passedAt"] for s in passed] == ["2026-11-12T10:00:00+00:00", None]
    assert steps[0]["passedAt"] is None


def test_step_vote() -> None:
    """A step keeps its vote, and only the vote of the next step decides.

    Rule: §F/finance/budget/000826.
    """
    steps = plan_rules.step_snapshot([("Beschluss", uuid.uuid4()), ("Genehmigung", None)])
    voted = plan_rules.with_step_vote(steps, 0, "v1")
    assert [s.get("voteId") for s in voted] == ["v1", None]
    assert "voteId" not in steps[0]
    assert plan_rules.vote_decides_next(voted, "v1")
    assert not plan_rules.vote_decides_next(voted, "v2")
    passed = plan_rules.with_step_passed(voted, 0, "2026-11-12T10:00:00+00:00")
    assert passed[0]["voteId"] == "v1"
    assert not plan_rules.vote_decides_next(passed, "v1")
    assert not plan_rules.vote_decides_next([], "v1")


def test_step_request_and_title() -> None:
    """A version waits for the Gremium of its next step after the request.

    Rule: §F/finance/budget/000838.
    """
    gremium = uuid.uuid4()
    steps = plan_rules.step_snapshot([("Vorberatung", None), ("Beschluss", gremium)])
    assert plan_rules.waiting_gremium("in_progress", steps) is None
    first = plan_rules.with_step_requested(steps, 0, "2026-11-13T10:00:00+00:00")
    assert plan_rules.waiting_gremium("in_progress", first) is None
    assert "requestedAt" not in steps[0]
    passed = plan_rules.with_step_passed(steps, 0, "2026-11-13T10:00:00+00:00")
    asked = plan_rules.with_step_requested(passed, 1, "2026-11-13T11:00:00+00:00")
    assert plan_rules.waiting_gremium("in_progress", passed) is None
    assert plan_rules.waiting_gremium("in_progress", asked) == str(gremium)
    assert plan_rules.waiting_gremium("draft", asked) is None
    assert plan_rules.waiting_gremium("in_force", asked) is None
    done = plan_rules.with_step_passed(asked, 1, "2026-11-13T12:00:00+00:00")
    assert plan_rules.waiting_gremium("in_progress", done) is None
    assert (
        plan_rules.step_title("VS-Mittel", "2026", 0, "Beschluss")
        == "Haushaltsplan VS-Mittel 2026: Beschluss"
    )
    assert (
        plan_rules.step_title("VS-Mittel", "2026", 2, "Beschluss")
        == "Haushaltsplan VS-Mittel 2026, 2. Nachtrag: Beschluss"
    )


def test_version_name() -> None:
    """§F/finance/budget/000852: the first version is named Haushaltsplan."""
    assert plan_rules.version_name(0) == "Haushaltsplan"
    assert plan_rules.version_name(2) == "2. Nachtrag"


def test_side_sums_and_balance() -> None:
    """§F/finance/budget/000795: the income Ansätze equal the expense Ansätze."""
    lines = [("income", D(100)), ("expense", D(60)), ("expense", D(40)), (None, D(7))]
    assert plan_rules.side_sums(lines) == (D(100), D(100))
    assert plan_rules.is_balanced(lines)
    assert not plan_rules.is_balanced([("income", D(1))])
    assert plan_rules.is_balanced([])


def test_summed_amounts_give_each_parent_the_sum_of_its_children() -> None:
    """§F/finance/budget/000794: a parent holds the sum of its children on every level."""
    amounts = {EXP: D(40), EXP_A: D(30), EXP_B: D(10), EXP_A1: D(50)}
    assert plan_rules.summed_amounts(PARENT_OF, amounts) == {
        EXP: D(60), EXP_A: D(50), EXP_B: D(10), EXP_A1: D(50),
    }
    lower = {EXP: D(100), EXP_A: D(80), EXP_B: D(10), EXP_A1: D(5)}
    assert plan_rules.summed_amounts(PARENT_OF, lower)[EXP] == D(15)


def test_summed_amounts_keep_a_cost_centre_without_a_child_line() -> None:
    """A parent whose children have no line keeps the Ansatz a person typed."""
    amounts = {EXP: D(70), EXP_A: D(50)}
    assert plan_rules.summed_amounts(PARENT_OF, amounts) == {EXP: D(50), EXP_A: D(50)}
    assert plan_rules.summed_amounts(PARENT_OF, {EXP_A: D(50)}) == {EXP_A: D(50)}
    assert plan_rules.summed_amounts(PARENT_OF, {}) == {}


def test_allocations_from_lines() -> None:
    """§F/finance/budget/000797: expense Ansätze become allocations, income and missing lines 0."""
    nodes = [
        (TOP, None, None), (INC, TOP, "income"), (EXP, TOP, "expense"),
        (EXP_A, EXP, "expense"), (EXP_B, EXP, "expense"),
    ]
    amounts = {INC: D(70), EXP: D(70), EXP_A: D(50)}
    assert plan_rules.allocations_from_lines(nodes, amounts, TOP) == {
        INC: D(0), EXP: D(70), EXP_A: D(50), EXP_B: D(0), TOP: D(70),
    }


def test_with_plan_fields() -> None:
    """Each node of the forest gets its switch and the years that plan it.

    Rule: §F/finance/budget/000818.
    """
    forest = [{"id": 1, "children": [{"id": 2, "children": []}]}]
    out = plan_rules.with_plan_fields(forest, {1: True}, {1: ["fy"], 2: ["fy"]})
    assert out == [
        {
            "id": 1, "plan_enabled": True, "planned_in": ("fy",),
            "children": [
                {"id": 2, "plan_enabled": False, "planned_in": ("fy",), "children": []}
            ],
        }
    ]


def test_first_child_of() -> None:
    top, parent, a, b = (uuid.uuid4() for _ in range(4))
    parent_of = {top: None, parent: top, a: parent, b: parent}
    assert plan_rules.first_child_of(a, parent_of, [parent]) == parent
    assert plan_rules.first_child_of(a, parent_of, [parent, b]) is None
    assert plan_rules.first_child_of(a, parent_of, [parent, a]) is None
    assert plan_rules.first_child_of(a, parent_of, []) is None
    assert plan_rules.first_child_of(top, parent_of, []) is None


def test_is_plain_draft() -> None:
    """Only a plan with nothing but its first version in draft goes with the switch.

    Rule: §F/finance/budget/000814.
    """
    assert plan_rules.is_plain_draft([(0, "draft")])
    assert not plan_rules.is_plain_draft([(0, "in_force")])
    assert not plan_rules.is_plain_draft([(0, "in_progress")])
    assert not plan_rules.is_plain_draft([(0, "replaced"), (1, "draft")])
    assert not plan_rules.is_plain_draft([])


def test_the_side_of_a_node_is_the_side_of_its_titel() -> None:
    """§F/finance/budget/000853: a line below a Titel has the side of the Titel."""
    sides = {INC: "income", EXP: "expense"}
    assert plan_rules.titel_of(PARENT_OF, TOP, EXP_A1) == EXP
    assert plan_rules.titel_of(PARENT_OF, TOP, INC) == INC
    assert plan_rules.titel_of(PARENT_OF, TOP, TOP) is None
    assert plan_rules.titel_of(PARENT_OF, TOP, uuid.uuid4()) is None
    assert plan_rules.side_of(PARENT_OF, TOP, sides, EXP_A1) == "expense"
    assert plan_rules.side_of(PARENT_OF, TOP, sides, TOP) is None
    assert plan_rules.side_of(PARENT_OF, TOP, {INC: "income"}, EXP_B) is None
    assert plan_rules.sides_of(PARENT_OF, TOP, {INC: "income"}) == {
        TOP: None, INC: "income", EXP: None, EXP_A: None, EXP_B: None, EXP_A1: None,
    }


def test_steps_by_hand() -> None:
    """§F/finance/budget/000855: the steps before the state are passed, the others open."""
    voted = {**_DONE, "voteId": "v1"}
    waiting = {**_OPEN, "voteId": "v2"}
    out = plan_rules.steps_by_hand([voted, waiting, waiting], 2, "now")
    assert out == [
        voted,
        {**_OPEN, "voteId": "v2", "passedAt": "now", "byHand": True},
        _OPEN,
    ]
    assert plan_rules.steps_by_hand([voted, _DONE], 0, "now") == [_OPEN, _OPEN]
    assert plan_rules.steps_by_hand([], 0, "now") == []


@pytest.mark.parametrize(
    ("state", "step", "count", "passed"),
    [
        ("draft", None, 3, 0),
        ("draft", 0, 3, None),
        ("in_force", None, 3, 3),
        ("in_force", None, 0, 0),
        ("in_force", 2, 3, None),
        ("in_progress", 0, 3, 0),
        ("in_progress", 2, 3, 2),
        ("in_progress", 3, 3, None),
        ("in_progress", None, 3, None),
        ("in_progress", 0, 0, None),
    ],
)
def test_manual_passed(
    state: plan_rules.ManualState, step: int | None, count: int, passed: int | None
) -> None:
    """§F/finance/budget/000855: a state by hand names a step only for `in_progress`."""
    assert plan_rules.manual_passed(state, step, count) == passed


def test_allocation_changes() -> None:
    """Only an allocation that differs from its Ansatz is a change, with before and after.

    Rule: §F/finance/budget/000803.
    """
    a, b, c = (uuid.uuid4() for _ in range(3))
    D = Decimal
    assert plan_rules.allocation_changes({a: D(5), b: D(1)}, {a: D(5), b: D(2), c: D(0)}) == {
        b: (D(1), D(2))
    }
