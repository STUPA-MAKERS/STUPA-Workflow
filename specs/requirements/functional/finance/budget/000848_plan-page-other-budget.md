---
id: "000848"
title: Another budget takes the budget before off the plan page
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

# Another budget takes the budget before off the plan page

When the person chooses another budget on the plan page, each part of the budget before must
go off the page at once: its plan, its years, its selected Kostenstelle and its actions. A
late answer for the budget before must stay off the page.

Reason: An action under the name of the new budget would else change a plan of the budget
before, for example delete its draft, and the URL would name a Kostenstelle beside a budget
that is not its own.

Test: One component test chooses another budget while the years load and reads that the plan
and the actions of the budget before are gone and that the years of a budget that the person
left stay off the page. One test reads that the selected Kostenstelle is gone.
