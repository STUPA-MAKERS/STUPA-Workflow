---
id: "000851"
title: A budget page drops the answer of an older tree read
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/budget-dashboard.component.ts
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# A budget page drops the answer of an older tree read

The tabs Bewirtschaftung and Planung must drop the answer of a tree read that went out
before the read whose answer is on the page. This holds for the first tree read of a page
too.

Reason: Each save of a Kostenstelle reads the tree again. An answer that arrives late would
else put older names and values back on the page.

Test: One test of each page answers two tree reads in the other order and reads the tree of
the newer one, and one answers the first read of the page after a later read.
