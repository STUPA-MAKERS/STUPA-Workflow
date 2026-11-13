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


def test_step_vote_config_and_question() -> None:
    """The vote of a step is secret, simple, refused on a tie and names its plan.

    Rule: §F/finance/budget/000838.
    """
    assert plan_rules.step_vote_config(None) == {
        "options": ["yes", "no", "abstain"],
        "majorityRule": "simple",
        "secret": True,
        "tieBreak": "rejected",
    }
    assert plan_rules.step_vote_config(50)["quorum"] == {"type": "percent", "value": 50}
    assert (
        plan_rules.step_vote_question("VS-Mittel", "2026", 0, "Beschluss")
        == "Haushaltsplan VS-Mittel 2026: Beschluss"
    )
    assert (
        plan_rules.step_vote_question("VS-Mittel", "2026", 2, "Beschluss")
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
    """Each node of the forest gets its side, its switch and the years that plan it.

    Rule: §F/finance/budget/000818.
    """
    forest = [{"id": 1, "children": [{"id": 2, "children": []}]}]
    out = plan_rules.with_plan_fields(forest, {2: "income"}, {1: True}, {1: ["fy"], 2: ["fy"]})
    assert out == [
        {
            "id": 1, "side": None, "plan_enabled": True, "planned_in": ("fy",),
            "children": [
                {"id": 2, "side": "income", "plan_enabled": False, "planned_in": ("fy",),
                 "children": []}
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


def test_is_plain_stammplan() -> None:
    """Only a Stammplan in force without a passed step is a plan of the switch alone.

    Rule: §F/finance/budget/000814.
    """
    assert plan_rules.is_plain_stammplan([(0, "in_force", [])])
    assert not plan_rules.is_plain_stammplan([(0, "in_force", [{"name": "A"}])])
    assert not plan_rules.is_plain_stammplan([(0, "draft", [])])
    assert not plan_rules.is_plain_stammplan([(0, "replaced", []), (1, "in_force", [])])
    assert not plan_rules.is_plain_stammplan([])


def test_allocation_changes() -> None:
    """Only an allocation that differs from its Ansatz is a change, with before and after.

    Rule: §F/finance/budget/000803.
    """
    a, b, c = (uuid.uuid4() for _ in range(3))
    D = Decimal
    assert plan_rules.allocation_changes({a: D(5), b: D(1)}, {a: D(5), b: D(2), c: D(0)}) == {
        b: (D(1), D(2))
    }
