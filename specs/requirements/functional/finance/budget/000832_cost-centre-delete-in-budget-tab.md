---
id: "000832"
title: A Kostenstelle is deleted in the Budget tab
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# A Kostenstelle is deleted in the Budget tab

The Budget tab must offer the action "Kostenstelle löschen" for the selected Kostenstelle
to a person with `budget.structure`, after a confirmation. The page must show the refusal
of a Kostenstelle that is in use (000254) or in a plan (000820) as a message.

Reason: Verwaltung does not list a Kostenstelle below a budget (000828), so the Budget tab
is the only place for the action.

Test: The page tests delete a Kostenstelle after the confirmation and read the message of a
refused delete.
