"""Pure rules of the Haushaltsplan: states, balance, line sums and allocations.

No function here touches the database. The ops class `tree.plans.PlanOps` reads the
rows, asks these functions and writes the result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

PlanState = Literal["draft", "in_progress", "in_force", "replaced"]
#: The states a person can ask for. The platform sets the other two: `in_progress`
#: with the first passed step, `replaced` when a later version comes into force.
PlanTarget = Literal["draft", "in_force"]
Side = Literal["income", "expense"]

_ZERO = Decimal(0)

#: The largest value of ``Numeric(12, 2)``: a larger Ansatz gives 422, not a 500 from
#: the database.
MAX_AMOUNT = Decimal("9999999999.99")

#: The states before ``in_force``. A plan has at most one version in them.
OPEN_STATES: tuple[str, ...] = ("draft", "in_progress")

#: The largest number of steps of one budget.
MAX_STEPS = 10


def next_step(steps: Sequence[Mapping[str, Any]]) -> int | None:
    """Return the index of the first step that is not passed, or `None`."""
    return next((i for i, step in enumerate(steps) if step.get("passedAt") is None), None)


def can_enter_force(state: str, steps: Sequence[Mapping[str, Any]]) -> bool:
    """Say if a version can come into force.

    A draft comes into force when its budget has no steps: `steps` then holds the
    steps of the budget. A version in progress comes into force after its last step.
    """
    return (state == "draft" and not steps) or (
        state == "in_progress" and next_step(steps) is None
    )


def can_return_to_draft(state: str) -> bool:
    """Say if a version can move back to draft: only one that passes its steps."""
    return state == "in_progress"


def step_snapshot(steps: Sequence[tuple[str, UUID | None]]) -> list[dict[str, Any]]:
    """Return the steps of a budget as the record a version keeps, none passed."""
    return [
        {"name": name, "gremiumId": str(gremium_id) if gremium_id else None, "passedAt": None}
        for name, gremium_id in steps
    ]


def with_step_passed(
    steps: Sequence[Mapping[str, Any]], index: int, passed_at: str
) -> list[dict[str, Any]]:
    """Return `steps` with the step at `index` passed at `passed_at`."""
    return [
        {**step, "passedAt": passed_at} if i == index else dict(step)
        for i, step in enumerate(steps)
    ]


def with_step_vote(
    steps: Sequence[Mapping[str, Any]], index: int, vote_id: str
) -> list[dict[str, Any]]:
    """Return `steps` with the vote of the step at `index`."""
    return [
        {**step, "voteId": vote_id} if i == index else dict(step) for i, step in enumerate(steps)
    ]


def vote_decides_next(steps: Sequence[Mapping[str, Any]], vote_id: str) -> bool:
    """Say if `vote_id` is the vote of the next step that is not passed."""
    index = next_step(steps)
    return index is not None and steps[index].get("voteId") == vote_id


#: The options of the vote of a step: the Gremium accepts or refuses the plan.
STEP_VOTE_OPTIONS: tuple[str, ...] = ("yes", "no", "abstain")


def step_vote_config(quorum_percent: int | None) -> dict[str, Any]:
    """Return the config of the vote of a step, with the quorum of its Gremium."""
    return {
        "options": list(STEP_VOTE_OPTIONS),
        "majorityRule": "simple",
        "secret": True,
        "tieBreak": "rejected",
        **(
            {}
            if quorum_percent is None
            else {"quorum": {"type": "percent", "value": quorum_percent}}
        ),
    }


def step_vote_question(budget: str, year: str, version: str, step: str) -> str:
    """Return the question of the vote of a step, such as `Haushaltsplan VS 2026 ...`."""
    return f"Haushaltsplan {budget} {year}, {version}: {step}"


def version_name(number: int) -> str:
    """Name a version for a message: the Stammplan, or the Nachtrag with its number."""
    return "Stammplan" if number == 0 else f"{number}. Nachtrag"


def side_sums(lines: Sequence[tuple[str | None, Decimal]]) -> tuple[Decimal, Decimal]:
    """Sum the Ansätze of `(side, amount)` rows as `(income, expense)`.

    The caller passes the direct children of the top-level cost center. A row
    without a side counts on neither side.
    """
    return (
        sum((amount for side, amount in lines if side == "income"), _ZERO),
        sum((amount for side, amount in lines if side == "expense"), _ZERO),
    )


def is_balanced(lines: Sequence[tuple[str | None, Decimal]]) -> bool:
    """Say if the income Ansätze equal the expense Ansätze."""
    income, expense = side_sums(lines)
    return income == expense


def ancestors_below(
    node_id: UUID, parent_of: Mapping[UUID, UUID | None], top_id: UUID
) -> tuple[UUID, ...]:
    """Return the ancestors of `node_id` below `top_id`, nearest first.

    The top level has no plan line, so the walk stops below it.
    """
    parent = parent_of.get(node_id)
    if parent is None or parent == top_id:
        return ()
    return (parent, *ancestors_below(parent, parent_of, top_id))


def summed_amounts(
    parent_of: Mapping[UUID, UUID | None],
    amounts: Mapping[UUID, Decimal],
) -> dict[UUID, Decimal]:
    """Return the Ansatz of each line when every parent holds the sum of its children.

    `amounts` holds the Ansatz of each cost center with a line. A cost center with a
    child that has a line gets the sum of the Ansätze of those children, on every
    level, so a parent can stand neither above nor below its children. A cost center
    without such a child keeps the Ansatz a person typed.
    """
    below = {
        parent: tuple(n for n, above in parent_of.items() if above == parent and n in amounts)
        for parent in amounts
    }

    def total(node: UUID) -> Decimal:
        children = below[node]
        return sum((total(child) for child in children), _ZERO) if children else amounts[node]

    return {node: total(node) for node in amounts}


def is_plain_stammplan(versions: Sequence[tuple[int, str, Sequence[Any]]]) -> bool:
    """Say if a plan holds nothing but a Stammplan in force that passed no step.

    `versions` holds `(number, state, steps)` of each version. Such a plan says the
    same as the allocations, so the plan switch can go off and take it along.
    """
    return len(versions) == 1 and all(
        number == 0 and state == "in_force" and not steps for number, state, steps in versions
    )


def first_child_of(
    node_id: UUID, parent_of: Mapping[UUID, UUID | None], with_line: Sequence[UUID]
) -> UUID | None:
    """Return the parent whose first child line `node_id` gets, or `None`.

    A cost center gets the first child line of its parent when the parent has a line
    and neither the cost center nor one of its siblings has one. The parent then stops
    to hold an Ansatz of its own, so the line of the child takes that Ansatz over.
    """
    parent = parent_of.get(node_id)
    taken = any(n in with_line for n, above in parent_of.items() if above == parent)
    return parent if parent is not None and parent in with_line and not taken else None


def allocation_changes(
    current: Mapping[UUID, Decimal], target: Mapping[UUID, Decimal]
) -> dict[UUID, tuple[Decimal, Decimal]]:
    """Return `(before, after)` for each cost center whose allocation the plan changes."""
    return {
        node: (current.get(node, _ZERO), after)
        for node, after in target.items()
        if current.get(node, _ZERO) != after
    }


def allocations_from_lines(
    nodes: Sequence[tuple[UUID, UUID | None, str | None]],
    amounts: Mapping[UUID, Decimal],
    top_id: UUID,
) -> dict[UUID, Decimal]:
    """Return the allocation of each cost center of a plan that comes into force.

    `nodes` holds `(id, parent_id, side)` of the top-level node and of every node
    below it. An expense node gets its Ansatz. An income node and a node without a
    line get 0, because an allocation is money to spend. The top-level node gets the
    sum of the expense Ansätze of its direct children.
    """
    below = {
        node: (amounts.get(node, _ZERO) if side == "expense" else _ZERO)
        for node, _parent, side in nodes
        if node != top_id
    }
    top_sum = sum(
        (below[node] for node, parent, _side in nodes if parent == top_id),
        _ZERO,
    )
    return {**below, top_id: top_sum}


def with_plan_fields(
    forest: Sequence[dict[str, Any]],
    side_of: Mapping[object, str | None],
    enabled_of: Mapping[object, bool],
    planned_in: Mapping[object, Sequence[object]],
) -> list[dict[str, Any]]:
    """Add `side`, `plan_enabled` and `planned_in` to each node dict of a forest.

    `planned_in` holds, for a top-level node, the fiscal years with a version in
    force, and for a node below it the fiscal years whose version in force has a line
    for the node.
    """
    return [
        {
            **node,
            "side": side_of.get(node["id"]),
            "plan_enabled": enabled_of.get(node["id"], False),
            "planned_in": tuple(planned_in.get(node["id"], ())),
            "children": with_plan_fields(node["children"], side_of, enabled_of, planned_in),
        }
        for node in forest
    ]
