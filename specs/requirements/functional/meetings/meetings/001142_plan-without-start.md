---
id: "001142"
title: Without a start time the agenda shows only durations and the sum
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
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

# Without a start time the agenda shows only durations and the sum

When the Sitzung has no start time, the agenda must show no planned start. Each TOP with a
duration must show `N Min.` in the row subline. One line below the last row must show the sum of
all durations as `Dauer ca. N Min.` when at least one TOP has a duration. The head of the agenda
must not show the sum, because a heading carries no count.

Reason: A planned clock time needs a start. The sum still tells how long the Sitzung takes.

Test: Component test of the agenda pane: without a start time no row shows `ca. HH:MM`, and the
line below the last row shows the sum.
