---
id: "000624"
title: The work list on Start keeps its column header and cuts at the window edge
kind: non-functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-19
replaced_by: F/collaboration/activity/001300
scope:
  - frontend/src/app/pages/activity
  - frontend/vendor/ui-kit/src/lib/data-table
---

# The work list on Start keeps its column header and cuts at the window edge

On a desktop width, the tables "Offene Aufgaben" and "Meine Anträge" on the start page must
scroll inside their panel below the tab line. The column header of the table must stay at the
top of the panel while the rows pass under it. The panel must run to the bottom edge of the
window, and its edges follow 000193. The
panel keeps no room for a floating button (000650).

Reason: A header that scrolls away leaves the columns without names. The bottom edge of the
window is a real line, so a fade there hides rows for no gain (000193).

Test: `data-table.component.spec.ts` (`stickyHead`) and screenshots of both tabs scrolled to
the middle and to the end, in the light and the dark theme.
