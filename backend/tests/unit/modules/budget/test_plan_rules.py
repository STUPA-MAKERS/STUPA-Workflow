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


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        ("draft", "resolved", True),
        ("resolved", "approved", True),
        ("approved", "in_force", True),
        ("resolved", "draft", True),
        ("draft", "approved", False),
        ("approved", "draft", False),
        ("in_force", "replaced", False),
        ("in_force", "draft", False),
        ("draft", "draft", False),
    ],
)
def test_move_allowed(current: str, target: str, allowed: bool) -> None:
    """§000792: one step forward, and resolved can go back to draft."""
    assert plan_rules.move_allowed(current, target) is allowed


def test_version_name() -> None:
    assert plan_rules.version_name(0) == "Stammplan"
    assert plan_rules.version_name(2) == "2. Nachtrag"


def test_side_sums_and_balance() -> None:
    """§000795: the income Ansätze equal the expense Ansätze."""
    lines = [("income", D(100)), ("expense", D(60)), ("expense", D(40)), (None, D(7))]
    assert plan_rules.side_sums(lines) == (D(100), D(100))
    assert plan_rules.is_balanced(lines)
    assert not plan_rules.is_balanced([("income", D(1))])
    assert plan_rules.is_balanced([])


def test_children_sum() -> None:
    amounts = {EXP_A: D(30), EXP_B: D(12), EXP_A1: D(99)}
    assert plan_rules.children_sum(EXP, PARENT_OF, amounts) == D(42)
    assert plan_rules.children_sum(EXP_B, PARENT_OF, amounts) == D(0)


def test_raised_ancestors_raises_each_parent_up_to_the_top() -> None:
    """§000794: a sum of children above the parent raises the parent."""
    amounts = {EXP: D(40), EXP_A: D(30), EXP_B: D(10), EXP_A1: D(50)}
    raised = plan_rules.raised_ancestors(EXP_A1, PARENT_OF, amounts, TOP)
    assert raised == {EXP_A: D(50), EXP: D(60)}


def test_raised_ancestors_stops_at_a_parent_that_is_large_enough() -> None:
    amounts = {EXP: D(100), EXP_A: D(30), EXP_A1: D(50)}
    assert plan_rules.raised_ancestors(EXP_A1, PARENT_OF, amounts, TOP) == {EXP_A: D(50)}
    assert plan_rules.raised_ancestors(EXP_A1, PARENT_OF, {EXP_A: D(50), EXP_A1: D(50)}, TOP) == {}


def test_raised_ancestors_of_a_direct_child_and_of_the_top() -> None:
    assert plan_rules.raised_ancestors(EXP, PARENT_OF, {EXP: D(5)}, TOP) == {}
    assert plan_rules.raised_ancestors(TOP, PARENT_OF, {}, TOP) == {}


def test_allocations_from_lines() -> None:
    """§000797: expense Ansätze become allocations, income and missing lines 0."""
    nodes = [
        (TOP, None, None), (INC, TOP, "income"), (EXP, TOP, "expense"),
        (EXP_A, EXP, "expense"), (EXP_B, EXP, "expense"),
    ]
    amounts = {INC: D(70), EXP: D(70), EXP_A: D(50)}
    assert plan_rules.allocations_from_lines(nodes, amounts, TOP) == {
        INC: D(0), EXP: D(70), EXP_A: D(50), EXP_B: D(0), TOP: D(70),
    }


def test_with_plan_fields() -> None:
    forest = [{"id": 1, "children": [{"id": 2, "children": []}]}]
    out = plan_rules.with_plan_fields(forest, {2: "income"}, {1: True})
    assert out == [
        {
            "id": 1, "side": None, "plan_enabled": True,
            "children": [
                {"id": 2, "side": "income", "plan_enabled": False,
                 "children": []}
            ],
        }
    ]
