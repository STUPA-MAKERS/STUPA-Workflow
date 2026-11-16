---
id: "000968"
title: The plan PDF prints a line with lines below it in grey
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/budget/test_plan_export.py:test_the_pdf_marks_a_line_with_lines_below_as_grey"
  - "typst/tests/test_plan.py:test_a_line_with_lines_below_keeps_its_leaf_flag"
implementation:
  - backend/app/modules/budget/plan_export.py
  - typst/typst_service/document.py
  - typst/template/plan.typ
scope:
  - backend/app/modules/budget/plan_export.py
  - typst/typst_service/document.py
  - typst/template/plan.typ
---

# The plan PDF prints a line with lines below it in grey

In the PDF of a Haushaltsplan (000875), every cell of a line that has a line of the version
below it in the tree must print in grey (`#666666`). A line without such a line below it must
print in black. An amount must not stand in brackets. The group headings, the sums of a side
and the balance are not lines of the tree and keep their style. The XLSX file keeps all amounts
as plain numbers in black.

Reason: The Ansatz of a parent is the sum of the Ansätze of its children. The grey shows that
the amount is a subtotal and that the reader must not add it to the lines below it. `#666666`
on white has a contrast of 5.7:1, so the text stays readable on screen and in print.

Test: A unit test builds the export of a tree with a parent line and a child line and checks
that the PDF request marks only the parent as not a leaf and holds no brackets.
