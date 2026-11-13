---
id: "000855"
title: A person with an own permission sets the state of a plan by hand
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_state_by_hand_moves_forwards_and_backwards"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_state_by_hand_checks_the_step_and_the_draft"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_only_the_newest_version_takes_a_state_by_hand"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_state_by_hand_ends_the_open_vote_of_the_version"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_the_state_by_hand_needs_its_own_permission"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_steps_by_hand"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_manual_passed"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/plan_router.py
  - backend/app/shared/permissions.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget/plan
---

# A person with an own permission sets the state of a plan by hand

The permission `budget.plan.set_state` ("Zustand des Haushaltsplans setzen") must let a
person set the state of the newest version of a Haushaltsplan by hand: the draft, each step
of the version, and the state in force, forwards and backwards
(`PUT /budget-plan-versions/{id}/state` with `state`, `step` and `reason`).
`budget.structure` alone must not give this action. The migration gives the permission to
the role `admin` only. No MCP tool and no OAuth scope must carry it.

The platform must record the steps before the chosen state as passed by hand (`byHand`),
must clear the steps after it, and must end the open votes of the version (000839). An
older version must answer 409 `plan_state_invalid`, and so must a request that changes
nothing. A step that the version does not have, and a step beside the draft or the state
in force, must answer 422 `plan_step_invalid`.

The checks of a version must stay: a version without a line (000792), with a Titel without
a side (000853) or with an unbalanced plan (000795) must not leave the draft, and a closed
fiscal year must refuse the change (000801). A version that comes into force by hand must
set the allocations (000797) and must replace the version in force before it (000796). A
version in force that goes back by hand must keep the allocations, and the version that it
replaced must stay replaced.

The request must hold a reason as text. The audit entry (`budget_plan_state_set`) must
name the Haushalt, the year, the version, the state before and after, the step, the
reason, the actor and each allocation that changed (000802).

The plan page must offer "Zustand setzen" in the menu of the newest version to a person
with the permission. The dialog must take the state, the step and the reason, must name
that a version in force sets the allocations, and must save only with a reason.

Reason: The plans of the years that ran before the platform have their decisions on
paper. A person with an own permission records their state, and the audit log keeps who
did it and why. The right to write a plan must not be the right to put it in force without
its steps.

Test: The backend tests set each state forwards and backwards, read the steps, the
allocations and the audit entries, send a wrong step and an older version, leave the draft
without a side, and end an open vote. The router test calls the route with
`budget.structure` only. The page tests open the dialog with and without the permission
and save a state with a reason.
