---
id: "000792"
title: A plan version passes the steps of its budget
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_can_enter_force"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_passes_the_steps_of_its_budget"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
scope:
  - backend/app/modules/budget
---

# A plan version passes the steps of its budget

A plan version must have one of the states `draft`, `in_progress`, `in_force` and
`replaced`. A version that leaves `draft` must pass its steps (000824) in their order, one
step at a time, and the platform must keep the time of each passed step. A version must
come into force only after its last step. A version without steps must come into force
from `draft`. A version before `in_force` can move back to `draft`, and the platform must
then clear the passed steps. A different move must answer 409 `plan_state_invalid`.

Reason: The budget says which decisions its plan needs, so the platform has no fixed
order of bodies.
