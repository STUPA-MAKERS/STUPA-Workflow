---
id: "000792"
title: A plan version passes the steps of its budget
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_can_enter_force"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_can_return_to_draft"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_passes_the_steps_of_its_budget"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_budget_without_steps_goes_from_draft_into_force"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_without_a_line_does_not_come_into_force"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_in_force_does_not_come_into_force_again"
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
from `draft`. A version without a line must not leave `draft` and must not come into force,
else 422 `plan_empty`. A
version in `in_progress` can move back to `draft`, and the platform must then clear the
passed steps and end the votes of the steps (000839). A different move must answer 409
`plan_state_invalid`.

Reason: The budget says which decisions its plan needs, so the platform has no fixed
order of bodies. A plan without a line would set each allocation of the year to 0 €.

Test: The tests move a version through each state, with steps and without, and try each move
that is not allowed.
