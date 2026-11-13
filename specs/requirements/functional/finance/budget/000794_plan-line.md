---
id: "000794"
title: A plan line holds the Ansatz of one Kostenstelle
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_parent_holds_the_sum_of_its_children"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_delete_line_lowers_the_parent"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_delete_node_lowers_the_parent_of_a_draft"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_set_line_heals_every_parent_of_the_version"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_copy_gives_each_parent_the_sum_of_its_children"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_first_child_line_takes_the_ansatz_of_its_parent"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_sum_above_the_largest_amount_is_refused"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_summed_amounts_give_each_parent_the_sum_of_its_children"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "frontend/src/app/pages/budget/cost-centre/cost-centre-create.component.spec.ts:CostCentreCreateComponent"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_an_amount_of_minus_zero_is_zero"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/plan_schemas.py
scope:
  - backend/app/modules/budget
---

# A plan line holds the Ansatz of one Kostenstelle

A plan version must have at most one line for each Kostenstelle below the top level. A line
must hold an Ansatz from 0 € and an optional Erläuterung. A Kostenstelle with a child that
has a line in the version must hold the sum of the Ansätze of those children as its Ansatz.
The platform must set that sum on each level after each change and each removal of a line,
after the delete of a child Kostenstelle and in each new version that copies lines. The
platform must answer 422 `plan_amount_too_large` when a sum passes 9 999 999 999,99 €. A
person must not set the Ansatz of such a Kostenstelle: the platform must ignore an amount
that a request gives for it, and the plan must show no Ansatz field for it. When the sum
falls below the gesperrt amount of the parent, the platform must lower that amount to the
sum. A Kostenstelle without such a child keeps the Ansatz that a person set. An amount of
minus zero must count as 0 €: the answer and the audit entry must show `0.00`.

The first child line of a Kostenstelle must take the Ansatz and the gesperrt amount of
that Kostenstelle when the request names no Ansatz above 0 €. The form for a new
Kostenstelle in a draft must show that Ansatz as its start value.

Reason: LHO § 17 tells the Studierendenschaft to plan each purpose apart and to explain it.
A person types the amounts of the lowest Kostenstellen only, so a parent can never stand
above or below the sum of its children. The first child takes the Ansatz of its parent, so
the split of a Kostenstelle loses no planned amount.

Test: The tests change, remove and copy lines of children on two levels and read the Ansatz of
each parent. The plan page shows no Ansatz field for a parent.
