---
id: "000610"
title: A month without a meeting is a narrow column with a dash
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.spec.ts:emptyMonth"
implementation:
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.html
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.scss
scope:
  - frontend/src/app/features/gremien/gremium-attendance
---

# A month without a meeting is a narrow column with a dash

In the attendance matrix of a Gremium, a month without a closed meeting must be a narrow
column. Its head must show only the month. Each of its cells must show a dash without a box,
also for a person who was not a member in that month.

Reason: A range often holds months without a meeting, for example the lecture-free time. Boxes
in these months fill most of the matrix and hide the months that hold data.

Test: `frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.spec.ts`.
