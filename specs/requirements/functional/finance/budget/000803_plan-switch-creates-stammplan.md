---
id: "000803"
title: A new fiscal year of a Haushalt with the plan switch gets its draft at once
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_plan_switch_gives_open_years_a_draft"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_new_fiscal_year_gets_a_draft"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/plan_router.py
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/admin/budgets
---

# A new fiscal year of a Haushalt with the plan switch gets its draft at once

A fiscal year that a person creates for a Haushalt with the plan switch on (000814) must get
its Haushaltsplan with one version in `draft` at once (000854). The draft must copy the
lines, the Ansätze, the Vermerke and the sides of the version in force of the latest fiscal
year before it that has one (000837). Without such a year the draft must hold a line for
each node with an Ansatz of 0 € and no side.

Reason: A current year needs the plan for a Nachtrag. The plan of a year starts from the
plan of the year before.

Test: The backend tests create a year before and after a plan in force and read the draft.
