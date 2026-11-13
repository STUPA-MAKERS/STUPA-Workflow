---
id: "000818"
title: A plan line makes a Kostenstelle part of the year
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_tree_names_the_years_that_plan_a_cost_centre"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_with_plan_fields"
implementation:
  - backend/app/modules/budget/tree/view.py
  - backend/app/modules/budget/plan_rules.py
scope:
  - backend/app/modules/budget
---

# A plan line makes a Kostenstelle part of the year

A Kostenstelle must be part of a fiscal year with a Haushaltsplan when the version in force
has a line for it. A line with an Ansatz of 0 € must count. A Kostenstelle without a line
must stay in the tree and in the other years. The read of the tree must name, for each
Kostenstelle, the fiscal years whose version in force has a line for it, and for a
top-level Kostenstelle the fiscal years with a version in force (`plannedIn`).

Reason: The Haushaltsplan of a year names its Titel, and the set of Titel changes from year
to year. One tree for all years needs the plan to say which Kostenstellen a year has.

Test: The backend test brings versions into force and reads `plannedIn` of each Kostenstelle in
the tree.
