---
id: "000833"
title: The allocation of a year without a plan is set in the Budget tab
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
implementation:
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
scope:
  - frontend/src/app/pages/budget
---

# The allocation of a year without a plan is set in the Budget tab

For a fiscal year without a plan, the detail of a selected Kostenstelle in the view
Bewirtschaftung must let a person with `budget.structure` set its allocation. A year with a
plan must not offer the field (000798).

Reason: A budget without a Haushaltsplan has no Ansatz. Its allocation is set by hand, and
Verwaltung no longer lists its Kostenstellen (000828).
