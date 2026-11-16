---
id: "000806"
title: The plan page shows the steps of the version
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "frontend/src/app/pages/budget/plan/budget-plan.util.spec.ts:BudgetPlanUtil"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# The plan page shows the steps of the version

The plan page must show the state of the version with the step display of the ui-kit. The
steps must be "Entwurf", each step of the version by its name, and "In Kraft". A passed
step must show a check mark and its date. A draft must show the steps of its budget. A step
that waits for its Gremium must show that it waits for a meeting and each meeting that has
the plan on its agenda, and "Abstimmung läuft" while its vote is open (000838). A vote that
is not accepted sends the version back to the draft, so no step shows "Abgelehnt".

Reason: The person must see which steps the version has passed and which steps remain.

Test: The component tests read the step display of a draft, of a version between its steps and
of a version in force, and the state of the vote of a step.
