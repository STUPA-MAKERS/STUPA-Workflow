---
id: "000812"
title: An amount field of a draft saves when the person leaves it
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# An amount field of a draft saves when the person leaves it

An amount field in the table of a draft must save its value when the person leaves the field.
The plan page must then show the new sums and the new balance. The table must not have a
save button.

Reason: A draft does not bind, and a value that is saved at once is not lost when the tab
closes.
