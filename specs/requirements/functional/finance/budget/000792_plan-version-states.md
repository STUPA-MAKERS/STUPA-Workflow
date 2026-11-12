---
id: "000792"
title: A plan version moves through five states
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_move_allowed"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_state_moves_and_balance"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
scope:
  - backend/app/modules/budget
---

# A plan version moves through five states

A plan version must have one of the states `draft`, `resolved`, `approved`, `in_force` and
`replaced`. A version must move only one step forward in this order. A version in `resolved`
can also move back to `draft`. A different move must answer 409 `plan_state_invalid`.

Reason: The STUPA decides the plan, then the Präsidium approves it, then it applies.
