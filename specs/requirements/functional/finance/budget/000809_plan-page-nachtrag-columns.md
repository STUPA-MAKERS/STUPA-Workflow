---
id: "000809"
title: A Nachtrag is shown beside the version in force
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

# A Nachtrag is shown beside the version in force

For a Nachtrag, the tables of the plan page must have the columns Kostenstelle, Ansatz of
the Nachtrag, Ansatz of the version in force and Änderung.

Reason: The STUPA decides the change, so the person must see the two amounts side by side.
