---
id: "001144"
title: The agenda shows the planned end and marks an overrun
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
implementation: null
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - mcp
---

# The agenda shows the planned end and marks an overrun

When the plan has a start, the agenda must show the planned end of the last TOP as one line
`Ende ca. HH:MM` below the last row. When the Sitzung has an end time and the planned end is
later than it, the line must read `Ende ca. HH:MM · nach dem Sitzungsende HH:MM` and use the
warning colour. The text must name the overrun, because a colour alone does not reach every
reader (the look "Sehr hoher Kontrast" has no warning colour). The line must not change the end
time of the Sitzung.

Reason: The person who plans the agenda sees at once that the TOPs do not fit into the time of
the Sitzung.

Test: Component test of the agenda pane: the line shows the planned end, and it carries the
warning class when the end is after the end time.
