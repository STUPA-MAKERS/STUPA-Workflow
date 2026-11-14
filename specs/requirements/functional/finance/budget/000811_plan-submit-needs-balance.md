---
id: "000811"
title: An unbalanced draft cannot go to the vote
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# An unbalanced draft cannot go to the vote

The actions that take a draft out of the draft must be disabled while the draft has no
line or is not balanced: "Schritt abschließen", "Abstimmung anlegen" and "In Kraft setzen".
Each disabled action must name the cause. The plan page must show a warning note with the
difference while the draft is not balanced.

Reason: The backend refuses an unbalanced version, and the person must see the cause first.

Test: The component test opens an unbalanced draft and reads the state of each action and the
note.
