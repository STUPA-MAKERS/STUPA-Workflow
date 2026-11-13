---
id: "000795"
title: A plan version is balanced before the decision
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_passes_the_steps_of_its_budget"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_budget_without_steps_goes_from_draft_into_force"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_side_sums_and_balance"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
scope:
  - backend/app/modules/budget
---

# A plan version is balanced before the decision

The sum of the income Ansätze must equal the sum of the expense Ansätze when a version
leaves `draft`. The sums use the direct children of the top-level Kostenstelle. An unequal
version must answer 422 `plan_not_balanced`.

Reason: LHO § 106 tells the Studierendenschaft to balance income and expenses in the plan.

Test: The tests pass the first step of an unbalanced version and get 422, and sum the two sides
of example lines.
