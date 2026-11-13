---
id: "000834"
title: An inactive Kostenstelle is hidden in the Budget tab
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/budget/cost-centre/cost-centre.util.spec.ts:CostCentreUtil"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_inactive_cost_centre_hides_the_ones_below_it"
implementation:
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/cost-centre/cost-centre.util.ts
  - frontend/src/app/pages/budget/budget-tree.api.ts
  - backend/app/modules/budget/form_options.py
  - backend/app/modules/search/service.py
scope:
  - frontend/src/app/pages/budget
  - backend/app/modules/budget
  - backend/app/modules/search
  - mcp
---

# An inactive Kostenstelle is hidden in the Budget tab

The Budget tab and each Kostenstelle picker must not show a Kostenstelle that is not
active, and none below it. The Kostenstelle options of the application form and the global
search must follow the same rule. A person with `budget.structure` must still see it in the
Budget tab, marked "inaktiv", so that the person can set it active again. A Kostenstelle
must have no separate flag that hides it in the Budget tab: the platform must not keep
`hiddenInBudget`.

Reason: Two switches with the same effect make a person choose between them without a
difference.

Test: The dashboard test reads the tree with and without `budget.structure`. The backend test
sets a Kostenstelle inactive and reads the form options and the search.
