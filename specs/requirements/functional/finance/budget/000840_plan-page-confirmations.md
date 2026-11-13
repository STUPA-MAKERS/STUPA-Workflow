---
id: "000840"
title: The plan page asks before an action that binds or deletes
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# The plan page asks before an action that binds or deletes

The plan page must ask for a confirmation before each of these actions: "In Kraft setzen",
"Schritt abschließen", "Zurück in den Entwurf", "Entwurf löschen", "Zeile entfernen" and
"Kostenstelle löschen". The dialog must name what the action changes. A cancelled dialog
must change nothing. The page must send no second request while a request of an action
runs.

Reason: A version in force sets the allocations of the year, and a deleted draft is gone.
One press must not do that by mistake.

Test: The component tests press each of these actions, read the dialog, cancel it and confirm
it.
