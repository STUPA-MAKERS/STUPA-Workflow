---
id: "000803"
title: The plan switch gives each open fiscal year a Stammplan
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_plan_switch_gives_open_years_a_stammplan"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_preview_of_the_plan_switch"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_allocation_changes"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/plan_router.py
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/admin/budgets
---

# The plan switch gives each open fiscal year a Stammplan

When a person sets the plan switch (000814) of a top-level Kostenstelle to on, the system
must give each open fiscal year of that Kostenstelle that has no Haushaltsplan a Stammplan
in the state `in_force`. The Ansatz of a Kostenstelle without a child must equal its
allocation, and a parent must hold the sum of its children (000794). The Stammplan then
sets the allocations (000797). When that changes an allocation, the request must answer 409
`plan_changes_allocations` unless it confirms the changes (`confirmChanges`).
`GET /budgets/{id}/plan-switch/preview` must name each allocation that changes, with the
amount before and after, and the edit form of the budget must show that list and ask before
it saves. A closed fiscal year must not get a Haushaltsplan.

Reason: A current year needs the plan for a Nachtrag. A closed year does not change. A
parent whose allocation differs from the sum of its children cannot stay as it is in a
plan, so the person must see the new amounts first.

Test: The backend test switches a budget on and reads the plan and the allocations of each year,
with and without the confirmation. The form test turns the switch on and reads the list of
changed allocations.
