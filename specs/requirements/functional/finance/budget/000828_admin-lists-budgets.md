---
id: "000828"
title: Verwaltung lists only the budgets
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
implementation:
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
  - frontend/src/app/app.routes.ts
scope:
  - frontend/src/app/pages/admin/budgets
---

# Verwaltung lists only the budgets

The page of Verwaltung for the Kostenstellen must have the name "Budgets" and the path
`/admin/budgets`. It must list only the top-level Kostenstellen, each with the start of its
fiscal year and with "Mit Haushaltsplan" or "Ohne Haushaltsplan". It must not show a
Kostenstelle below a budget. The page must keep the creation of a budget, the edit form of
a budget and the fiscal years of a budget. The path `/admin/cost-centres` must lead to the
new path.

Reason: A Kostenstelle below a budget belongs to the plan of a year. It comes and goes
with the plan, so it is no setting of the platform.

Test: The component tests read the list, create, edit and delete a budget and open its fiscal
years.
