---
id: "000817"
title: The side is set on a direct child of the top level
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_side_goes_to_the_subtree_and_to_a_new_child"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_side_is_refused_off_the_first_level"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_side_cannot_change_below_a_planned_amount"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_plan_switch_needs_a_top_level_node_with_sides"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_side_of_a_closed_year_does_not_change"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_income_side_takes_the_vermerke_off_the_draft_line"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_key_taken_at_the_same_moment_is_a_conflict"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_vermerk_of_a_decided_plan_keeps_the_side"
implementation:
  - backend/app/modules/budget/tree/plans.py
scope:
  - backend/app/modules/budget
---

# The side is set on a direct child of the top level

A person with `budget.structure` must set the side on a direct child of a top-level
Kostenstelle. The platform must give the side to each Kostenstelle below it. A new child
must get the side of its parent. A different Kostenstelle must answer 422
`side_not_settable`, also when a create request sends a side for it. A change of the side must answer 409 `side_in_plan` when a plan line
of that subtree has an Ansatz above 0 €, and when a line of a version that left `draft` holds a
Vermerk and the new side is income (000816). The plan switch (000814) must answer 422
`plan_side_missing` when a Kostenstelle below the top level has no side.

Reason: A side that changes below a planned amount changes the balance of a decided plan.

Test: The tests set the side on each level, change it below a planned amount and in a closed
year, and turn the plan switch on without sides.
