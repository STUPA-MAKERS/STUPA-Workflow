---
id: "000893"
title: A skeleton has the shape of the loaded page
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/applications/applications-detail.component.spec.ts:ApplicationsDetailComponent"
  - "frontend/src/app/pages/graph/graph.component.spec.ts:GraphComponent"
  - "frontend/src/app/features/meetings/meeting-page-skeleton/meeting-page-skeleton.component.spec.ts:MeetingPageSkeletonComponent"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.html
  - frontend/src/app/pages/budget/budget-dashboard.component.html
  - frontend/src/app/pages/applications/applications-detail.component.html
  - frontend/src/app/pages/tickets/ticket-detail.component.html
  - frontend/src/app/features/gremien/gremium-detail/gremium-detail.component.html
  - frontend/src/app/features/meetings/meeting-page-skeleton/meeting-page-skeleton.component.html
  - frontend/src/app/pages/graph/graph.component.html
scope:
  - frontend/src/app/
---

# A skeleton has the shape of the loaded page

A loading skeleton must stand in the containers of the loaded page: the same pane, sheet,
section headings, columns and rows. A part that the page shows in most cases must have a
placeholder of its height. A list uses `app-skeleton variant="items"`, a table its own
`loading` input. A skeleton must not show an amount or a count before the data is there.

A head stands in the shape of its controls: the buttons of a connected button group as
`.skel-grp` with `.skel-btn` (the same height, gap and corners), the meta chips as `.skel-chips`
with `.skel-chip`, and a tab bar with a bar for each label. A page whose content is a drawing
(the graph) shows the empty canvas with its tools, not rows.

Reason: A skeleton in another shape makes the page jump when the data arrives, and a block of
grey panels reads as a different page.

Test: A review of each UI change with a screenshot of the skeleton beside the loaded page. A
unit test of a page with a container skeleton checks the headings and the containers.
