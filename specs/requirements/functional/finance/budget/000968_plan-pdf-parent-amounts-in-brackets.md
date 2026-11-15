---
id: "000968"
title: The plan PDF shows the amounts of a line with lines below it in brackets
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/budget/test_plan_export.py:test_the_pdf_shows_the_amounts_of_a_line_with_lines_below_in_brackets"
implementation:
  - backend/app/modules/budget/plan_export.py
scope:
  - backend/app/modules/budget/plan_export.py
---

# The plan PDF shows the amounts of a line with lines below it in brackets

In the PDF of a Haushaltsplan (000875), each amount of a line that has a line of the version
below it in the tree must stand in brackets, for example `(1.200,00)`. An amount of a line
without such a line below it must stand without brackets. The rule applies to every amount
column of the line. The XLSX file keeps all amounts as plain numbers.

Reason: The Ansatz of a parent is the sum of the Ansätze of its children. The brackets show
that the amount is a subtotal and that the reader must not add it to the lines below it.

Test: A unit test builds the export of a tree with a parent line and a child line and
compares the cells of the PDF request.
