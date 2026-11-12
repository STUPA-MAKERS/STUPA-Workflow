---
id: "000822"
title: A year with a plan shows only its Kostenstellen
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/budget/plan/budget-plan.util.spec.ts:yearMembers"
implementation:
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/plan/budget-plan.util.ts
scope:
  - frontend/src/app/pages/budget
---

# A year with a plan shows only its Kostenstellen

The view Bewirtschaftung and each Kostenstelle picker must show, for a fiscal year that has
a version in force, only a Kostenstelle that has a line in that version or a booking or an
Antrag in that year. The top-level Kostenstelle must always show. A year without a plan
must show each Kostenstelle.

Reason: A Kostenstelle that is not in the plan of a year has no Ansatz there. It stays
visible while it holds a booking, because the booking must be found and moved.
