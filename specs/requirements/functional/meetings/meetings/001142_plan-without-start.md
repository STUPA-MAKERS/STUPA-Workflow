---
id: "001142"
title: Without a start time the agenda shows only durations
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/agenda-plan.util.spec.ts:planNoStart"
  - "frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.spec.ts:planRowsNoStart"
implementation:
  - frontend/src/app/features/meetings/agenda-plan.util.ts
  - frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.ts
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - mcp
---

# Without a start time the agenda shows only durations

When the Sitzung has no start time, the agenda must show no planned start. Each TOP with a
duration must show `N Min.` in the row subline. The agenda must not show the sum of the
durations, not below the last row and not in the head, because the agenda pane ends with its
list (spec 001330) and a heading carries no count.

Reason: A planned clock time needs a start. A line below the list would be a footer segment of
the pane, and the pane has none.

Test: Component test of the agenda pane: without a start time no row shows `ca. HH:MM`, and the
pane shows no sum.
