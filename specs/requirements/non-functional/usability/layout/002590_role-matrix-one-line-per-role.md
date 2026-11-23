---
id: "002590"
title: Each role of the role matrix is one line
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/pages/admin/gremium-roles/gremium-role-matrix.component.spec.ts:oneColumnPerRight"
implementation:
  - frontend/src/app/pages/admin/gremium-roles/gremium-role-matrix.component.html
  - frontend/src/app/pages/admin/gremium-roles/gremium-role-matrix.component.scss
scope:
  - frontend/src/app/pages/admin/gremium-roles
---

# Each role of the role matrix is one line

The matrix "Gremienrollen und Berechtigungen" must have one column for each right of the
catalogue of Gremium rights. The number of columns must come from the catalogue, not from a
fixed number in the stylesheet. In a wide container, each role must be one line: the name and
the groups, then one box for each right below its column head, then the ⋮ menu at the end of
the line. The column heads must be one line of heads above the roles. A long head must break
inside its column and must not overlap the next column. In a narrow container, the matrix
keeps the chip layout of a role card.

Reason: A new right ("Mitglieder benachrichtigen", 001851) added a column to the catalogue,
but the grid kept five right columns. Each role then wrapped into a second line, and the ⋮
menu stood below the boxes.

Test: Frontend component test: the grid gets the number of rights of the catalogue.
