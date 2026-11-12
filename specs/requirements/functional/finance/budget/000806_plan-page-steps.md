---
id: "000806"
title: The plan page shows the state as four steps
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "frontend/src/app/pages/budget/plan/budget-plan.util.spec.ts:stepIndex"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# The plan page shows the state as four steps

The plan page must show the state of the version with the step display of the ui-kit. The
steps must be "Entwurf", "Beschlossen", "Genehmigt" and "In Kraft". A finished step must show
a check mark.

Reason: The person must see which steps the version has passed and which steps remain.
