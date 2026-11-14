---
id: "000893"
title: A skeleton has the shape of the loaded page
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.html
  - frontend/src/app/pages/budget/budget-dashboard.component.html
scope:
  - frontend/src/app/
---

# A skeleton has the shape of the loaded page

A loading skeleton must stand in the containers of the loaded page: the same pane, sheet,
section headings, columns and rows. A part that the page shows in most cases must have a
placeholder of its height. A list uses `app-skeleton variant="items"`, a table its own
`loading` input. A skeleton must not show an amount or a count before the data is there.

Reason: A skeleton in another shape makes the page jump when the data arrives, and a block of
grey panels reads as a different page.

Test: A review of each UI change with a screenshot of the skeleton beside the loaded page. A
unit test of a page with a container skeleton checks the headings and the containers.
