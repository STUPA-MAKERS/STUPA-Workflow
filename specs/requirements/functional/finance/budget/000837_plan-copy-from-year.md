---
id: "000837"
title: A new plan can copy the plan of another year
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_create_plan_copies_the_plan_in_force_of_another_year"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A new plan can copy the plan of another year

The create of a Haushaltsplan can name a different fiscal year of the same budget
(`copyFromFiscalYearId`). The new Stammplan must then start in `draft` with a copy of the
lines of the version in force of that year: the side (000853), the Ansatz, the Erläuterung,
the Vermerke and the gesperrt amount. Each parent of the copy must hold the sum of its children (000794). A
year without a version in force and a year of a different budget must answer 422
`plan_copy_source_invalid`. For a fiscal year without a plan, the plan page must offer
"Aus Vorjahr übernehmen" beside "Haushaltsplan anlegen" when the fiscal year before it has
a version in force.

Reason: The plan of a year starts from the plan of the year before, and typing each line
again costs time and makes errors.

Test: The backend test creates a plan from a year with a plan in force, from a year without one
and from a year of a different budget. The component test reads where the action shows.
