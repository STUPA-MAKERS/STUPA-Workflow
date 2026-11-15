---
id: "001021"
title: A plan shows the Änderung only against an Ansatz
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
  - frontend/src/app/pages/budget/plan/budget-plan.component.html
scope:
  - frontend/src/app/pages/budget
---

# A plan shows the Änderung only against an Ansatz

The tables and the detail of a line must show the Änderung only when the plan has an
Ansatz to compare against: the version before a Nachtrag, or the plan in force of the year
before (000889). Without one, the column "Änderung" and the figure "Änderung" must not
show.

Reason: Without an Ansatz to compare against, every row of the column shows "–", and the
column takes the width of a name.

Test: The component test reads the columns and the figures of a plan in the first year and
of a plan with a year before without a plan in force.
