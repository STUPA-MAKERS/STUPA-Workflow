---
id: "000825"
title: A person records a passed step
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_passes_the_steps_of_its_budget"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_step_with_a_vote_is_not_recorded_by_hand"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_router.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A person records a passed step

A person with `budget.structure` must record the next step of a version as passed
(`POST /budget-plan-versions/{id}/steps/next`). The first step must answer 422
`plan_not_balanced` for a version that is not balanced (000795). A step with a vote that is
not cancelled must answer 409 `plan_step_has_vote`, and the plan page must not offer the
record for it. The record must write an audit entry with the name of the step and its
Gremium. The plan page must ask for a confirmation before the record (000840).

Reason: A decision can happen outside the platform, for example the approval of the
Präsidium, so a person must be able to record it. A step that a vote decides must not get
a second result by hand.

Test: The tests record each step of a version, the first step of an unbalanced version, and a
step that has a vote.
