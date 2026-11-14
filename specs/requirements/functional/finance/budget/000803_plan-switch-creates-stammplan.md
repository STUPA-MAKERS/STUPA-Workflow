---
id: "000803"
title: The plan switch gives each open fiscal year a draft
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
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

# The plan switch gives each open fiscal year a draft

When a person sets the plan switch (000814) of a Haushalt to on, the platform must give
each open fiscal year of that Haushalt that has no Haushaltsplan a Haushaltsplan with one
version in `draft` (000854). The Ansatz of a node without a child must equal its
allocation, and a parent must hold the sum of its children (000794). The switch must
change no allocation, so the request has no preview and no confirmation, and the edit form
of the Haushalt asks for nothing. A closed fiscal year must not get a Haushaltsplan.

A fiscal year that a person creates for a Haushalt with the switch on must get its draft
at once. The draft must copy the lines, the Ansätze, the Vermerke and the sides of the
version in force of the latest fiscal year before it that has one (000837). Without such a
year the draft must hold a line for each node with an Ansatz of 0 € and no side.

Reason: A current year needs the plan for a Nachtrag. A closed year does not change. The
switch brings no plan into force, because no body decided one. The plan of a year starts
from the plan of the year before.

Test: The backend tests switch a Haushalt on and read the draft and the allocations of each
year, and create a year before and after a plan in force. The form test turns the switch on
and reads the requests.
