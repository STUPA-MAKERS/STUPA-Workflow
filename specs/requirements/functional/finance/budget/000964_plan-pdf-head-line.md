---
id: "000964"
title: The head line of the plan PDF sits tight between the title and the table
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "typst/tests/test_plan.py:test_the_head_line_sits_tight_between_the_title_and_the_table"
implementation:
  - typst/template/plan.typ
scope:
  - typst/template/plan.typ
---

# The head line of the plan PDF sits tight between the title and the table

In the PDF of a Haushaltsplan (000875), the line with Haushalt, Haushaltsjahr, Version and
Stand must have at most 0.2 cm of space below the rule of the title and at most 0.25 cm of
space above the table. The block spacing of the page must not add to these gaps.

Reason: The head line is one short line of data. With the block spacing of the page added
above and below it, it took the height of three lines and pushed the table down.

Test: A test of the typst service renders a plan and compares the tops of the title, of
the head line and of the table heading in the PDF.
