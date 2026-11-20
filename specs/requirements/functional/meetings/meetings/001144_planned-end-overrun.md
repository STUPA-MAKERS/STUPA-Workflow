---
id: "001144"
title: The agenda shows no planned end and no overrun
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.spec.ts:planRowsOverrun"
implementation:
  - frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.html
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - mcp
---

# The agenda shows no planned end and no overrun

The agenda must not show a line with the planned end below the last row, because the agenda
pane ends with its list (spec ui-kit:001440). The planned start of each TOP in its row subline stays
(spec 001141). When the planned end of the last TOP is later than the end time of the Sitzung,
the agenda must not mark it, and no row must change its colour.

Reason: The planned start in each row already shows how far the plan reaches. A mark would need
a footer segment below the list or a colour that the row does not otherwise have.

Test: Component test of the agenda pane: with a planned end after the end time of the Sitzung,
no row carries a warning class and no end line is shown.
