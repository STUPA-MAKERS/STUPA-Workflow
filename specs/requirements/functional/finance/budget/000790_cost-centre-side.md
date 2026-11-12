---
id: "000790"
title: A Kostenstelle below the top level has a side
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_side_goes_to_the_subtree_and_to_a_new_child"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/tree/nodes.py
scope:
  - backend/app/modules/budget
---

# A Kostenstelle below the top level has a side

A Kostenstelle below a top-level Kostenstelle with the plan switch on (000814) must have the
side `income` or `expense`. A child must
have the side of its parent. A top-level Kostenstelle must not have a side.

Reason: LHO § 15 tells the Studierendenschaft to plan income and expenses apart and in full.
