---
id: "000811"
title: An unbalanced draft cannot go to the vote
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

# An unbalanced draft cannot go to the vote

The button "Zur Abstimmung geben" must be disabled while the draft is not balanced. The
plan page must then show a warning note with the difference.

Reason: The backend refuses an unbalanced version, and the person must see the cause first.
