---
id: "000823"
title: A budget holds the steps of its Haushaltsplan
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_plan_steps_of_a_budget"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_plan_write_needs_the_switch"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_a_plan_input_refuses_unknown_fields_and_blank_names"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_a_name_needs_a_visible_character"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_models.py
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/admin/budgets
---

# A budget holds the steps of its Haushaltsplan

A top-level Kostenstelle with the plan switch on must hold an ordered list of plan steps.
Each step must have a name of 1 to 120 characters with at least one visible character and
can name one Gremium, else 422. The page "Haushalte" must name a name above 120 characters at
its field and must not send it. A person with
`budget.structure` must set the list (`PUT /budgets/{id}/plan-steps`). The list can be
empty and must hold at most 10 steps. A Gremium that does not exist must answer 422
`plan_step_gremium_invalid`. The platform must give no default steps.

Reason: The law of each budget says which body decides its plan and which body approves
it. The VS-Mittel need the decision of the STUPA and the approval of the Präsidium, a
different budget needs different steps.

Test: The test sets the steps of a budget with a Gremium, with a missing Gremium, with a blank
name, with a name of invisible characters only, with more than 10 steps and with the switch off. The component test types a name above 120
characters.
