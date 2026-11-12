---
id: "000794"
title: A plan line holds the Ansatz of one Kostenstelle
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_set_line_raises_the_parent"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_raised_ancestors_raises_each_parent_up_to_the_top"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
scope:
  - backend/app/modules/budget
---

# A plan line holds the Ansatz of one Kostenstelle

A plan version must have at most one line for each Kostenstelle below the top level. A line
must hold an Ansatz from 0 € and an optional Erläuterung. When the sum of the Ansätze of the
children exceeds the Ansatz of the parent, the platform must raise the Ansatz of the parent
to that sum. An Ansatz of a parent below the sum of its children must answer 422
`plan_line_below_children`.

Reason: LHO § 17 tells the Studierendenschaft to plan each purpose apart and to explain it.
A person types the amounts of the lowest Kostenstellen first.
