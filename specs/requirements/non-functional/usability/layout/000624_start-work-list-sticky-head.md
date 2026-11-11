---
id: "000624"
title: The work list on Start keeps its column header and cuts at the window edge
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/vendor/ui-kit/src/lib/data-table/data-table.component.spec.ts:stickyHead"
implementation:
  - frontend/vendor/ui-kit/src/lib/data-table
  - frontend/src/app/pages/dashboard/dashboard.component.scss
scope:
  - frontend/src/app/pages/dashboard
  - frontend/vendor/ui-kit/src/lib/data-table
---

# The work list on Start keeps its column header and cuts at the window edge

On a desktop width, the tables "Offene Aufgaben" and "Meine Anträge" on the start page must
scroll inside their panel below the tab line. The column header of the table must stay at the
top of the panel while the rows pass under it. The panel must run to the bottom edge of the
window, and the rows must cut hard at that edge. The panel must not fade at either end. The
panel keeps no room for a floating button (000650).

Reason: A header that scrolls away leaves the columns without names. The bottom edge of the
window is a real line, so a fade there hides rows for no gain (000575, 000527).

Test: `data-table.component.spec.ts` (`stickyHead`) and screenshots of both tabs scrolled to
the middle and to the end, in the light and the dark theme.
