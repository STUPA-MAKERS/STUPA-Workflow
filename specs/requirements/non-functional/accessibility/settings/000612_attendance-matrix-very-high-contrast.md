---
id: "000612"
title: The attendance matrix follows very high contrast
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.styles.spec.ts:veryHighContrast"
implementation:
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.html
  - frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.component.scss
scope:
  - frontend/src/app/features/gremien/gremium-attendance
---

# The attendance matrix follows very high contrast

With "Hoher Kontrast" on (000605), every attendance cell that opens the meetings of a
month and the sort button "Gesamt" must be black on yellow with the black edge of 000598. A
badge in a cell must be a black plate with yellow text. The rows of the matrix must have the
2 px white edge of a row group. The legend must not show the entries for the colour steps
("an allen Sitzungen", "an einigen", "an keiner"), because the cells show no colour steps in
this mode; the count in the cell tells the share. On a phone, a cell of a person card is not a
control, so it must be white text with a white edge and without a fill.

Reason: The colour steps of the cells are tints of the accent colour, and 000605 allows no
tint. A cell is a control, so it must look like every other control in this mode.

Test: `frontend/src/app/features/gremien/gremium-attendance/gremium-attendance.styles.spec.ts`.
