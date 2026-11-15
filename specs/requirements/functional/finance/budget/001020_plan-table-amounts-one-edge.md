---
id: "001020"
title: The amounts of a plan table end on one edge
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.html
  - frontend/src/app/pages/budget/plan/budget-plan.component.scss
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# The amounts of a plan table end on one edge

The plan page must show every amount with its cents, also an amount without cents
("0,00 €", not "0 €"). This applies to the tables, the figures, the group sums and the tree.

In a table with amount fields (000810), the sum of a parent must have the width and the
inner padding of a field, with its € at the place of the € of a field, and the weight of the
text of a field. So each amount and each € of the column end on one edge.

On a wide screen the rows of the plan tables must stand on surface 2 of the sheet (surface 1),
with surface 1 between them, as the row groups on a pane do.

An amount field in a table row must have no fill and a thin edge. The hover of a row must
not hide the box of a field. A display setting that colours the fields (000598, very high
contrast) must still colour them.

Reason: In one column, "150.475,00 €" in a field, "0 €" in bold beside it and "0,00 €"
in the next field read as three formats. The fill of a field has the colour of a row under
the pointer, so the field of that row looks like plain text. Rows on the surface of the sheet do not
stand apart from it.

Test: The component test reads the sum of a parent beside the fields: its width class, its
digits with cents and its € apart. The other tests of the page read amounts with cents.
