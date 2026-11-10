---
id: "000611"
title: An attendance cell holds its badges
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.spec.ts:cellBadges"
implementation:
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.html
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.scss
scope:
  - frontend/src/app/features/gremien/gremium-attendance
---

# An attendance cell holds its badges

In the attendance matrix of a Gremium, the badges of a cell must stand inside the cell, after
the count. The badge of the excused meetings must show the number and "E" (for example "4E"),
and the badge of the meetings with a transferred vote must show the number and "V" (for example
"1V"). The legend must show the same badges. A cell without an attended meeting must show its
count in the muted text colour.

Reason: A bare number on the corner of a cell reads as a notification count, and the neighbour
cell cuts it.

Test: `frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.spec.ts`.
