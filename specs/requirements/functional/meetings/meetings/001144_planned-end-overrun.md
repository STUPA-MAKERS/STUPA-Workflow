---
id: "001144"
title: The agenda marks an overrun on the last TOP
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/agenda-plan.util.spec.ts:planOverrun"
  - "frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.spec.ts:planRowsOverrun"
implementation:
  - frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.html
  - frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.scss
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - mcp
---

# The agenda marks an overrun on the last TOP

The agenda must not show a line with the planned end below the last row, because the agenda
pane ends with its list (spec 001330). The planned start of each TOP in its row subline stays
(spec 001141). When the Sitzung has an end time and the planned end of the last TOP is later than
it, the subline of the last row must use the warning colour and keep its text. The mark must not
change the end time of the Sitzung.

Reason: The person who plans the agenda sees at once that the TOPs do not fit into the time of
the Sitzung, without a footer segment below the list.

Test: Component test of the agenda pane: the last row carries the warning class when the planned
end is after the end time, and no row carries it otherwise.
