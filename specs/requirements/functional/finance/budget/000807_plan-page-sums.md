---
id: "000807"
title: The plan page shows the sums and the balance
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "frontend/src/app/pages/budget/plan/budget-plan.util.spec.ts:BudgetPlanUtil"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# The plan page shows the sums and the balance

The plan page must show the sum of the income Ansätze, the sum of the expense Ansätze and
their difference. It must show "Ausgeglichen" for a difference of 0 € and "Nicht ausgeglichen"
for a different value.

Reason: The plan must be balanced before the decision.

Test: The component test reads the two sums and the difference of a balanced and of an
unbalanced version.
