---
id: "000794"
title: A plan line holds the Ansatz of one Kostenstelle
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_parent_holds_the_sum_of_its_children"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_delete_line_lowers_the_parent"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_summed_ancestors_follow_the_children_up_to_the_top"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
scope:
  - backend/app/modules/budget
---

# A plan line holds the Ansatz of one Kostenstelle

A plan version must have at most one line for each Kostenstelle below the top level. A line
must hold an Ansatz from 0 € and an optional Erläuterung. A Kostenstelle with a child that
has a line in the version must hold the sum of the Ansätze of those children as its Ansatz.
The platform must set that sum after each change and each removal of a line of a child, so
the Ansatz of the parent rises and falls with its children. A person must not set the Ansatz
of such a Kostenstelle: the platform must ignore an amount that a request gives for it, and
the plan must show no Ansatz field for it. When the sum falls below the gesperrt amount of
the parent, the platform must lower that amount to the sum. A Kostenstelle without such a
child keeps the Ansatz that a person set.

Reason: LHO § 17 tells the Studierendenschaft to plan each purpose apart and to explain it.
A person types the amounts of the lowest Kostenstellen only, so a parent can never stand
above or below the sum of its children.
