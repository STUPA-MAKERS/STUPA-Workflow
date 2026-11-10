---
id: "000609"
title: The attendance matrix looks like a row group
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.styles.spec.ts:rowGroupLook"
implementation:
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.html
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.scss
scope:
  - frontend/src/app/features/gremien/gremium-attendance
---

# The attendance matrix looks like a row group

The attendance matrix of a Gremium (tab "Anwesenheit") must look like the list of the tab
"Mitglieder". The column titles must be a plain line of small capitals without a bar. The
persons must be the rows of a row group on surface 2, with the rounded outer corners of a row
group and without lines between the cells. The line "Ø anwesend je Sitzung" must be a plain
line below the rows without a bar. A cell with a count must be a pill that is at most 6 rem
wide. The matrix must stay a table for a screen reader.

Reason: A boxed table with a head bar, cell lines and wide cell blocks is a second list style
in the same Gremium, and a person reads it as a part of another app.

Test: `frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.styles.spec.ts`.
