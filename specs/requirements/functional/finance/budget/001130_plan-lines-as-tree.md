---
id: "001130"
title: The lines of a plan show as a tree
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.html
  - frontend/src/app/pages/budget/plan/budget-plan.component.scss
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget/plan
---

# The lines of a plan show as a tree

The plan page must show the lines of a plan as a tree. This applies to the list beside the
plan, to the tables of the plan and to the plan on a phone.

A line with lines below it must have a chevron in front of its name. The chevron opens and
closes the lines below it. When the page opens, the Titel are open and the lines below them
are closed. A line that the person selects, also by the URL, opens the lines above it. While
the search has a text, every hit shows and the chevrons are disabled. The table of the lines
below a selected line (000815) has no chevrons.

In the list and on a phone, a vertical line for each level above a row must run through the
column of the chevrons, from the first to the last row below that level.

A line with lines below it holds a sum (001041). It has the colours of every other line.

A name in the list and on a phone breaks into a second line. Only a name that is longer than
two lines is cut.

On a phone the plan must show the lines as rows of the tree, with the name at the start and
the amount at the end, instead of a table card for each line. A press on a row opens the line
in the bottom sheet (000810).

Reason: A plan by the Haushaltstitel of the Land has up to five levels. Shown only by indent,
the levels cannot be told apart, the deep names are cut, and the many parent lines with
0,00 € hide the lines with an Ansatz. On a phone each line was a card three rows high.

Test: The component test closes and opens a line in the list and the table, searches in a
closed line, selects a line below a closed line, and reads the rows of the tree on a phone.
