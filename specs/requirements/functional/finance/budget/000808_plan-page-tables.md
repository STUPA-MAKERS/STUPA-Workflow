---
id: "000808"
title: The plan page lists income and expenses in two tables
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# The plan page lists income and expenses in two tables

The detail of the plan must show the lines in the two tables "Einnahmen" and "Ausgaben". Each table
must have the columns Kostenstelle, Ansatz, Ansatz of the year before, Ist of the year
before and Änderung. In a window from 1200 px to below 1340 px, a table with the two
columns of the year before must not show the column Änderung; the detail of a line shows
the Änderung at every width. The Vermerke of a line must show below its name. A child Kostenstelle
must be indented below its parent.

Reason: LHO § 15 tells the Studierendenschaft to show income and expenses apart. In a
window below 1340 px the four amount columns leave about 110 px for the name, and a name or
a Vermerk of a deep Kostenstelle then breaks into lines of one or two letters.

Test: The component test reads the columns and the rows of the two tables.
