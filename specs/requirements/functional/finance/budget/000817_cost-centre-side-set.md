---
id: "000817"
title: The side is set on a direct child of the top level
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_side_goes_to_the_subtree_and_to_a_new_child"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_side_is_refused_off_the_first_level"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_side_cannot_change_below_a_planned_amount"
implementation:
  - backend/app/modules/budget/tree/plans.py
scope:
  - backend/app/modules/budget
---

# The side is set on a direct child of the top level

A person with `budget.structure` must set the side on a direct child of a top-level
Kostenstelle. The platform must give the side to each Kostenstelle below it. A new child
must get the side of its parent. A change of the side must answer 409 `side_in_plan` when a
plan line of that subtree has an Ansatz above 0 €. The plan switch (000814) must answer 422
`plan_side_missing` when a Kostenstelle below the top level has no side.

Reason: A side that changes below a planned amount changes the balance of a decided plan.
