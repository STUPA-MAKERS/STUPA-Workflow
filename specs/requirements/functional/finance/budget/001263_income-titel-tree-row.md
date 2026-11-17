---
id: "001263"
title: The tree row of an income Titel shows its Ansatz and the reached part
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-17
tests:
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
implementation:
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/budget-dashboard.component.html
scope:
  - frontend/src/app/pages/budget
---

# The tree row of an income Titel shows its Ansatz and the reached part

The row of a node that is income in the selected year must show the Ansatz of its line
instead of the allocation 0. Its bar must show `Ist / Ansatz` in the colour of the node,
full at 100 % and above, and its label must read "{percent} % erreicht".

Reason: The amount of a row is the Ansatz on both sides; only the bar reads as progress
for an income and as use for an expense.

Test: The page test reads the amount, the bar and its label of an income Titel.
